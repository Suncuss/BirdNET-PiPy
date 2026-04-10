"""
Tests for audio recording modules.

Tests RtspRecorder and PulseAudioRecorder functionality including:
- Initialization
- Recording chunk creation
- Atomic file operations
- Thread lifecycle management
- Error handling and cleanup
- Shell injection prevention (argument lists, not shell strings)
"""
import os
import subprocess
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

from core.audio_manager import (
    BaseRecorder,
    PulseAudioRecorder,
    RtspRecorder,
    create_recorder,
)


class TestCreateRecorderFactory:
    """Test the create_recorder factory function."""

    def test_creates_pulseaudio_recorder(self, temp_output_dir):
        """Test factory creates PulseAudioRecorder for pulseaudio mode."""
        recorder = create_recorder(
            recording_mode='pulseaudio',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000,
            source_name='test_source'
        )
        assert isinstance(recorder, PulseAudioRecorder)
        assert recorder.source_name == 'test_source'

    def test_creates_rtsp_recorder(self, temp_output_dir):
        """Test factory creates RtspRecorder for rtsp mode."""
        recorder = create_recorder(
            recording_mode='rtsp',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000,
            rtsp_url='rtsp://192.168.1.100/stream'
        )
        assert isinstance(recorder, RtspRecorder)
        assert recorder.rtsp_url == 'rtsp://192.168.1.100/stream'

    def test_raises_for_missing_rtsp_url(self, temp_output_dir):
        """Test factory raises ValueError if rtsp mode but no rtsp_url."""
        with pytest.raises(ValueError, match="rtsp_url required"):
            create_recorder(
                recording_mode='rtsp',
                chunk_duration=3.0,
                output_dir=temp_output_dir,
                target_sample_rate=48000
            )

    def test_raises_for_unknown_mode(self, temp_output_dir):
        """Test factory raises ValueError for unknown recording mode."""
        with pytest.raises(ValueError, match="Unknown recording mode"):
            create_recorder(
                recording_mode='unknown_mode',
                chunk_duration=3.0,
                output_dir=temp_output_dir,
                target_sample_rate=48000
            )

    def test_pulseaudio_defaults_to_default_source(self, temp_output_dir):
        """Test pulseaudio mode defaults source_name to 'default'."""
        recorder = create_recorder(
            recording_mode='pulseaudio',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )
        assert recorder.source_name == 'default'


class TestBaseRecorderInterface:
    """Test that BaseRecorder provides correct interface."""

    def test_base_recorder_is_abstract(self):
        """Test that BaseRecorder cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseRecorder(chunk_duration=3.0, output_dir='/tmp', target_sample_rate=48000)

    def test_all_recorders_inherit_from_base(self):
        """Test that all recorder classes inherit from BaseRecorder."""
        assert issubclass(RtspRecorder, BaseRecorder)
        assert issubclass(PulseAudioRecorder, BaseRecorder)


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

    def test_record_chunk_uses_argument_list_not_shell(self, temp_output_dir):
        """Test that the ffmpeg command uses argument list, not shell string."""
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

            # Should be a list, not a string (no shell injection)
            assert isinstance(cmd, list)
            assert cmd[0] == 'ffmpeg'
            assert '-f' in cmd
            assert 'pulse' in cmd
            assert '-i' in cmd
            assert 'birdnet_monitor.monitor' in cmd
            assert '-t' in cmd
            assert '3.0' in cmd
            assert '-ar' in cmd
            assert '48000' in cmd
            assert '-ac' in cmd
            assert '1' in cmd

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
             patch('os.rename'), \
             patch('core.audio_manager.local_now',
                   return_value=datetime(2025, 11, 26, 10, 30, 0)):

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
             patch('core.audio_manager.local_now',
                   return_value=datetime(2025, 11, 26, 10, 30, 0)):

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
    """Test that all recorders produce compatible output patterns."""

    def test_all_recorders_use_same_filename_format(self, temp_output_dir):
        """Test that all recorders use YYYYMMDD_HHMMSS.wav format."""
        import re

        pulse_recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        rtsp_recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        # Test Pulse recorder
        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename'):

            mock_run.return_value = Mock(returncode=0)
            pulse_result = pulse_recorder._record_chunk()

        # Test RTSP recorder
        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename'):

            mock_run.return_value = Mock(returncode=0)
            rtsp_result = rtsp_recorder._record_chunk()

        # All should produce same filename format: YYYYMMDD_HHMMSS.wav
        filename_pattern = r'^\d{8}_\d{6}\.wav$'
        for result, name in [(pulse_result, 'Pulse'), (rtsp_result, 'RTSP')]:
            filename = os.path.basename(result)
            assert re.match(filename_pattern, filename), f"{name} filename '{filename}' doesn't match pattern"

    def test_all_recorders_use_argument_lists_not_shell(self, temp_output_dir):
        """Test that all recorders use argument lists to prevent shell injection."""
        pulse_recorder = PulseAudioRecorder(
            source_name='default',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        rtsp_recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        # PulseAudio recorder should use subprocess.run with list
        with patch('subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.path.getsize', return_value=144000), \
             patch('os.rename'):
            mock_run.return_value = Mock(returncode=0)

            pulse_recorder._record_chunk()
            pulse_cmd = mock_run.call_args[0][0]
            assert isinstance(pulse_cmd, list), "PulseAudio recorder should use argument list"

            mock_run.reset_mock()

            rtsp_recorder._record_chunk()
            rtsp_cmd = mock_run.call_args[0][0]
            assert isinstance(rtsp_cmd, list), "RTSP recorder should use argument list"


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

    def test_record_chunk_uses_argument_list_not_shell(self, temp_output_dir):
        """Test that the ffmpeg command uses argument list, not shell string."""
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

            # Should be a list, not a string (no shell injection)
            assert isinstance(cmd, list)
            assert cmd[0] == 'ffmpeg'
            assert '-rtsp_transport' in cmd
            assert 'tcp' in cmd
            assert '-timeout' in cmd
            assert '10000000' in cmd
            assert '-allowed_media_types' in cmd
            assert 'audio' in cmd
            assert '-fflags' in cmd
            assert '+genpts+discardcorrupt' in cmd
            assert '-use_wallclock_as_timestamps' in cmd
            assert '1' in cmd
            assert 'rtsp://192.168.1.100:554/stream' in cmd
            assert '-map' in cmd
            assert '0:a:0' in cmd
            assert '-af' in cmd
            assert 'aresample=async=1:first_pts=0' in cmd
            assert '-t' in cmd
            assert '3.0' in cmd
            assert '-ar' in cmd
            assert '48000' in cmd

            assert cmd.index('-allowed_media_types') < cmd.index('-i')
            assert cmd.index('-map') > cmd.index('-i')

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
             patch('os.rename'):

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
             patch('core.audio_manager.local_now',
                   return_value=datetime(2025, 11, 26, 10, 30, 0)):

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

    def test_rtsp_recorder_has_retry_delay(self, temp_output_dir):
        """Test that RTSP recorder has a retry delay for reconnection."""
        recorder = RtspRecorder(
            rtsp_url='rtsp://192.168.1.100:554/stream',
            chunk_duration=3.0,
            output_dir=temp_output_dir,
            target_sample_rate=48000
        )

        assert recorder._get_retry_delay() > 0


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
