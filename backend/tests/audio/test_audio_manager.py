"""
Tests for audio recording modules.

Tests HttpStreamRecorder, RtspRecorder, and PulseAudioRecorder functionality including:
- Initialization
- Recording chunk creation
- Atomic file operations
- Thread lifecycle management
- Error handling and cleanup
"""
import pytest
import os
import tempfile
import time
import subprocess
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime

from core.audio_manager import HttpStreamRecorder, PulseAudioRecorder, RtspRecorder


class TestHttpStreamRecorderInit:
    """Test HttpStreamRecorder initialization."""

    def test_initialization_stores_parameters(self, http_recorder_params, temp_output_dir):
        """Test that constructor stores all parameters correctly."""
        params = http_recorder_params.copy()
        params['output_dir'] = temp_output_dir

        recorder = HttpStreamRecorder(**params)

        assert recorder.stream_url == params['stream_url']
        assert recorder.chunk_duration == params['chunk_duration']
        assert recorder.output_dir == temp_output_dir
        assert recorder.target_sample_rate == params['target_sample_rate']

    def test_initialization_sets_default_state(self, http_recorder_params, temp_output_dir):
        """Test that recorder starts in stopped state."""
        params = http_recorder_params.copy()
        params['output_dir'] = temp_output_dir

        recorder = HttpStreamRecorder(**params)

        assert recorder.is_running is False
        assert recorder.recording_thread is None


class TestHttpStreamRecorderRecordChunk:
    """Test HttpStreamRecorder._record_chunk() method."""

    def test_record_chunk_builds_correct_command(self, temp_output_dir):
        """Test that the ffmpeg command is built correctly."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename'):
            mock_run.return_value = Mock(returncode=0)

            recorder._record_chunk()

            # Verify subprocess was called
            assert mock_run.called
            call_args = mock_run.call_args
            cmd = call_args[0][0]

            # Should be ['bash', '-c', 'curl ... | ffmpeg ...']
            assert cmd[0] == 'bash'
            assert cmd[1] == '-c'
            assert 'curl' in cmd[2]
            assert 'ffmpeg' in cmd[2]
            assert 'http://test:8888/stream.mp3' in cmd[2]
            assert '-t 3.0' in cmd[2]
            assert '-ar 48000' in cmd[2]
            assert '-ac 1' in cmd[2]

    def test_record_chunk_success_returns_final_path(self, temp_output_dir):
        """Test successful recording returns the final file path."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename') as mock_rename:

            mock_run.return_value = Mock(returncode=0)

            result = recorder._record_chunk()

            # Should return final path (not temp path)
            assert result is not None
            assert result.endswith('.wav')
            assert '.tmp' not in result
            # Filename format: YYYYMMDD_HHMMSS.wav
            import re
            filename = os.path.basename(result)
            assert re.match(r'^\d{8}_\d{6}\.wav$', filename)

    def test_record_chunk_performs_atomic_rename(self, temp_output_dir):
        """Test that file is atomically renamed from temp to final."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename') as mock_rename, \
             patch('core.audio_manager.datetime') as mock_dt:

            mock_dt.now.return_value = datetime(2025, 11, 26, 10, 30, 0)
            mock_run.return_value = Mock(returncode=0)

            recorder._record_chunk()

            # Verify atomic rename was called with temp -> final
            mock_rename.assert_called_once()
            temp_path, final_path = mock_rename.call_args[0]
            assert '.tmp.wav' in temp_path
            assert '.tmp' not in final_path

    def test_record_chunk_failure_returns_none(self, temp_output_dir):
        """Test that failed recording returns None."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=False):
            mock_run.return_value = Mock(returncode=1)

            result = recorder._record_chunk()

            assert result is None

    def test_record_chunk_cleans_up_temp_on_failure(self, temp_output_dir):
        """Test that temp file is cleaned up on failure."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        # Simulate: subprocess succeeds but file exists check passes initially,
        # then we check for cleanup
        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=0), \
             patch('os.unlink') as mock_unlink:
            mock_run.return_value = Mock(returncode=0)

            result = recorder._record_chunk()

            # Empty file should be cleaned up
            assert result is None
            mock_unlink.assert_called_once()

    def test_record_chunk_handles_timeout(self, temp_output_dir):
        """Test that subprocess timeout is handled gracefully."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.unlink') as mock_unlink:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd='test', timeout=13)

            result = recorder._record_chunk()

            assert result is None
            # Should attempt cleanup
            mock_unlink.assert_called_once()

    def test_record_chunk_handles_generic_exception(self, temp_output_dir):
        """Test that generic exceptions are handled gracefully."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.unlink') as mock_unlink:
            mock_run.side_effect = Exception("Unexpected error")

            result = recorder._record_chunk()

            assert result is None
            mock_unlink.assert_called_once()

    def test_record_chunk_rejects_empty_file(self, temp_output_dir):
        """Test that empty files (0 bytes) are rejected."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=0), \
             patch('os.unlink') as mock_unlink, \
             patch('os.rename') as mock_rename:
            mock_run.return_value = Mock(returncode=0)

            result = recorder._record_chunk()

            # Should reject empty file
            assert result is None
            # Should not rename empty file
            mock_rename.assert_not_called()


