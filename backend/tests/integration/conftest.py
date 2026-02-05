"""
Integration test fixtures for main pipeline testing.

Provides fixtures for testing main.py functions with proper isolation
from global state and external services.
"""
import os
import tempfile
from queue import Queue
from unittest.mock import Mock, patch

import pytest


@pytest.fixture
def temp_recording_dir():
    """Create a temporary directory for test recordings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_config_settings(temp_recording_dir):
    """Mock configuration settings for testing."""
    extracted_dir = os.path.join(temp_recording_dir, 'extracted')
    spectrogram_dir = os.path.join(temp_recording_dir, 'spectrograms')
    os.makedirs(extracted_dir, exist_ok=True)
    os.makedirs(spectrogram_dir, exist_ok=True)

    settings = {
        'RECORDING_DIR': temp_recording_dir,
        'RECORDING_LENGTH': 9,
        'EXTRACTED_AUDIO_DIR': extracted_dir,
        'SPECTROGRAM_DIR': spectrogram_dir,
        'BIRDNET_SERVER_ENDPOINT': 'http://birdnet:5001/api/analyze_audio_file',
        'ANALYSIS_CHUNK_LENGTH': 3,
        'API_PORT': 5002,
        'SAMPLE_RATE': 48000,
        'RECORDING_MODE': 'pulseaudio',
        'PULSEAUDIO_SOURCE': 'default',
        'STREAM_URL': 'http://localhost:8888/stream.mp3'
    }
    return settings


@pytest.fixture
def mock_birdnet_success_response():
    """Mock successful BirdNet API response with detections."""
    return [
        {
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.95,
            'timestamp': '2025-11-26T10:30:00',
            'group_timestamp': '2025-11-26T10:30:00',
            'chunk_index': 0,
            'total_chunks': 3,
            'bird_song_file_name': '20251126_103000_American_Robin_95.wav',
            'spectrogram_file_name': '20251126_103000_American_Robin_95.webp',
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        }
    ]


@pytest.fixture
def mock_birdnet_empty_response():
    """Mock BirdNet API response with no detections."""
    return []


@pytest.fixture
def create_test_wav_file(temp_recording_dir):
    """Factory fixture to create test WAV files of specific sizes."""
    created_files = []

    def _create_file(filename, size_bytes):
        file_path = os.path.join(temp_recording_dir, filename)
        with open(file_path, 'wb') as f:
            f.write(b'\x00' * size_bytes)
        created_files.append(file_path)
        return file_path

    yield _create_file

    # Cleanup any remaining files
    for f in created_files:
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass


@pytest.fixture
def fresh_file_queue():
    """Provide a fresh empty queue for each test."""
    return Queue()


@pytest.fixture
def mock_detection_with_metadata():
    """Complete detection data matching BirdNet response format."""
    return {
        'common_name': 'American Robin',
        'scientific_name': 'Turdus migratorius',
        'confidence': 0.95,
        'timestamp': '2025-11-26T10:30:00',
        'group_timestamp': '2025-11-26T10:30:00',
        'chunk_index': 1,
        'total_chunks': 3,
        'bird_song_file_name': 'American_Robin_95_test.wav',
        'spectrogram_file_name': 'American_Robin_95_test.webp',
        'latitude': 40.7128,
        'longitude': -74.0060,
        'cutoff': 0.5,
        'sensitivity': 0.75,
        'overlap': 0.25
    }


@pytest.fixture
def mock_utils_functions():
    """Pre-configured mocks for all utils functions."""
    with patch('core.main.select_audio_chunks') as mock_select, \
         patch('core.main.trim_audio') as mock_trim, \
         patch('core.main.generate_spectrogram') as mock_spec, \
         patch('core.main.convert_wav_to_mp3') as mock_convert:

        # Returns (start_chunk, end_chunk) inclusive - represents 3 chunks (0, 1, 2)
        mock_select.return_value = (0, 2)

        yield {
            'select_audio_chunks': mock_select,
            'trim_audio': mock_trim,
            'generate_spectrogram': mock_spec,
            'convert_wav_to_mp3': mock_convert
        }


@pytest.fixture
def temp_extraction_dirs(temp_recording_dir):
    """Create extraction and spectrogram directories."""
    extracted_dir = os.path.join(temp_recording_dir, 'extracted')
    spectrogram_dir = os.path.join(temp_recording_dir, 'spectrograms')
    os.makedirs(extracted_dir, exist_ok=True)
    os.makedirs(spectrogram_dir, exist_ok=True)

    return {
        'extracted': extracted_dir,
        'spectrogram': spectrogram_dir
    }


# ===== Priority 2 Fixtures: Full Pipeline Integration Tests =====


@pytest.fixture
def pipeline_db_manager():
    """Create real temp database for pipeline integration tests."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    from core.db import DatabaseManager
    manager = DatabaseManager(db_path=db_path)

    yield manager

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def pipeline_temp_dirs(temp_recording_dir):
    """Create complete directory structure for pipeline tests."""
    extracted_dir = os.path.join(temp_recording_dir, 'extracted')
    spectrogram_dir = os.path.join(temp_recording_dir, 'spectrograms')
    os.makedirs(extracted_dir, exist_ok=True)
    os.makedirs(spectrogram_dir, exist_ok=True)

    return {
        'recording': temp_recording_dir,
        'extracted': extracted_dir,
        'spectrogram': spectrogram_dir
    }


