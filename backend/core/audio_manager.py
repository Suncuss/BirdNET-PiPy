"""
Audio Recording Modules

Provides two recording methods:
1. RtspRecorder - Records from RTSP streams (IP cameras, etc)
2. PulseAudioRecorder - Records from PulseAudio server via socket

All output mono WAV files at target sample rate (48kHz).
"""

import logging
import os
import re
import subprocess
import threading
import time
from abc import ABC, abstractmethod

from config.constants import VALID_RECORDING_MODES, RecordingMode
from core.timezone_service import local_now
from core.utils import sanitize_url

logger = logging.getLogger(__name__)

# ffmpeg stderr prefixes to skip (boilerplate + redundant wrappers)
_FFMPEG_SKIP_PREFIXES = (
    # Build/version boilerplate
    'ffmpeg version', 'built with', 'configuration:', 'lib',
    'Copyright', 'the FFmpeg developers',
    # Redundant wrapper lines ffmpeg emits after the real error
    'Error opening input file',
    'Error opening input files',
)

# Regex to strip memory addresses from ffmpeg component tags, e.g.
# [rtsp @ 0x55564a562e00] → [rtsp]
_FFMPEG_ADDR_RE = re.compile(r'\[(\w+)#?\d*\s*@\s*0x[0-9a-f]+\]')


def _parse_ffmpeg_error(stderr: str) -> str:
    """Extract meaningful error lines from ffmpeg stderr.

    ffmpeg stderr starts with version/build/library info before the
    actual error.  Strip that boilerplate, memory addresses, and
    redundant wrapper lines, returning only the useful part capped
    at 500 characters.
    """
    if not stderr:
        return 'No error output'
    lines = []
    for line in stderr.strip().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(_FFMPEG_SKIP_PREFIXES):
            continue
        # Strip verbose memory addresses for readability
        stripped = _FFMPEG_ADDR_RE.sub(r'[\1]', stripped)
        lines.append(stripped)
    if not lines:
        return 'No meaningful error output'
    return '\n'.join(lines)[:500]


def _summarize_stream_error(stderr: str) -> str:
    """Extract a concise single-line error for stream test results.

    Builds on _parse_ffmpeg_error but returns only the first meaningful
    line, capped at 150 characters — suitable for inline UI display.
    """
    parsed = _parse_ffmpeg_error(stderr)
    if parsed in ('No error output', 'No meaningful error output'):
        return parsed
    first_line = parsed.split('\n')[0]
    if len(first_line) > 150:
        return first_line[:147] + '...'
    return first_line


