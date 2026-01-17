"""
Audio Recording Modules

Provides three recording methods:
1. HttpStreamRecorder - Records from HTTP audio streams
2. RtspRecorder - Records from RTSP streams (IP cameras, etc)
3. PulseAudioRecorder - Records from PulseAudio server via socket

All output mono WAV files at target sample rate (48kHz).
"""

import subprocess
import os
import time
import threading
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
import logging

from core.utils import sanitize_url

logger = logging.getLogger(__name__)


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
        since the last error was logged.

        Args:
            message: Error message to log
        """
        current_time = time.time()
        if current_time - self._last_error_logged > self._ERROR_LOG_INTERVAL:
            self._last_error_logged = current_time
            logger.error(message)

    def _record_chunk(self) -> Optional[str]:
        """
        Record a single audio chunk with timestamp filename.
        Uses atomic rename to ensure file only appears when complete.

        Returns:
            Path to recorded file if successful, None otherwise
        """
        # Generate timestamp-based filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_path = os.path.join(self.output_dir, f".{timestamp}.tmp.wav")
        final_path = os.path.join(self.output_dir, f"{timestamp}.wav")

        try:
            if self._execute_recording(temp_path):
                # Verify file was created and has content
                if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                    # Atomic rename - file only appears when complete
                    os.rename(temp_path, final_path)
                    return final_path
        except subprocess.TimeoutExpired:
            logger.warning("Recording timed out", extra={'temp_path': temp_path})
        except Exception as e:
            logger.warning(f"Recording failed: {e}", extra={'temp_path': temp_path})
        finally:
            # Clean up temp file if it still exists (wasn't renamed)
            # Use try-except to handle race conditions where file may have been removed
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except OSError:
                pass  # File already removed or inaccessible

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

    def restart(self):
        """Restart the recording process"""
        self.stop()
        time.sleep(1)
        self.start()


class HttpStreamRecorder(BaseRecorder):
    """
    Simple HTTP audio stream recorder.
    Records fixed-duration chunks with timestamp-based filenames.
    Uses curl piped to ffmpeg for stream capture.
    """

    def __init__(self, stream_url: str, chunk_duration: float,
                 output_dir: str, target_sample_rate: int):
        """
        Initialize HTTP stream recorder.

        Args:
            stream_url: HTTP URL of audio stream
            chunk_duration: Duration of each chunk in seconds
            output_dir: Directory to save recordings
            target_sample_rate: Sample rate for output in Hz
        """
        super().__init__(chunk_duration, output_dir, target_sample_rate)
        self.stream_url = stream_url

    def _get_thread_name(self) -> str:
        return "HTTPRecordingThread"

    def _execute_recording(self, temp_path: str) -> bool:
        """
        Execute curl | ffmpeg pipeline for HTTP stream recording.
        Uses subprocess.Popen to safely pipe without shell injection.
        """
        # Start curl process to fetch stream
        curl_cmd = ['curl', '-s', self.stream_url]
        curl_proc = subprocess.Popen(
            curl_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Start ffmpeg process to convert and save
        ffmpeg_cmd = ['ffmpeg', '-i', 'pipe:0'] + self._get_ffmpeg_output_args(temp_path)

        try:
            ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=curl_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE
            )

            # Allow curl to receive SIGPIPE if ffmpeg exits
            curl_proc.stdout.close()

            # Wait for ffmpeg with timeout
            ffmpeg_proc.wait(timeout=self.chunk_duration + 10)

            # Clean up curl process
            curl_proc.terminate()
            curl_proc.wait(timeout=2)

            if ffmpeg_proc.returncode != 0:
                ffmpeg_stderr = ffmpeg_proc.stderr.read().decode('utf-8', errors='replace')[:500] if ffmpeg_proc.stderr else ""
                curl_stderr = curl_proc.stderr.read().decode('utf-8', errors='replace')[:200] if curl_proc.stderr else ""
                self._log_recording_error(
                    f"HTTP stream recording failed (returncode={ffmpeg_proc.returncode}, "
                    f"url={self.stream_url}): ffmpeg: {ffmpeg_stderr}, curl: {curl_stderr}"
                )

            return ffmpeg_proc.returncode == 0

        except subprocess.TimeoutExpired:
            # Kill both processes on timeout
            ffmpeg_proc.kill()
            curl_proc.kill()
            raise


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

    def _execute_recording(self, temp_path: str) -> bool:
        """
        Execute ffmpeg command for RTSP stream recording.
        Uses argument list to prevent shell injection.
        """
        cmd = [
            'ffmpeg',
            '-rtsp_transport', 'tcp',
            '-timeout', '10000000',  # 10 second connection timeout (microseconds)
            '-i', self.rtsp_url,
        ] + self._get_ffmpeg_output_args(temp_path)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.chunk_duration + 15  # Extra time for RTSP connection
        )

        if result.returncode != 0:
            stderr_snippet = result.stderr[:500] if result.stderr else "No error output"
            safe_url = sanitize_url(self.rtsp_url)
            self._log_recording_error(
                f"RTSP recording failed (returncode={result.returncode}, url={safe_url}): {stderr_snippet}"
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
            stderr_snippet = result.stderr[:500] if result.stderr else "No error output"
            self._log_recording_error(
                f"PulseAudio recording failed (returncode={result.returncode}): {stderr_snippet}"
            )

        return result.returncode == 0


def create_recorder(
    recording_mode: str,
    chunk_duration: float,
    output_dir: str,
    target_sample_rate: int,
    source_name: str = None,
    stream_url: str = None,
    rtsp_url: str = None
) -> BaseRecorder:
    """
    Factory function to create the appropriate recorder based on recording mode.

    Args:
        recording_mode: 'pulseaudio', 'http_stream', or 'rtsp'
        chunk_duration: Duration of each chunk in seconds
        output_dir: Directory to save recordings
        target_sample_rate: Sample rate for output in Hz
        source_name: PulseAudio source name (required for pulseaudio mode)
        stream_url: HTTP stream URL (required for http_stream mode)
        rtsp_url: RTSP URL (required for rtsp mode)

    Returns:
        Configured BaseRecorder instance

    Raises:
        ValueError: If recording_mode is invalid or required URL/source is missing
    """
    if recording_mode == 'pulseaudio':
        return PulseAudioRecorder(
            source_name=source_name or 'default',
            chunk_duration=chunk_duration,
            output_dir=output_dir,
            target_sample_rate=target_sample_rate
        )
    elif recording_mode == 'rtsp':
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
    elif recording_mode == 'http_stream':
        if not stream_url:
            raise ValueError("stream_url required for http_stream recording mode")
        return HttpStreamRecorder(
            stream_url=stream_url,
            chunk_duration=chunk_duration,
            output_dir=output_dir,
            target_sample_rate=target_sample_rate
        )
    else:
        raise ValueError(f"Unknown recording mode: {recording_mode}")
