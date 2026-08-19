"""
Persistent-capture audio recorder.

One long-lived ffmpeg per source streams raw PCM over a pipe; Python cuts
fixed-duration WAV segments and publishes them with the same tmp+rename
contract as the per-segment recorders in audio_manager. ffmpeg is respawned
only on failure or stall, not per segment, which removes the inter-segment
capture gap (process spawn + source handshake) that costs 5-11s per cycle
on slow devices.

Writing each segment in a single burst at completion (instead of streaming
it over its whole duration) also keeps the file's dirty-page age below the
kernel writeback deadline, so short-lived queue files can die in the page
cache instead of hitting the SD card.
"""

import collections
import fcntl
import logging
import os
import select
import subprocess
import threading
import time
import wave
from datetime import timedelta

from core.audio_manager import BaseRecorder, _parse_ffmpeg_error
from core.fd_diagnostics import log_fd_exhaustion_if_needed
from core.native_lock import native_lock
from core.timezone_service import local_now

logger = logging.getLogger(__name__)

# No PCM for this long after audio has begun → stream stalled; respawn ffmpeg.
STALL_TIMEOUT_SECONDS = 10.0
# Allowance for the first PCM byte of a session: process start + source
# handshake can take 10-15s on slow devices (measured on Pi Zero 2W), so the
# tight stall timeout only applies once audio is flowing.
STARTUP_TIMEOUT_SECONDS = 45.0
# Discard finished segments instead of publishing while the analysis queue
# is at least this deep. Gapless capture removes the accidental load-shedding
# the old spawn gap provided, so shedding must be explicit or the queue can
# grow without bound on devices where inference is slower than capture.
MAX_QUEUE_DEPTH = 3
# Within a session, segment names are sample-count contiguous (each advances
# by exactly chunk_duration): delivery jitter, catch-up bursts, and publish
# backpressure never perturb the timeline. If the timeline nevertheless
# diverges from the wall clock beyond this for this many consecutive
# boundaries (accumulated audio loss, a skewed source clock, or a system
# clock step — DST fall-back, an NTP correction), naming is re-anchored to
# the wall clock IN PLACE: no session restart, no capture gap. A backward
# re-anchor may repeat local timestamps; that is inherent to naive local
# time (the DST fall-back hour genuinely repeats on the clock).
WALL_REANCHOR_SECONDS = 30.0
WALL_REANCHOR_BOUNDARIES = 4
READ_BLOCK_BYTES = 65536
# Enlarged pipe so a briefly stalled reader can't block ffmpeg's writes.
PIPE_BUFFER_BYTES = 1 << 20
STDERR_TAIL_LINES = 40