def test_stream_url(url: str) -> tuple:
    """Probe an RTSP stream URL to check if it's accessible.

    Args:
        url: The RTSP stream URL to test

    Returns:
        (success: bool, message: str)
    """
    if not url.startswith(('rtsp://', 'rtsps://')):
        return (False, 'Invalid URL format: must start with rtsp:// or rtsps://')

    safe_url = sanitize_url(url)

    try:
        result = subprocess.run(
            [
                'ffmpeg',
                '-rtsp_transport', 'tcp',
                '-timeout', '5000000',
                '-allowed_media_types', 'audio',
                '-fflags', '+genpts+discardcorrupt',
                '-use_wallclock_as_timestamps', '1',
                '-i', url,
                '-t', '1',
                '-f', 'null', '-',
            ],
            timeout=10,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return (True, 'Stream is accessible')
        error_msg = _summarize_stream_error(result.stderr)
        return (False, f'Stream probe failed: {error_msg}')

    except subprocess.TimeoutExpired:
        return (False, 'Connection timed out')
    except Exception as e:
        logger.error('Stream test error', extra={'error': str(e), 'url': safe_url})
        return (False, f'Stream test error: {str(e)}')


class BaseRecorder(ABC):
    """
    Abstract base class for audio recorders.

    Provides common functionality for recording fixed-duration audio chunks
    with timestamp-based filenames and atomic file operations.
    """

    # Rate limit interval for error logging (seconds)
    _ERROR_LOG_INTERVAL = 30

    def __init__(self, chunk_duration: float, output_dir: str, target_sample_rate: int):
        """
        Initialize base recorder.

        Args:
            chunk_duration: Duration of each chunk in seconds
            output_dir: Directory to save recordings
            target_sample_rate: Sample rate for output in Hz
        """
        self.chunk_duration = chunk_duration
        self.output_dir = output_dir
        self.target_sample_rate = target_sample_rate
        self.is_running = False
        self.recording_thread = None
        self._last_error_logged = 0  # Timestamp for rate-limited logging

        # Health tracking
        self.consecutive_failures = 0
        self.last_error_message = ''
        self.last_error_time = 0.0
        self.last_success_time = 0.0

    @abstractmethod
    def _get_thread_name(self) -> str:
        """Return the name for the recording thread."""
        pass

    @abstractmethod
    def _execute_recording(self, temp_path: str) -> bool:
        """
        Execute the recording command.

        Args:
            temp_path: Path to write temporary recording file

        Returns:
            True if recording succeeded, False otherwise
        """
        pass

    def _get_ffmpeg_output_args(self, temp_path: str) -> list:
        """
        Get common ffmpeg output arguments for WAV recording.

        Args:
            temp_path: Path to write output file

        Returns:
            List of ffmpeg arguments for output format
        """
        return [
            '-t', str(self.chunk_duration),
            '-ar', str(self.target_sample_rate),
            '-ac', '1',
            '-acodec', 'pcm_s16le',
            '-y', temp_path
        ]

    def _log_recording_error(self, message: str) -> None:
        """
        Log a recording error with rate limiting to avoid log flooding.

        Only logs if at least _ERROR_LOG_INTERVAL seconds have passed
        since the last error was logged. Always captures message for health tracking.

        Args:
            message: Error message to log
        """
        self.last_error_message = message
        current_time = time.time()
        if current_time - self._last_error_logged > self._ERROR_LOG_INTERVAL:
            self._last_error_logged = current_time
            logger.error(message)

    def _record_chunk(self) -> str | None:
        """
        Record a single audio chunk with timestamp filename.
        Uses atomic rename to ensure file only appears when complete.

        Returns:
            Path to recorded file if successful, None otherwise
        """
        # Generate timestamp-based filenames
        timestamp = local_now().strftime("%Y%m%d_%H%M%S")
        temp_path = os.path.join(self.output_dir, f".{timestamp}.tmp.wav")
        final_path = os.path.join(self.output_dir, f"{timestamp}.wav")

        try:
            if self._execute_recording(temp_path):
                # Verify file was created and has content
                if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    # Atomic rename - file only appears when complete
                    os.rename(temp_path, final_path)
                    self.consecutive_failures = 0
                    self.last_success_time = time.time()
                    logger.info("🔴 Audio recorded", extra={
                        'file': os.path.basename(final_path),
                        'duration': self.chunk_duration,
                    })
                    return final_path
        except subprocess.TimeoutExpired:
            logger.warning("Recording timed out", extra={'temp_path': temp_path})
            self.last_error_message = "Recording timed out"
        except Exception as e:
            logger.warning(f"Recording failed: {e}", extra={'temp_path': temp_path})
            self.last_error_message = f"Recording failed: {e}"
        finally:
            # Clean up temp file if it still exists (wasn't renamed)
            # Use try-except to handle race conditions where file may have been removed
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass  # File already removed or inaccessible

        self.consecutive_failures += 1
        self.last_error_time = time.time()
        return None

    def _get_retry_delay(self) -> float:
        """Return delay in seconds before retrying after failure."""
        return 1.0

    def _recording_loop(self):
        """Main recording loop - runs in separate thread"""
        while self.is_running:
            try:
                chunk_path = self._record_chunk()

                if not chunk_path:
                    # Recording failed, brief pause before retry
                    time.sleep(self._get_retry_delay())

            except Exception as e:
                logger.error(f"Recording error: {e}")
                time.sleep(self._get_retry_delay() * 2)

    def start(self):
        """Start recording in background thread"""
        if self.is_running:
            return

        self.is_running = True
        self.recording_thread = threading.Thread(
            target=self._recording_loop,
            name=self._get_thread_name(),
            daemon=True
        )
        self.recording_thread.start()

    def stop(self):
        """Stop recording and wait for thread to finish"""
        if not self.is_running:
            return

        self.is_running = False
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=5)

    def is_healthy(self) -> bool:
        """Check if recording thread is still running"""
        if not self.is_running:
            return False
        return self.recording_thread and self.recording_thread.is_alive()

    @staticmethod
    def default_health_status() -> dict:
        """Return default/empty health status (used when no recorder exists)."""
        return {
            'is_healthy': False,
            'consecutive_failures': 0,
            'last_error_message': '',
            'last_error_time': 0.0,
            'last_success_time': 0.0,
        }

    def get_health_status(self, healthy: bool | None = None) -> dict:
        """Get recorder health metrics for monitoring.

        Args:
            healthy: Override for is_healthy() to avoid redundant calls
                     when the caller already has the result.
        """
        return {
            'is_healthy': self.is_healthy() if healthy is None else healthy,
            'consecutive_failures': self.consecutive_failures,
            'last_error_message': self.last_error_message,
            'last_error_time': self.last_error_time,
            'last_success_time': self.last_success_time,
        }

    def restart(self):
        """Restart the recording process"""
        self.stop()
        self.consecutive_failures = 0
        time.sleep(1)
        self.start()