@pytest.fixture
def create_valid_wav_file(temp_recording_dir):
    """Factory to create valid WAV files for testing."""
    def _create_file(filename, duration_seconds=6):
        # 48000 Hz * 2 bytes (16-bit) * duration
        size_bytes = 48000 * 2 * duration_seconds
        file_path = os.path.join(temp_recording_dir, filename)
        with open(file_path, 'wb') as f:
            f.write(b'\x00' * size_bytes)
        return file_path

    return _create_file


@pytest.fixture
def mock_birdnet_single_detection():
    """Mock BirdNet API response with single detection."""
    return [
        {
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.95,
            'timestamp': '2025-11-27T10:30:00',
            'group_timestamp': '2025-11-27T10:30:00',
            'chunk_index': 0,
            'total_chunks': 3,
            'bird_song_file_name': 'American_Robin_95_test.wav',
            'spectrogram_file_name': 'American_Robin_95_test.webp',
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        }
    ]


@pytest.fixture
def mock_birdnet_multiple_detections():
    """Mock BirdNet API response with multiple detections."""
    return [
        {
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.95,
            'timestamp': '2025-11-27T10:30:00',
            'group_timestamp': '2025-11-27T10:30:00',
            'chunk_index': 0,
            'total_chunks': 3,
            'bird_song_file_name': 'American_Robin_95_test.wav',
            'spectrogram_file_name': 'American_Robin_95_test.webp',
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        },
        {
            'common_name': 'Blue Jay',
            'scientific_name': 'Cyanocitta cristata',
            'confidence': 0.87,
            'timestamp': '2025-11-27T10:30:03',
            'group_timestamp': '2025-11-27T10:30:00',
            'chunk_index': 1,
            'total_chunks': 3,
            'bird_song_file_name': 'Blue_Jay_87_test.wav',
            'spectrogram_file_name': 'Blue_Jay_87_test.webp',
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        }
    ]


@pytest.fixture
def mock_audio_processing(pipeline_temp_dirs):
    """Mock audio processing that creates real dummy output files."""
    def _mock_trim_audio(input_path, output_path, start, end):
        # Create dummy WAV file
        with open(output_path, 'wb') as f:
            f.write(b'RIFF' + b'\x00' * 100)

    def _mock_generate_spectrogram(input_path, output_path, title, **kwargs):
        # Create dummy WEBP file
        with open(output_path, 'wb') as f:
            f.write(b'RIFF' + b'\x00' * 100)

    def _mock_convert_wav_to_mp3(input_path, output_path, **kwargs):
        # Create dummy MP3 file
        with open(output_path, 'wb') as f:
            f.write(b'ID3' + b'\x00' * 100)

    return {
        'trim_audio': _mock_trim_audio,
        'generate_spectrogram': _mock_generate_spectrogram,
        'convert_wav_to_mp3': _mock_convert_wav_to_mp3
    }


# ===== Priority 3 & 4 Fixtures: Thread Tests + Edge Cases =====


@pytest.fixture
def controllable_stop_flag():
    """Factory for creating controllable stop flag mocks."""
    def _create_stop_flag(iterations=3):
        call_count = [0]
        def stop_after_n():
            call_count[0] += 1
            return call_count[0] > iterations
        return stop_after_n
    return _create_stop_flag


@pytest.fixture
def mock_recorder():
    """Mock recorder for testing recording thread."""
    recorder = Mock()
    recorder.is_healthy.return_value = True
    recorder.start.return_value = None
    recorder.stop.return_value = None
    recorder.restart.return_value = None
    return recorder


@pytest.fixture
def mock_threads():
    """Mock thread objects for shutdown testing."""
    recording_thread = Mock()
    processing_thread = Mock()
    recording_thread.is_alive.return_value = False
    processing_thread.is_alive.return_value = False
    recording_thread.join.return_value = None
    processing_thread.join.return_value = None
    return {
        'recording': recording_thread,
        'processing': processing_thread
    }