class PersistentCaptureRecorder(BaseRecorder):
    """Gapless recorder: long-lived ffmpeg → PCM pipe → Python segmentation.

    Reuses BaseRecorder's thread management, health tracking, and publish
    contract; a capture session failure increments consecutive_failures and
    the session is respawned after the usual retry delay, while the
    recording thread (and therefore is_healthy()) stays up.
    """

    def __init__(self, input_args: list, chunk_duration: float,
                 output_dir: str, target_sample_rate: int, label: str = ''):
        super().__init__(chunk_duration, output_dir, target_sample_rate)
        self.input_args = input_args
        self.label = label
        # Observability/test hooks; not read by production code.
        self.segments_published = 0
        self.segments_discarded = 0
        self._segment_bytes = int(target_sample_rate * 2 * chunk_duration)
        self._process = None
        # native_lock: recorder threads are real OS threads; also keeps the
        # gevent tripwire (test_native_locks) happy should the API process
        # ever import this module.
        self._process_lock = native_lock()
        self._stderr_tail = collections.deque(maxlen=STDERR_TAIL_LINES)
        self._last_discard_logged = 0.0

    def _get_thread_name(self) -> str:
        return "PersistentCaptureThread"

    def _get_retry_delay(self) -> float:
        return 2.0

    # -- process management ------------------------------------------------

    def _build_command(self) -> list:
        return ['ffmpeg', '-nostdin', '-loglevel', 'error'] + self.input_args + [
            '-ac', '1',
            '-ar', str(self.target_sample_rate),
            '-f', 's16le',
            '-acodec', 'pcm_s16le',
            'pipe:1',
        ]

    def _popen(self) -> subprocess.Popen:
        """Launch ffmpeg. Split from _spawn so tests can stub just this."""
        proc = subprocess.Popen(
            self._build_command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            fcntl.fcntl(proc.stdout.fileno(),
                        getattr(fcntl, 'F_SETPIPE_SZ', 1031),
                        PIPE_BUFFER_BYTES)
        except OSError:
            pass  # default pipe size still works, just less slack
        return proc

    def _spawn(self) -> subprocess.Popen:
        proc = self._popen()
        self._stderr_tail.clear()
        threading.Thread(
            target=self._drain_stderr, args=(proc,),
            name=f"{self._get_thread_name()}-stderr", daemon=True,
        ).start()
        with self._process_lock:
            self._process = proc
        return proc

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        # The raw-PCM muxer logs a warning per camera timestamp jitter
        # ("non monotonically increasing dts"); the audio bytes are
        # unaffected, and the spam would push real errors out of the tail.
        try:
            for raw in iter(proc.stderr.readline, b''):
                line = raw.decode('utf-8', errors='replace').rstrip()
                if line and 'non monotonically increasing dts' not in line:
                    self._stderr_tail.append(line)
        except (OSError, ValueError):
            pass  # pipe closed during shutdown

    def _shutdown_process(self, proc: subprocess.Popen) -> None:
        with self._process_lock:
            if self._process is proc:
                self._process = None
        try:
            # SIGKILL, not SIGTERM: ffmpeg's graceful RTSP teardown can take
            # seconds, and a pipe-output capture process has nothing to
            # finalize — waiting would just add dead air before the respawn.
            proc.kill()
            proc.wait()
        except OSError:
            pass
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except OSError:
                pass

    def _stderr_summary(self) -> str:
        return _parse_ffmpeg_error('\n'.join(self._stderr_tail))

    # -- capture loop ------------------------------------------------------

    def _recording_loop(self):
        while self.is_running:
            try:
                self._run_capture_session()
            except Exception as e:
                log_fd_exhaustion_if_needed(e, logger, 'capture-session', extra={
                    'recorder': self.__class__.__name__,
                })
                self._log_recording_error(f"Capture session error: {e}")
            if self.is_running:
                self._note_failure()
                time.sleep(self._get_retry_delay())

    def _run_capture_session(self) -> None:
        """One ffmpeg lifetime: stream PCM, cut segments, until EOF/stall."""
        proc = self._spawn()
        fd = proc.stdout.fileno()
        buf = bytearray()
        segment_start = None
        divergence_strikes = 0
        try:
            while self.is_running:
                timeout = (STARTUP_TIMEOUT_SECONDS if segment_start is None
                           else STALL_TIMEOUT_SECONDS)
                readable, _, _ = select.select([fd], [], [], timeout)
                if not readable:
                    if self.is_running:
                        self._log_recording_error(
                            f"Capture stalled ({self.label}): no audio for "
                            f"{timeout:.0f}s, restarting ffmpeg")
                    return
                data = os.read(fd, READ_BLOCK_BYTES)
                if not data:
                    # EOF is expected during stop() (the process is killed);
                    # only a mid-run EOF is a failure worth logging.
                    if self.is_running:
                        self._log_recording_error(
                            f"Capture ended ({self.label}): "
                            f"{self._stderr_summary()}")
                    return
                if segment_start is None:
                    segment_start = local_now()
                buf += data
                while len(buf) >= self._segment_bytes:
                    boundary = segment_start + timedelta(
                        seconds=self.chunk_duration)
                    # Divergence is measured before publish I/O; transient
                    # excursions (catch-up bursts, publish backpressure)
                    # recover on their own, so only a persistent divergence
                    # re-anchors — and it only renames, never restarts.
                    divergence = (local_now() - boundary).total_seconds()
                    divergence_strikes = (
                        divergence_strikes + 1
                        if abs(divergence) > WALL_REANCHOR_SECONDS
                        else 0)
                    queued = self._queue_wav_names()
                    if len(queued) >= MAX_QUEUE_DEPTH:
                        # Shed without materializing the segment bytes: on
                        # the overloaded devices this path exists for, the
                        # copy would be pure waste.
                        del buf[:self._segment_bytes]
                        self._record_discard()
                    else:
                        segment = bytes(
                            memoryview(buf)[:self._segment_bytes])
                        del buf[:self._segment_bytes]
                        self._publish_segment(segment, segment_start, queued)
                    if divergence_strikes >= WALL_REANCHOR_BOUNDARIES:
                        divergence_strikes = 0
                        boundary = local_now()
                        logger.info(
                            "Capture timeline re-anchored to wall clock",
                            extra={'drift_seconds': round(divergence, 1)})
                    segment_start = boundary
        finally:
            self._shutdown_process(proc)

    # -- publishing --------------------------------------------------------

    def _queue_wav_names(self) -> set:
        """Names of completed segments currently queued for analysis."""
        try:
            return {
                name for name in os.listdir(self.output_dir)
                if name.endswith('.wav') and not name.startswith('.')
            }
        except OSError:
            return set()

    def _collision_free(self, candidate, queued_names: set):
        """Bump candidate forward whole seconds until its filename is unused.

        Applied to every published name: after a backward re-anchor (DST
        fall-back, NTP step) the timeline can run through names of segments
        still sitting in the analysis queue, and os.rename() would silently
        replace them. Terminates because the queue holds at most a few
        files, and this recorder is the directory's only writer.
        """
        bumped = 0
        while candidate.strftime("%Y%m%d_%H%M%S") + '.wav' in queued_names:
            candidate += timedelta(seconds=1)
            bumped += 1
        if bumped:
            logger.info("Segment name bumped past a queued name", extra={
                'bumped_seconds': bumped,
            })
        return candidate

    def _record_discard(self) -> None:
        # Deliberate shedding: capture is healthy, the backlog is an
        # analysis-side problem, so a discard is not a failure.
        self._note_success()
        self.segments_discarded += 1
        now = time.time()
        if now - self._last_discard_logged > self._ERROR_LOG_INTERVAL:
            self._last_discard_logged = now
            logger.warning("Analysis backlog full, discarding segment", extra={
                'discarded_total': self.segments_discarded,
            })

    def _publish_segment(self, pcm: bytes, started_at,
                         queued_names: set) -> None:
        named_at = self._collision_free(started_at, queued_names)
        temp_path, final_path = self._segment_paths(named_at)
        try:
            with wave.open(temp_path, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self.target_sample_rate)
                wav.writeframes(pcm)
            os.rename(temp_path, final_path)
        except OSError as e:
            # A failed write/rename (disk full, permissions) must surface as
            # recorder degradation, not silence — count it like any failure.
            self._note_failure()
            log_fd_exhaustion_if_needed(e, logger, 'recording', extra={
                'temp_path': temp_path,
                'recorder': self.__class__.__name__,
            })
            self._log_recording_error(f"Failed to publish segment: {e}")
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass
            return

        self._note_success()
        self.segments_published += 1
        logger.info("🔴 Audio recorded", extra={
            'file': os.path.basename(final_path),
            'duration': self.chunk_duration,
            'capture': 'persistent',
        })

    # -- lifecycle ---------------------------------------------------------

    def _interrupt(self) -> None:
        """Kill ffmpeg during stop() so the blocked reader unblocks quickly.

        BaseRecorder.stop() clears is_running before calling this, so the
        session loop cannot respawn during shutdown. SIGKILL, not SIGTERM:
        ffmpeg's graceful RTSP teardown can take longer than the join, and
        a pipe-output capture process has nothing to finalize.
        """
        with self._process_lock:
            proc = self._process
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
