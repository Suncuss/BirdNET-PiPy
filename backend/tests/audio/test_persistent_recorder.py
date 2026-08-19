"""
Tests for the persistent-capture recorder.

Covers PCM segmentation into WAV files, the tmp+rename publish contract,
backlog discard, stall/EOF session recovery, timeline drift re-anchoring,
shutdown behavior, and factory selection. The capture session is exercised
with real bytes through a real pipe via a fake ffmpeg process — no
subprocess execution needed.

NOTE: conftest's reset_imports pops core.* between tests, so core modules
are resolved per-test via the `pr` fixture (never at module level) and
patched through that same module object — otherwise class identity and
patch targets split between module generations.
"""
import os
import threading
import time
import wave
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

# Small segments so tests can feed a whole segment without filling the pipe.
RATE = 8000
CHUNK_SECONDS = 1.0
SEGMENT_BYTES = int(RATE * 2 * CHUNK_SECONDS)
FIXED_TIME = datetime(2026, 8, 18, 10, 30, 0)


@pytest.fixture
def pr():
    """The persistent_recorder module, freshly resolved for this test."""
    import core.persistent_recorder as module
    return module


class FakeFfmpeg:
    """Stands in for the ffmpeg Popen: real pipes plus call recording."""

    def __init__(self):
        read_fd, self._write_fd = os.pipe()
        self.stdout = os.fdopen(read_fd, 'rb', 0)
        err_read_fd, self._err_write_fd = os.pipe()
        self.stderr = os.fdopen(err_read_fd, 'rb', 0)
        self._open_write_fds = [self._write_fd, self._err_write_fd]
        self.terminated = False
        self.killed = False

    def feed(self, data: bytes):
        os.write(self._write_fd, data)

    def feed_stderr(self, data: bytes):
        os.write(self._err_write_fd, data)

    def end_stream(self):
        """Close the write ends: the reader sees EOF."""
        for fd in self._open_write_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._open_write_fds.clear()

    def terminate(self):
        self.terminated = True
        self.end_stream()

    def kill(self):
        self.killed = True
        self.end_stream()

    def wait(self, timeout=None):
        return 0


def make_recorder(pr, output_dir):
    return pr.PersistentCaptureRecorder(
        input_args=['-f', 'pulse', '-i', 'default'],
        chunk_duration=CHUNK_SECONDS,
        output_dir=output_dir,
        target_sample_rate=RATE,
        label='test',
    )


def attach_fake_ffmpeg(recorder) -> FakeFfmpeg:
    """Stub only the process launch; the real _spawn still registers the
    process and drains stderr, so that bookkeeping stays under test."""
    fake = FakeFfmpeg()
    recorder._popen = lambda: fake
    return fake


def run_session(recorder):
    """Run one capture session in a thread (returns the thread)."""
    recorder.is_running = True
    thread = threading.Thread(target=recorder._run_capture_session, daemon=True)
    thread.start()
    return thread


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        time.sleep(0.01)
    return predicate()