class RtspRecorder(BaseRecorder):
    """
    RTSP audio stream recorder.
    Records fixed-duration chunks from RTSP streams (IP cameras, etc).
    """

    def __init__(self, rtsp_url: str, chunk_duration: float,
                 output_dir: str, target_sample_rate: int):
        """
        Initialize RTSP stream recorder.

        Args:
            rtsp_url: RTSP URL (rtsp:// or rtsps://)
            chunk_duration: Duration of each chunk in seconds
            output_dir: Directory to save recordings
            target_sample_rate: Sample rate for output in Hz
        """
        super().__init__(chunk_duration, output_dir, target_sample_rate)
        self.rtsp_url = rtsp_url

    def _get_thread_name(self) -> str:
        return "RTSPRecordingThread"

    def _get_retry_delay(self) -> float:
        """RTSP needs longer delay for reconnection."""
        return 2.0

    def _get_ffmpeg_rtsp_args(self) -> list:
        """
        Build RTSP ffmpeg arguments for unstable camera streams.

        Restricting the demuxer to audio avoids unnecessary video parsing
        errors, while regenerating/smoothing timestamps prevents broken
        output when cameras emit non-monotonic RTP timing.
        """
        return [
            '-rtsp_transport', 'tcp',
            '-timeout', '10000000',  # 10 second connection timeout (microseconds)
            '-allowed_media_types', 'audio',
            '-fflags', '+genpts+discardcorrupt',
            '-use_wallclock_as_timestamps', '1',
            '-i', self.rtsp_url,
            '-map', '0:a:0',
            '-af', 'aresample=async=1:first_pts=0',
        ]

    def _execute_recording(self, temp_path: str) -> bool:
        """
        Execute ffmpeg command for RTSP stream recording.
        Uses argument list to prevent shell injection.
        """
        cmd = ['ffmpeg'] + self._get_ffmpeg_rtsp_args() + self._get_ffmpeg_output_args(temp_path)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.chunk_duration + 15  # Extra time for RTSP connection
        )

        if result.returncode != 0:
            safe_url = sanitize_url(self.rtsp_url)
            self._log_recording_error(
                f"RTSP recording failed (url={safe_url}): {_parse_ffmpeg_error(result.stderr)}"
            )

        return result.returncode == 0


class PulseAudioRecorder(BaseRecorder):
    """
    PulseAudio audio recorder.
    Records fixed-duration chunks from PulseAudio server via socket.
    Enables multiple applications to share the same audio source.
    """

    def __init__(self, source_name: str, chunk_duration: float,
                 output_dir: str, target_sample_rate: int):
        """
        Initialize PulseAudio recorder.

        Args:
            source_name: PulseAudio source name (e.g., "default" or specific source)
            chunk_duration: Duration of each chunk in seconds
            output_dir: Directory to save recordings
            target_sample_rate: Sample rate for output in Hz
        """
        super().__init__(chunk_duration, output_dir, target_sample_rate)
        self.source_name = source_name if source_name else "default"

    def _get_thread_name(self) -> str:
        return "PulseAudioRecordingThread"

    def _execute_recording(self, temp_path: str) -> bool:
        """
        Execute ffmpeg command for PulseAudio recording.
        Uses argument list to prevent shell injection.
        """
        cmd = [
            'ffmpeg',
            '-f', 'pulse',
            '-i', self.source_name,
        ] + self._get_ffmpeg_output_args(temp_path)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.chunk_duration + 10
        )

        if result.returncode != 0:
            self._log_recording_error(
                f"PulseAudio recording failed: {_parse_ffmpeg_error(result.stderr)}"
            )

        return result.returncode == 0


def create_recorder(
    recording_mode: str,
    chunk_duration: float,
    output_dir: str,
    target_sample_rate: int,
    source_name: str = None,
    rtsp_url: str = None
) -> BaseRecorder:
    """
    Factory function to create the appropriate recorder based on recording mode.

    Args:
        recording_mode: 'pulseaudio' or 'rtsp'
        chunk_duration: Duration of each chunk in seconds
        output_dir: Directory to save recordings
        target_sample_rate: Sample rate for output in Hz
        source_name: PulseAudio source name (required for pulseaudio mode)
        rtsp_url: RTSP URL (required for rtsp mode)

    Returns:
        Configured BaseRecorder instance

    Raises:
        ValueError: If recording_mode is invalid or required URL/source is missing
    """
    if recording_mode == RecordingMode.PULSEAUDIO:
        return PulseAudioRecorder(
            source_name=source_name or 'default',
            chunk_duration=chunk_duration,
            output_dir=output_dir,
            target_sample_rate=target_sample_rate
        )
    elif recording_mode == RecordingMode.RTSP:
        if not rtsp_url:
            raise ValueError("rtsp_url required for rtsp recording mode")
        if not rtsp_url.startswith(('rtsp://', 'rtsps://')):
            raise ValueError("rtsp_url must start with rtsp:// or rtsps://")
        return RtspRecorder(
            rtsp_url=rtsp_url,
            chunk_duration=chunk_duration,
            output_dir=output_dir,
            target_sample_rate=target_sample_rate
        )
    else:
        raise ValueError(
            f"Unknown recording mode: {recording_mode}. "
            f"Valid modes: {', '.join(VALID_RECORDING_MODES)}"
        )
