"""
Audio test fixtures and configuration.

Provides fixtures for testing HttpStreamRecorder, RtspRecorder, and PulseAudioRecorder
without actual subprocess execution or audio hardware.
"""
import tempfile
from datetime import datetime
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for test recordings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_subprocess_success():
    """Mock subprocess.run for successful recording."""
    with patch('subprocess.run') as mock_run:
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture
def mock_subprocess_failure():
    """Mock subprocess.run for failed recording."""
    with patch('subprocess.run') as mock_run:
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: connection failed"
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture
def mock_datetime_now():
    """Mock datetime.now for consistent timestamps."""
    fixed_time = datetime(2025, 11, 26, 10, 30, 0)
    with patch('core.audio_manager.datetime') as mock_dt:
        mock_dt.now.return_value = fixed_time
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt, fixed_time


@pytest.fixture
def http_recorder_params():
    """Standard parameters for HttpStreamRecorder."""
    return {
        'stream_url': 'http://test-stream:8888/audio.mp3',
        'chunk_duration': 3.0,
        'output_dir': '/tmp/test',
        'target_sample_rate': 48000
    }


@pytest.fixture
def pulse_recorder_params():
    """Standard parameters for PulseAudioRecorder."""
    return {
        'source_name': 'birdnet_monitor.monitor',
        'chunk_duration': 3.0,
        'output_dir': '/tmp/test',
        'target_sample_rate': 48000
    }


@pytest.fixture
def rtsp_recorder_params():
    """Standard parameters for RtspRecorder."""
    return {
        'rtsp_url': 'rtsp://192.168.1.100:554/stream',
        'chunk_duration': 3.0,
        'output_dir': '/tmp/test',
        'target_sample_rate': 48000
    }


@pytest.fixture
def mock_file_operations():
    """Mock file system operations for testing."""
    with patch('os.path.exists') as mock_exists, \
         patch('os.path.getsize') as mock_getsize, \
         patch('os.rename') as mock_rename, \
         patch('os.unlink') as mock_unlink:
        yield {
            'exists': mock_exists,
            'getsize': mock_getsize,
            'rename': mock_rename,
            'unlink': mock_unlink
        }
