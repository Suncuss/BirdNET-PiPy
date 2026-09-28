"""
Audio test fixtures and configuration.

Provides fixtures for testing RtspRecorder and PulseAudioRecorder
without actual subprocess execution or audio hardware.
"""
import tempfile

import pytest


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for test recordings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


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