class TestHttpStreamRecorderLifecycle:
    """Test HttpStreamRecorder start/stop/health methods."""

    def test_start_creates_daemon_thread(self, temp_output_dir):
        """Test that start() creates a daemon thread."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch.object(recorder, '_recording_loop'):
            recorder.start()

            try:
                assert recorder.is_running is True
                assert recorder.recording_thread is not None
                assert recorder.recording_thread.daemon is True
                assert recorder.recording_thread.name == "HTTPRecordingThread"
            finally:
                recorder.is_running = False

    def test_start_is_idempotent(self, temp_output_dir):
        """Test that calling start() twice doesn't create two threads."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch.object(recorder, '_recording_loop'):
            recorder.start()
            first_thread = recorder.recording_thread

            recorder.start()  # Second call should be no-op

            assert recorder.recording_thread is first_thread
            recorder.is_running = False

    def test_stop_sets_is_running_false(self, temp_output_dir):
        """Test that stop() sets is_running to False."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        recorder.is_running = True
        recorder.recording_thread = Mock()
        recorder.recording_thread.is_alive.return_value = True

        recorder.stop()

        assert recorder.is_running is False

    def test_stop_joins_thread_with_timeout(self, temp_output_dir):
        """Test that stop() joins the thread with timeout."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        mock_thread = Mock()
        mock_thread.is_alive.return_value = True
        recorder.is_running = True
        recorder.recording_thread = mock_thread

        recorder.stop()

        mock_thread.join.assert_called_once_with(timeout=5)

    def test_stop_is_idempotent(self, temp_output_dir):
        """Test that calling stop() when not running is safe."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        # Should not raise
        recorder.stop()
        recorder.stop()

    def test_is_healthy_returns_false_when_not_running(self, temp_output_dir):
        """Test is_healthy() returns False when recorder is stopped."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        assert recorder.is_healthy() is False

    def test_is_healthy_returns_true_when_thread_alive(self, temp_output_dir):
        """Test is_healthy() returns True when thread is alive."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        mock_thread = Mock()
        mock_thread.is_alive.return_value = True
        recorder.is_running = True
        recorder.recording_thread = mock_thread

        assert recorder.is_healthy() is True

    def test_is_healthy_returns_false_when_thread_dead(self, temp_output_dir):
        """Test is_healthy() returns False when thread has died."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        mock_thread = Mock()
        mock_thread.is_alive.return_value = False
        recorder.is_running = True
        recorder.recording_thread = mock_thread

        assert recorder.is_healthy() is False

    def test_restart_stops_then_starts(self, temp_output_dir):
        """Test that restart() calls stop() then start()."""
        recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch.object(recorder, 'stop') as mock_stop, \
             patch.object(recorder, 'start') as mock_start, \
             patch('time.sleep'):
            recorder.restart()

            mock_stop.assert_called_once()
            mock_start.assert_called_once()