class TestSegmentation:
    """PCM stream is cut into exact-size, valid, atomically published WAVs."""

    def test_publishes_exact_segments_and_holds_partial(self, pr, temp_output_dir):
        recorder = make_recorder(pr, temp_output_dir)
        fake = attach_fake_ffmpeg(recorder)

        with patch.object(pr, 'local_now', return_value=FIXED_TIME):
            thread = run_session(recorder)
            fake.feed(b'\x01\x02' * (SEGMENT_BYTES // 2))       # segment 1
            fake.feed(b'\x03\x04' * (SEGMENT_BYTES // 2))       # segment 2
            fake.feed(b'\x05\x06' * (SEGMENT_BYTES // 4))       # half a segment
            assert wait_for(lambda: recorder.segments_published == 2)
            fake.end_stream()
            thread.join(timeout=5)

        wavs = sorted(f for f in os.listdir(temp_output_dir) if f.endswith('.wav'))
        assert wavs == ['20260818_103000.wav', '20260818_103001.wav']
        assert not any(f.startswith('.') for f in os.listdir(temp_output_dir))
        for name in wavs:
            with wave.open(os.path.join(temp_output_dir, name)) as w:
                assert w.getnframes() == RATE
                assert w.getframerate() == RATE
                assert w.getnchannels() == 1
                assert w.getsampwidth() == 2

    def test_publish_resets_failure_counters(self, pr, temp_output_dir):
        recorder = make_recorder(pr, temp_output_dir)
        fake = attach_fake_ffmpeg(recorder)
        recorder.consecutive_failures = 3

        with patch.object(pr, 'local_now', return_value=FIXED_TIME):
            thread = run_session(recorder)
            fake.feed(b'\x00' * SEGMENT_BYTES)
            assert wait_for(lambda: recorder.segments_published == 1)
            fake.end_stream()
            thread.join(timeout=5)

        assert recorder.consecutive_failures == 0
        assert recorder.last_success_time > 0


class TestBacklogDiscard:
    """Segments are discarded, not published, while the queue is deep."""

    def test_discards_when_queue_full(self, pr, temp_output_dir):
        for i in range(pr.MAX_QUEUE_DEPTH):
            with open(os.path.join(temp_output_dir, f'2026081{i}_000000.wav'), 'wb') as f:
                f.write(b'RIFF')

        recorder = make_recorder(pr, temp_output_dir)
        fake = attach_fake_ffmpeg(recorder)

        with patch.object(pr, 'local_now', return_value=FIXED_TIME):
            thread = run_session(recorder)
            fake.feed(b'\x00' * SEGMENT_BYTES)
            assert wait_for(lambda: recorder.segments_discarded == 1)
            fake.end_stream()
            thread.join(timeout=5)

        assert recorder.segments_published == 0
        assert '20260818_103000.wav' not in os.listdir(temp_output_dir)
        # Capture itself succeeded: discard must not mark the recorder failing.
        assert recorder.consecutive_failures == 0

    def test_publish_failure_marks_recorder_failing(self, pr, temp_output_dir):
        """A failed WAV write (e.g. disk full) must surface as degradation,
        not silent success — regression test for success bookkeeping that
        ran before the write."""
        recorder = make_recorder(pr, temp_output_dir)
        fake = attach_fake_ffmpeg(recorder)

        with patch.object(pr, 'local_now', return_value=FIXED_TIME), \
             patch.object(pr.wave, 'open',
                          side_effect=OSError(28, 'No space left on device')):
            thread = run_session(recorder)
            fake.feed(b'\x00' * SEGMENT_BYTES)
            assert wait_for(lambda: recorder.consecutive_failures >= 1)
            # Read before end_stream(): the mid-run EOF logs its own error.
            publish_error = recorder.last_error_message
            fake.end_stream()
            thread.join(timeout=5)

        assert recorder.segments_published == 0
        assert recorder.last_error_time > 0
        assert 'Failed to publish segment' in publish_error
        assert not any(f.endswith('.wav') for f in os.listdir(temp_output_dir))

    def test_hidden_and_tmp_files_do_not_count_as_backlog(self, pr, temp_output_dir):
        for name in ('.20260817_000000.tmp.wav', '.hidden.wav', 'notes.txt'):
            with open(os.path.join(temp_output_dir, name), 'w') as f:
                f.write('x')
        recorder = make_recorder(pr, temp_output_dir)
        assert recorder._queue_wav_names() == set()


class TestSessionRecovery:
    """Stall and EOF end the session so the loop can respawn ffmpeg."""

    def test_stall_ends_session(self, pr, temp_output_dir, monkeypatch):
        monkeypatch.setattr(pr, 'STARTUP_TIMEOUT_SECONDS', 0.05)
        recorder = make_recorder(pr, temp_output_dir)
        attach_fake_ffmpeg(recorder)

        thread = run_session(recorder)
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert 'stalled' in recorder.last_error_message

    def test_eof_ends_session_with_stderr_summary(self, pr, temp_output_dir):
        recorder = make_recorder(pr, temp_output_dir)
        fake = attach_fake_ffmpeg(recorder)

        thread = run_session(recorder)
        fake.feed(b'\x00' * 100)
        fake.feed_stderr(b'Connection refused\n')
        time.sleep(0.05)  # let the drain thread read stderr
        fake.end_stream()
        thread.join(timeout=5)

        assert not thread.is_alive()
        assert 'Capture ended' in recorder.last_error_message
        assert 'Connection refused' in recorder.last_error_message

    def test_dts_warnings_filtered_at_drain(self, pr, temp_output_dir):
        """Camera timestamp jitter spam is dropped as it arrives, so the
        bounded tail keeps room for real errors."""
        recorder = make_recorder(pr, temp_output_dir)
        fake = FakeFfmpeg()
        fake.feed_stderr(
            b'[s16le] Application provided invalid, '
            b'non monotonically increasing dts to muxer in stream 0: 1 >= 1\n')
        fake.feed_stderr(b'Connection timed out\n')
        fake.end_stream()
        recorder._drain_stderr(fake)  # runs to EOF synchronously

        assert list(recorder._stderr_tail) == ['Connection timed out']
        assert 'Connection timed out' in recorder._stderr_summary()

    def test_loop_counts_failures_and_respawns(self, pr, temp_output_dir, monkeypatch):
        monkeypatch.setattr(pr, 'STARTUP_TIMEOUT_SECONDS', 0.05)
        recorder = make_recorder(pr, temp_output_dir)
        recorder._get_retry_delay = lambda: 0.01
        sessions = []

        def fake_popen():
            fake = FakeFfmpeg()
            sessions.append(fake)
            return fake

        recorder._popen = fake_popen
        recorder.start()
        try:
            assert wait_for(lambda: recorder.consecutive_failures >= 2)
            assert len(sessions) >= 2
        finally:
            recorder.stop()


class TestTimelineContiguity:
    """Within a session, names are sample-count contiguous: delivery jitter,
    bursts, and publish backpressure never bend the timeline."""

    @pytest.mark.parametrize('publish_delay', [0, 12],
                             ids=['burst-delivery', 'slow-publish'])
    def test_jitter_keeps_names_contiguous(self, pr, temp_output_dir,
                                           publish_delay):
        """Contiguous PCM keeps contiguous names whether segments arrive in
        one catch-up burst (delay 0: frozen clock) or every publish stalls
        (the reviewer's repro — including the boundary AFTER the one each
        stall lands on)."""
        recorder = make_recorder(pr, temp_output_dir)
        fake = attach_fake_ffmpeg(recorder)
        clock = {'now': FIXED_TIME}

        original_publish = recorder._publish_segment

        def delayed_publish(pcm, started_at, queued_names):
            clock['now'] += timedelta(seconds=publish_delay)
            original_publish(pcm, started_at, queued_names)

        recorder._publish_segment = delayed_publish

        with patch.object(pr, 'local_now', side_effect=lambda: clock['now']):
            thread = run_session(recorder)
            for _ in range(3):
                fake.feed(b'\x00' * SEGMENT_BYTES)
            assert wait_for(lambda: recorder.segments_published == 3)
            fake.end_stream()
            thread.join(timeout=5)

        wavs = sorted(f for f in os.listdir(temp_output_dir) if f.endswith('.wav'))
        assert wavs == ['20260818_103000.wav', '20260818_103001.wav',
                        '20260818_103002.wav']

    def _run_clock_step_scenario(self, pr, temp_output_dir, monkeypatch,
                                 step_seconds):
        """Feed 2 segments in 'real time', step the clock, feed 3 more.

        The fake clock advances by chunk_duration per publish (simulating
        real-time delivery); the step is applied between segments 2 and 3.
        Asserts the session thread survives the re-anchor (in place, no
        restart) and returns the published WAV filenames, sorted.
        """
        monkeypatch.setattr(pr, 'WALL_REANCHOR_SECONDS', 2.5)
        monkeypatch.setattr(pr, 'WALL_REANCHOR_BOUNDARIES', 2)
        # This dir has no consumer; keep the backlog-discard policy out of
        # the way so all five segments publish.
        monkeypatch.setattr(pr, 'MAX_QUEUE_DEPTH', 10)
        recorder = make_recorder(pr, temp_output_dir)
        fake = attach_fake_ffmpeg(recorder)
        clock = {'now': FIXED_TIME}

        original_publish = recorder._publish_segment

        def realtime_publish(pcm, started_at, queued_names):
            clock['now'] += timedelta(seconds=CHUNK_SECONDS)
            original_publish(pcm, started_at, queued_names)

        recorder._publish_segment = realtime_publish

        with patch.object(pr, 'local_now', side_effect=lambda: clock['now']):
            thread = run_session(recorder)
            fake.feed(b'\x00' * (SEGMENT_BYTES * 2))
            assert wait_for(lambda: recorder.segments_published == 2)
            clock['now'] += timedelta(seconds=step_seconds)
            fake.feed(b'\x00' * (SEGMENT_BYTES * 3))
            assert wait_for(lambda: recorder.segments_published == 5)
            assert thread.is_alive()  # re-anchor never ends the session
            fake.end_stream()
            thread.join(timeout=5)
        return sorted(f for f in os.listdir(temp_output_dir)
                      if f.endswith('.wav'))

    def test_backward_clock_step_reanchors_in_place(self, pr, temp_output_dir,
                                                    monkeypatch):
        """DST fall-back / backward NTP step: after the persistence gate,
        naming re-anchors backward in place — one logged correction, no
        restart churn, no capture gap."""
        wavs = self._run_clock_step_scenario(pr, temp_output_dir, monkeypatch,
                                             step_seconds=-10)
        # Segments 1-4 stay contiguous; segment 5 re-anchors to the
        # stepped-back clock (10:29:54), which sorts before them.
        assert wavs == ['20260818_102954.wav', '20260818_103000.wav',
                        '20260818_103001.wav', '20260818_103002.wav',
                        '20260818_103003.wav']

    def test_forward_clock_step_reanchors_in_place(self, pr, temp_output_dir,
                                                   monkeypatch):
        """Forward step (spring-forward, or accumulated audio loss):
        naming jumps forward once, in place."""
        wavs = self._run_clock_step_scenario(pr, temp_output_dir, monkeypatch,
                                             step_seconds=10)
        assert wavs == ['20260818_103000.wav', '20260818_103001.wav',
                        '20260818_103002.wav', '20260818_103003.wav',
                        '20260818_103014.wav']

    def test_later_boundary_never_overwrites_queued_file(self, pr, temp_output_dir):
        """Reviewer repro: after a (re-)anchor, a LATER boundary can land on
        a name still sitting in the queue — publication must bump past it,
        never rename over it."""
        queued = os.path.join(temp_output_dir, '20260818_103001.wav')
        with open(queued, 'wb') as f:
            f.write(b'MARKER')

        recorder = make_recorder(pr, temp_output_dir)
        fake = attach_fake_ffmpeg(recorder)

        with patch.object(pr, 'local_now', return_value=FIXED_TIME):
            thread = run_session(recorder)
            fake.feed(b'\x00' * (SEGMENT_BYTES * 2))
            assert wait_for(lambda: recorder.segments_published == 2)
            fake.end_stream()
            thread.join(timeout=5)

        with open(queued, 'rb') as f:
            assert f.read() == b'MARKER'   # queued audio survived
        wavs = sorted(f for f in os.listdir(temp_output_dir) if f.endswith('.wav'))
        assert wavs == ['20260818_103000.wav', '20260818_103001.wav',
                        '20260818_103002.wav']

    def test_collision_free_bumps_past_queued_names(self, pr, temp_output_dir):
        """A backward re-anchor landing on names still in the queue must
        bump forward to an unused second, never overwrite."""
        recorder = make_recorder(pr, temp_output_dir)
        queued = {'20260818_103000.wav', '20260818_103001.wav'}
        assert recorder._collision_free(FIXED_TIME, queued) == \
            FIXED_TIME + timedelta(seconds=2)
        clear = FIXED_TIME - timedelta(seconds=30)
        assert recorder._collision_free(clear, queued) == clear


class TestShutdown:
    """stop() kills ffmpeg and joins the thread promptly."""

    def test_stop_kills_process_and_joins(self, pr, temp_output_dir):
        recorder = make_recorder(pr, temp_output_dir)
        fake = attach_fake_ffmpeg(recorder)

        recorder.start()
        assert wait_for(lambda: recorder._process is fake)
        started = time.time()
        recorder.stop()
        elapsed = time.time() - started

        assert fake.killed
        assert elapsed < 3
        assert not recorder.recording_thread.is_alive()
        assert recorder.is_running is False

    def test_stop_is_idempotent(self, pr, temp_output_dir):
        recorder = make_recorder(pr, temp_output_dir)
        recorder.stop()  # never started: must not raise
        assert recorder.is_running is False


class TestCommandConstruction:
    """ffmpeg command construction. Input args come from audio_manager's
    shared builders (tested there), so only the PCM output side is ours."""

    def test_build_command_outputs_pcm_to_pipe(self, pr, temp_output_dir):
        recorder = make_recorder(pr, temp_output_dir)
        cmd = recorder._build_command()
        assert cmd[0] == 'ffmpeg'
        assert cmd[-1] == 'pipe:1'
        assert 's16le' in cmd
        assert '-ar' in cmd and str(RATE) in cmd
        assert '-ac' in cmd and '1' in cmd
        assert '-nostdin' in cmd
        # No per-segment duration: the stream runs until failure/stop.
        assert '-t' not in cmd


class TestFactorySelection:
    """create_recorder picks persistent capture by default."""

    def test_rtsp_defaults_to_persistent(self, pr, temp_output_dir):
        from core.audio_manager import create_recorder
        recorder = create_recorder(
            recording_mode='rtsp',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000,
            rtsp_url='rtsp://192.168.1.100/stream',
        )
        assert isinstance(recorder, pr.PersistentCaptureRecorder)
        assert 'rtsp://192.168.1.100/stream' in recorder.input_args

    def test_pulse_defaults_to_persistent(self, pr, temp_output_dir):
        from core.audio_manager import create_recorder
        recorder = create_recorder(
            recording_mode='pulseaudio',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000,
            source_name='mic',
        )
        assert isinstance(recorder, pr.PersistentCaptureRecorder)
        assert recorder.input_args == ['-f', 'pulse', '-i', 'mic']

    def test_segment_mode_env_reverts_to_per_segment(self, temp_output_dir,
                                                     monkeypatch):
        import core.audio_manager as am
        monkeypatch.setenv('BIRDNET_CAPTURE_MODE', 'segment')
        rtsp = am.create_recorder(
            recording_mode='rtsp',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000,
            rtsp_url='rtsp://192.168.1.100/stream',
        )
        pulse = am.create_recorder(
            recording_mode='pulseaudio',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000,
        )
        assert isinstance(rtsp, am.RtspRecorder)
        assert isinstance(pulse, am.PulseAudioRecorder)
