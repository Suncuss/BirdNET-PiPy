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
from datetime import datetime


class HttpStreamRecorder:
    """
    Simple HTTP audio stream recorder.
    Records fixed-duration chunks with timestamp-based filenames.
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
        self.stream_url = stream_url
        self.chunk_duration = chunk_duration
        self.output_dir = output_dir
        self.target_sample_rate = target_sample_rate
        self.is_running = False
        self.recording_thread = None

    def _record_chunk(self) -> str:
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

        # Build curl | ffmpeg pipeline
        # curl streams audio -> ffmpeg converts and saves to temp file
        cmd = (
            f'curl -s "{self.stream_url}" | '
            f'ffmpeg -i pipe:0 '
            f'-t {self.chunk_duration} '       # Exact duration
            f'-ar {self.target_sample_rate} '  # Sample rate (48kHz)
            f'-ac 1 '                           # Mono
            f'-acodec pcm_s16le '              # 16-bit PCM
            f'-y {temp_path}'                   # Write to temp file first
        )

        try:
            result = subprocess.run(
                ['bash', '-c', cmd],
                capture_output=True,
                text=True,
                timeout=self.chunk_duration + 10
            )

            # Verify file was created and has content
            if result.returncode == 0 and os.path.exists(temp_path):
                file_size = os.path.getsize(temp_path)
                if file_size > 0:
                    # Atomic rename - file only appears when complete
                    os.rename(temp_path, final_path)
                    return final_path

            # Clean up failed recording
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        except subprocess.TimeoutExpired:
            # Clean up if timeout occurred
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception:
            # Clean up on any other error
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        return None

    def _recording_loop(self):
        """Main recording loop - runs in separate thread"""
        while self.is_running:
            try:
                chunk_path = self._record_chunk()

                if chunk_path:
                    # Successfully recorded, continue to next chunk
                    pass
                else:
                    # Recording failed, brief pause before retry
                    time.sleep(1)

            except Exception as e:
                # Log error and continue with longer pause
                print(f"Recording error: {e}")
                time.sleep(2)

    def start(self):
        """Start recording in background thread"""
        if self.is_running:
            return

        self.is_running = True
        self.recording_thread = threading.Thread(
            target=self._recording_loop,
            name="HTTPRecordingThread",
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


class RtspRecorder:
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
        self.rtsp_url = rtsp_url
        self.chunk_duration = chunk_duration
        self.output_dir = output_dir
        self.target_sample_rate = target_sample_rate
        self.is_running = False
        self.recording_thread = None

    def _record_chunk(self) -> str:
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

        # Build ffmpeg command for RTSP recording
        # -rtsp_transport tcp: Use TCP for reliability
        # -timeout 10000000: 10 second connection timeout (in microseconds)
        cmd = (
            f'ffmpeg -rtsp_transport tcp -timeout 10000000 '
            f'-i "{self.rtsp_url}" '
            f'-t {self.chunk_duration} '       # Exact duration
            f'-ar {self.target_sample_rate} '  # Sample rate (48kHz)
            f'-ac 1 '                           # Mono
            f'-acodec pcm_s16le '              # 16-bit PCM
            f'-y {temp_path}'                   # Write to temp file first
        )

        try:
            result = subprocess.run(
                ['bash', '-c', cmd],
                capture_output=True,
                text=True,
                timeout=self.chunk_duration + 15  # Extra time for RTSP connection
            )

            # Verify file was created and has content
            if result.returncode == 0 and os.path.exists(temp_path):
                file_size = os.path.getsize(temp_path)
                if file_size > 0:
                    # Atomic rename - file only appears when complete
                    os.rename(temp_path, final_path)
                    return final_path

            # Clean up failed recording
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        except subprocess.TimeoutExpired:
            # Clean up if timeout occurred
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception:
            # Clean up on any other error
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        return None

    def _recording_loop(self):
        """Main recording loop - runs in separate thread"""
        while self.is_running:
            try:
                chunk_path = self._record_chunk()

                if chunk_path:
                    # Successfully recorded, continue to next chunk
                    pass
                else:
                    # Recording failed, brief pause before retry
                    time.sleep(2)  # Longer pause for RTSP reconnection

            except Exception as e:
                # Log error and continue with longer pause
                print(f"RTSP Recording error: {e}")
                time.sleep(3)

    def start(self):
        """Start recording in background thread"""
        if self.is_running:
            return

        self.is_running = True
        self.recording_thread = threading.Thread(
            target=self._recording_loop,
            name="RTSPRecordingThread",
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


class PulseAudioRecorder:
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
        self.source_name = source_name if source_name else "default"
        self.chunk_duration = chunk_duration
        self.output_dir = output_dir
        self.target_sample_rate = target_sample_rate
        self.is_running = False
        self.recording_thread = None

    def _record_chunk(self) -> str:
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

        # Build ffmpeg command for PulseAudio recording
        cmd = (
            f'ffmpeg -f pulse -i {self.source_name} '
            f'-t {self.chunk_duration} '       # Exact duration
            f'-ar {self.target_sample_rate} '  # Sample rate (48kHz)
            f'-ac 1 '                           # Mono
            f'-acodec pcm_s16le '              # 16-bit PCM
            f'-y {temp_path}'                   # Write to temp file first
        )

        try:
            result = subprocess.run(
                ['bash', '-c', cmd],
                capture_output=True,
                text=True,
                timeout=self.chunk_duration + 10
            )

            # Verify file was created and has content
            if result.returncode == 0 and os.path.exists(temp_path):
                file_size = os.path.getsize(temp_path)
                if file_size > 0:
                    # Atomic rename - file only appears when complete
                    os.rename(temp_path, final_path)
                    return final_path

            # Clean up failed recording
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        except subprocess.TimeoutExpired:
            # Clean up if timeout occurred
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception:
            # Clean up on any other error
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        return None

    def _recording_loop(self):
        """Main recording loop - runs in separate thread"""
        while self.is_running:
            try:
                chunk_path = self._record_chunk()

                if chunk_path:
                    # Successfully recorded, continue to next chunk
                    pass
                else:
                    # Recording failed, brief pause before retry
                    time.sleep(1)

            except Exception as e:
                # Log error and continue with longer pause
                print(f"Recording error: {e}")
                time.sleep(2)

    def start(self):
        """Start recording in background thread"""
        if self.is_running:
            return

        self.is_running = True
        self.recording_thread = threading.Thread(
            target=self._recording_loop,
            name="PulseAudioRecordingThread",
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