class TestPulseAudioRecorderInit:
    """Test PulseAudioRecorder initialization."""

    def test_initialization_stores_parameters(self, pulse_recorder_params, temp_output_dir):
        """Test that constructor stores all parameters correctly."""
        params = pulse_recorder_params.copy()
        params['output_dir'] = temp_output_dir

        recorder = PulseAudioRecorder(**params)

        assert recorder.source_name == params['source_name']
        assert recorder.chunk_duration == params['chunk_duration']
        assert recorder.output_dir == temp_output_dir
        assert recorder.target_sample_rate == params['target_sample_rate']

    def test_initialization_defaults_source_name(self, temp_output_dir):
        """Test that empty source_name defaults to 'default'."""
        recorder = PulseAudioRecorder(
            source_name='',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        assert recorder.source_name == 'default'

    def test_initialization_sets_default_state(self, pulse_recorder_params, temp_output_dir):
        """Test that recorder starts in stopped state."""
        params = pulse_recorder_params.copy()
        params['output_dir'] = temp_output_dir

        recorder = PulseAudioRecorder(**params)

        assert recorder.is_running is False
        assert recorder.recording_thread is None


class TestPulseAudioRecorderRecordChunk:
    """Test PulseAudioRecorder._record_chunk() method."""

    def test_record_chunk_builds_correct_command(self, temp_output_dir):
        """Test that the ffmpeg command for PulseAudio is built correctly."""
        recorder = PulseAudioRecorder(
            source_name='birdnet_monitor.monitor',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename'):
            mock_run.return_value = Mock(returncode=0)

            recorder._record_chunk()

            assert mock_run.called
            call_args = mock_run.call_args
            cmd = call_args[0][0]

            # Should be ['bash', '-c', 'ffmpeg -f pulse ...']
            assert cmd[0] == 'bash'
            assert cmd[1] == '-c'
            assert 'ffmpeg' in cmd[2]
            assert '-f pulse' in cmd[2]
            assert '-i birdnet_monitor.monitor' in cmd[2]
            assert '-t 3.0' in cmd[2]
            assert '-ar 48000' in cmd[2]
            assert '-ac 1' in cmd[2]

    def test_record_chunk_success_returns_final_path(self, temp_output_dir):
        """Test successful recording returns the final file path."""
        recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename') as mock_rename, \
             patch('core.audio_manager.datetime') as mock_dt:

            mock_dt.now.return_value = datetime(2025, 11, 26, 10, 30, 0)
            mock_run.return_value = Mock(returncode=0)

            result = recorder._record_chunk()

            assert result is not None
            assert result.endswith('.wav')
            assert '.tmp' not in result

    def test_record_chunk_performs_atomic_rename(self, temp_output_dir):
        """Test that file is atomically renamed from temp to final."""
        recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename') as mock_rename, \
             patch('core.audio_manager.datetime') as mock_dt:

            mock_dt.now.return_value = datetime(2025, 11, 26, 10, 30, 0)
            mock_run.return_value = Mock(returncode=0)

            recorder._record_chunk()

            mock_rename.assert_called_once()
            temp_path, final_path = mock_rename.call_args[0]
            assert '.tmp.wav' in temp_path
            assert '.tmp' not in final_path

    def test_record_chunk_handles_timeout(self, temp_output_dir):
        """Test that subprocess timeout is handled gracefully."""
        recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.unlink') as mock_unlink:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd='test', timeout=13)

            result = recorder._record_chunk()

            assert result is None
            mock_unlink.assert_called_once()


class TestPulseAudioRecorderLifecycle:
    """Test PulseAudioRecorder start/stop/health methods."""

    def test_start_creates_daemon_thread(self, temp_output_dir):
        """Test that start() creates a daemon thread."""
        recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch.object(recorder, '_recording_loop'):
            recorder.start()

            try:
                assert recorder.is_running is True
                assert recorder.recording_thread is not None
                assert recorder.recording_thread.daemon is True
                assert recorder.recording_thread.name == "PulseAudioRecordingThread"
            finally:
                recorder.is_running = False

    def test_is_healthy_returns_false_when_not_running(self, temp_output_dir):
        """Test is_healthy() returns False when recorder is stopped."""
        recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        assert recorder.is_healthy() is False

    def test_restart_stops_then_starts(self, temp_output_dir):
        """Test that restart() calls stop() then start()."""
        recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch.object(recorder, 'stop') as mock_stop, \
             patch.object(recorder, 'start') as mock_start, \
             patch('time.sleep'):
            recorder.restart()

            mock_stop.assert_called_once()
            mock_start.assert_called_once()


class TestRecorderComparison:
    """Test that both recorders produce compatible output patterns."""

    def test_both_recorders_use_same_filename_format(self, temp_output_dir):
        """Test that both recorders use YYYYMMDD_HHMMSS.wav format."""
        import re

        http_recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        pulse_recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename') as mock_rename:

            mock_run.return_value = Mock(returncode=0)

            http_result = http_recorder._record_chunk()

            mock_rename.reset_mock()

            pulse_result = pulse_recorder._record_chunk()

            # Both should produce same filename format: YYYYMMDD_HHMMSS.wav
            http_filename = os.path.basename(http_result)
            pulse_filename = os.path.basename(pulse_result)
            filename_pattern = r'^\d{8}_\d{6}\.wav$'
            assert re.match(filename_pattern, http_filename), f"HTTP filename '{http_filename}' doesn't match pattern"
            assert re.match(filename_pattern, pulse_filename), f"Pulse filename '{pulse_filename}' doesn't match pattern"

    def test_both_recorders_output_same_audio_format(self, temp_output_dir):
        """Test that both recorders specify same audio format in commands."""
        http_recorder = HttpStreamRecorder(
            stream_url='http://test:8888/stream.mp3',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        pulse_recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename'):
            mock_run.return_value = Mock(returncode=0)

            http_recorder._record_chunk()
            http_cmd = mock_run.call_args_list[0][0][0][2]

            pulse_recorder._record_chunk()
            pulse_cmd = mock_run.call_args_list[1][0][0][2]

            # Both should specify same audio format parameters
            for cmd in [http_cmd, pulse_cmd]:
                assert '-ar 48000' in cmd  # Sample rate
                assert '-ac 1' in cmd  # Mono
                assert '-acodec pcm_s16le' in cmd  # 16-bit PCM


class TestRtspRecorderInit:
    """Test RtspRecorder initialization."""

    def test_initialization_stores_parameters(self, rtsp_recorder_params, temp_output_dir):
        """Test that constructor stores all parameters correctly."""
        params = rtsp_recorder_params.copy()
        params['output_dir'] = temp_output_dir

        recorder = RtspRecorder(**params)

        assert recorder.rtsp_url == params['rtsp_url']
        assert recorder.chunk_duration == params['chunk_duration']
        assert recorder.output_dir == temp_output_dir
        assert recorder.target_sample_rate == params['target_sample_rate']

    def test_initialization_sets_default_state(self, rtsp_recorder_params, temp_output_dir):
        """Test that recorder starts in stopped state."""
        params = rtsp_recorder_params.copy()
        params['output_dir'] = temp_output_dir

        recorder = RtspRecorder(**params)

        assert recorder.is_running is False
        assert recorder.recording_thread is None


class TestRtspRecorderRecordChunk:
    """Test RtspRecorder._record_chunk() method."""

    def test_record_chunk_builds_correct_command(self, temp_output_dir):
        """Test that the ffmpeg command for RTSP is built correctly."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename'):
            mock_run.return_value = Mock(returncode=0)

            recorder._record_chunk()

            assert mock_run.called
            call_args = mock_run.call_args
            cmd = call_args[0][0]

            # Should be ['bash', '-c', 'ffmpeg -rtsp_transport tcp ...']
            assert cmd[0] == 'bash'
            assert cmd[1] == '-c'
            assert 'ffmpeg' in cmd[2]
            assert '-rtsp_transport tcp' in cmd[2]
            assert '-timeout 10000000' in cmd[2]
            assert 'rtsp://192.168.1.100:554/stream' in cmd[2]
            assert '-t 3.0' in cmd[2]
            assert '-ar 48000' in cmd[2]
            assert '-ac 1' in cmd[2]

    def test_record_chunk_success_returns_final_path(self, temp_output_dir):
        """Test successful recording returns the final file path."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename') as mock_rename:

            mock_run.return_value = Mock(returncode=0)

            result = recorder._record_chunk()

            # Should return final path (not temp path)
            assert result is not None
            assert result.endswith('.wav')
            assert '.tmp' not in result
            # Filename format: YYYYMMDD_HHMMSS.wav
            import re
            filename = os.path.basename(result)
            assert re.match(r'^\d{8}_\d{6}\.wav$', filename)

    def test_record_chunk_performs_atomic_rename(self, temp_output_dir):
        """Test that file is atomically renamed from temp to final."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename') as mock_rename, \
             patch('core.audio_manager.datetime') as mock_dt:

            mock_dt.now.return_value = datetime(2025, 11, 26, 10, 30, 0)
            mock_run.return_value = Mock(returncode=0)

            recorder._record_chunk()

            # Verify atomic rename was called with temp -> final
            mock_rename.assert_called_once()
            temp_path, final_path = mock_rename.call_args[0]
            assert '.tmp.wav' in temp_path
            assert '.tmp' not in final_path

    def test_record_chunk_failure_returns_none(self, temp_output_dir):
        """Test that failed recording returns None."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=False):
            mock_run.return_value = Mock(returncode=1)

            result = recorder._record_chunk()

            assert result is None

    def test_record_chunk_handles_timeout(self, temp_output_dir):
        """Test that subprocess timeout is handled gracefully."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.unlink') as mock_unlink:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd='test', timeout=18)

            result = recorder._record_chunk()

            assert result is None
            mock_unlink.assert_called_once()


class TestRtspRecorderLifecycle:
    """Test RtspRecorder start/stop/health methods."""

    def test_start_creates_daemon_thread(self, temp_output_dir):
        """Test that start() creates a daemon thread."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch.object(recorder, '_recording_loop'):
            recorder.start()

            try:
                assert recorder.is_running is True
                assert recorder.recording_thread is not None
                assert recorder.recording_thread.daemon is True
                assert recorder.recording_thread.name == "RTSPRecordingThread"
            finally:
                recorder.is_running = False

    def test_start_is_idempotent(self, temp_output_dir):
        """Test that calling start() twice doesn't create two threads."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch.object(recorder, '_recording_loop'):
            recorder.start()
            first_thread = recorder.recording_thread

            recorder.start()  # Second call should be no-op

            assert recorder.recording_thread is first_thread
            recorder.is_running = False

    def test_stop_sets_is_running_false(self, temp_output_dir):
        """Test that stop() sets is_running to False."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        recorder.is_running = True
        recorder.recording_thread = Mock()
        recorder.recording_thread.is_alive.return_value = True

        recorder.stop()

        assert recorder.is_running is False

    def test_is_healthy_returns_false_when_not_running(self, temp_output_dir):
        """Test is_healthy() returns False when recorder is stopped."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        assert recorder.is_healthy() is False

    def test_is_healthy_returns_true_when_thread_alive(self, temp_output_dir):
        """Test is_healthy() returns True when thread is alive."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        mock_thread = Mock()
        mock_thread.is_alive.return_value = True
        recorder.is_running = True
        recorder.recording_thread = mock_thread

        assert recorder.is_healthy() is True

    def test_restart_stops_then_starts(self, temp_output_dir):
        """Test that restart() calls stop() then start()."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        with patch.object(recorder, 'stop') as mock_stop, \
             patch.object(recorder, 'start') as mock_start, \
             patch('time.sleep'):
            recorder.restart()

            mock_stop.assert_called_once()
            mock_start.assert_called_once()
