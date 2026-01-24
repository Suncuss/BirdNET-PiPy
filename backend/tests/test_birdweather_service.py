"""Tests for the BirdWeather service module."""

import os
import pytest
import tempfile
import threading
import time
from unittest.mock import patch, MagicMock, mock_open

import requests


class TestBirdWeatherService:
    """Test BirdWeatherService class functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        import core.birdweather_service as bws
        bws._birdweather_service = None

    def _create_test_detection(self):
        """Create a sample detection dict for testing."""
        return {
            'timestamp': '2024-01-15T10:30:00',
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.85,
            'chunk_index': 0,
            'total_chunks': 3,
            'step_seconds': 3
        }

    def test_service_initialization(self):
        """Test service initializes with station ID."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'):
            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')
            assert service._station_id == 'test-station-123'

    def test_publish_queues_detection(self):
        """Test that publish extracts FLAC and queues for upload."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True):

            mock_run.return_value = MagicMock(returncode=0)

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')

            detection = self._create_test_detection()
            service.publish(detection, '/path/to/audio.wav', 0.0, 3.0)

            # Verify ffmpeg was called to extract FLAC (synchronously)
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert 'ffmpeg' in call_args
            assert '-c:a' in call_args
            assert 'flac' in call_args

    def test_extract_flac_success(self):
        """Test successful FLAC extraction via ffmpeg."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.subprocess.run') as mock_run, \
             patch('os.path.exists') as mock_exists, \
             tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:

            # Create a dummy audio file
            tmp.write(b'dummy audio data')
            tmp.flush()

            mock_exists.return_value = True
            mock_run.return_value = MagicMock(returncode=0)

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')
            result = service._extract_flac(tmp.name, 0.0, 3.0)

            # Should return a path (the temp flac file)
            assert result is not None
            assert result.endswith('.flac')

            # Clean up
            os.unlink(tmp.name)
            if os.path.exists(result):
                os.unlink(result)

    def test_extract_flac_file_not_found(self):
        """Test FLAC extraction when audio file doesn't exist."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('os.path.exists', return_value=False):

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')
            result = service._extract_flac('/nonexistent/audio.wav', 0.0, 3.0)

            assert result is None

    def test_extract_flac_ffmpeg_failure(self):
        """Test FLAC extraction when ffmpeg fails."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.subprocess.run') as mock_run, \
             patch('os.path.exists', return_value=True), \
             patch('os.remove'):

            mock_run.return_value = MagicMock(returncode=1, stderr=b'ffmpeg error')

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')
            result = service._extract_flac('/path/to/audio.wav', 0.0, 3.0)

            assert result is None

    def test_upload_soundscape_success(self):
        """Test successful soundscape upload."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.requests.post') as mock_post, \
             tempfile.NamedTemporaryFile(suffix='.flac', delete=False) as tmp:

            tmp.write(b'fake flac data')
            tmp.flush()

            mock_response = MagicMock()
            mock_response.status_code = 201  # BirdWeather returns 201 for created
            mock_response.json.return_value = {
                'soundscape': {'id': 12345}
            }
            mock_post.return_value = mock_response

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')
            result = service._upload_soundscape(tmp.name, '2024-01-15T10:30:00')

            assert result == '12345'

            # Verify API was called correctly
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert 'test-station-123' in call_args[0][0]
            assert call_args[1]['headers']['Content-Type'] == 'audio/flac'

            os.unlink(tmp.name)

    def test_upload_soundscape_api_error(self):
        """Test soundscape upload with API error."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.requests.post') as mock_post, \
             tempfile.NamedTemporaryFile(suffix='.flac', delete=False) as tmp:

            tmp.write(b'fake flac data')
            tmp.flush()

            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.text = 'Unauthorized'
            mock_post.return_value = mock_response

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')
            result = service._upload_soundscape(tmp.name, '2024-01-15T10:30:00')

            assert result is None

            os.unlink(tmp.name)

    def test_upload_soundscape_timeout(self):
        """Test soundscape upload timeout handling."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.requests.post') as mock_post, \
             tempfile.NamedTemporaryFile(suffix='.flac', delete=False) as tmp:

            tmp.write(b'fake flac data')
            tmp.flush()

            mock_post.side_effect = requests.exceptions.Timeout()

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')
            result = service._upload_soundscape(tmp.name, '2024-01-15T10:30:00')

            assert result is None

            os.unlink(tmp.name)

    def test_upload_detection_success(self):
        """Test successful detection upload."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.requests.post') as mock_post, \
             patch('core.birdweather_service.LAT', 42.47), \
             patch('core.birdweather_service.LON', -76.45):

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_post.return_value = mock_response

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')

            detection = self._create_test_detection()
            result = service._upload_detection(
                detection, '12345', '2024-01-15T10:30:00', 3.0
            )

            assert result is True

            # Verify API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            payload = call_args[1]['json']

            assert payload['commonName'] == 'American Robin'
            assert payload['scientificName'] == 'Turdus migratorius'
            assert payload['confidence'] == 0.85
            assert payload['soundscapeId'] == '12345'
            assert payload['soundscapeStartTime'] == 0
            assert payload['soundscapeEndTime'] == 3.0
            assert payload['lat'] == 42.47
            assert payload['lon'] == -76.45

    def test_upload_detection_api_error(self):
        """Test detection upload with API error."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.requests.post') as mock_post, \
             patch('core.birdweather_service.LAT', 42.47), \
             patch('core.birdweather_service.LON', -76.45):

            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = 'Internal Server Error'
            mock_post.return_value = mock_response

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')

            detection = self._create_test_detection()
            result = service._upload_detection(
                detection, '12345', '2024-01-15T10:30:00', 3.0
            )

            assert result is False

    def test_upload_detection_timeout(self):
        """Test detection upload timeout handling."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.requests.post') as mock_post, \
             patch('core.birdweather_service.LAT', 42.47), \
             patch('core.birdweather_service.LON', -76.45):

            mock_post.side_effect = requests.exceptions.Timeout()

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')

            detection = self._create_test_detection()
            result = service._upload_detection(
                detection, '12345', '2024-01-15T10:30:00', 3.0
            )

            assert result is False

    def test_do_publish_full_flow(self):
        """Test the full publish flow (upload soundscape, upload detection)."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.requests.post') as mock_post, \
             patch('core.birdweather_service.LAT', 42.47), \
             patch('core.birdweather_service.LON', -76.45), \
             patch('os.path.exists', return_value=True), \
             patch('os.remove'), \
             patch('builtins.open', mock_open(read_data=b'fake flac data')):

            # Mock API responses (201 for soundscape creation)
            soundscape_response = MagicMock()
            soundscape_response.status_code = 201
            soundscape_response.json.return_value = {'soundscape': {'id': 99999}}

            detection_response = MagicMock()
            detection_response.status_code = 201

            mock_post.side_effect = [soundscape_response, detection_response]

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')

            detection = self._create_test_detection()
            # Call _do_publish directly with a FLAC path and clip duration
            service._do_publish(detection, '/tmp/test.flac', 3.0)

            # Verify both API calls were made
            assert mock_post.call_count == 2

            # Verify detection payload has correct offsets (0 to clip_duration)
            detection_call = mock_post.call_args_list[1]
            payload = detection_call[1]['json']
            assert payload['soundscapeStartTime'] == 0
            assert payload['soundscapeEndTime'] == 3.0


class TestBirdWeatherServiceSingleton:
    """Test the get_birdweather_service singleton function."""

    def setup_method(self):
        """Reset singleton before each test."""
        import core.birdweather_service as bws
        bws._birdweather_service = None

    def test_singleton_returns_none_when_no_id(self):
        """Test that singleton returns None when no station ID configured."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', None):
            from core.birdweather_service import get_birdweather_service
            service = get_birdweather_service()
            assert service is None

    def test_singleton_returns_instance_when_id_configured(self):
        """Test that singleton returns instance when station ID is configured."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'):
            import core.birdweather_service as bws
            bws._birdweather_service = None  # Reset

            from core.birdweather_service import get_birdweather_service, BirdWeatherService
            service = get_birdweather_service()

            assert service is not None
            assert isinstance(service, BirdWeatherService)

    def test_singleton_returns_same_instance(self):
        """Test that singleton returns the same instance on multiple calls."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'):
            import core.birdweather_service as bws
            bws._birdweather_service = None  # Reset

            from core.birdweather_service import get_birdweather_service
            service1 = get_birdweather_service()
            service2 = get_birdweather_service()

            assert service1 is service2


class TestBirdWeatherServiceWorker:
    """Test the background worker functionality."""

    def setup_method(self):
        """Reset singleton before each test."""
        import core.birdweather_service as bws
        bws._birdweather_service = None

    def test_worker_processes_queue_items(self):
        """Test that worker thread processes queued items."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.subprocess.run') as mock_run, \
             patch('core.birdweather_service.requests.post') as mock_post, \
             patch('core.birdweather_service.LAT', 42.47), \
             patch('core.birdweather_service.LON', -76.45), \
             patch('os.path.exists', return_value=True), \
             patch('os.remove'), \
             patch('builtins.open', mock_open(read_data=b'fake flac data')), \
             tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_wav:

            # Create a real temp file for extraction
            tmp_wav.write(b'fake wav data')
            tmp_wav.flush()

            mock_run.return_value = MagicMock(returncode=0)

            soundscape_response = MagicMock()
            soundscape_response.status_code = 201
            soundscape_response.json.return_value = {'soundscape': {'id': 12345}}

            detection_response = MagicMock()
            detection_response.status_code = 201

            mock_post.side_effect = [soundscape_response, detection_response]

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')

            detection = {
                'timestamp': '2024-01-15T10:30:00',
                'common_name': 'American Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85,
                'chunk_index': 0
            }

            # Queue a detection (will extract FLAC synchronously then queue)
            service.publish(detection, tmp_wav.name, 0.0, 3.0)

            # Give worker time to process
            time.sleep(0.5)

            # Verify API calls were made (worker processed the item)
            assert mock_post.call_count >= 1

            # Clean up
            if os.path.exists(tmp_wav.name):
                os.unlink(tmp_wav.name)

    def test_worker_handles_errors_gracefully(self):
        """Test that worker continues processing after an error."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('os.path.exists', return_value=False):  # Force file not found error

            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')

            detection = {
                'timestamp': '2024-01-15T10:30:00',
                'common_name': 'American Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85
            }

            # Queue a detection that will fail
            service.publish(detection, '/nonexistent/audio.wav', 0.0, 3.0)

            # Give worker time to process
            time.sleep(0.3)

            # Worker should still be alive (daemon thread)
            assert service._worker.is_alive()

    def test_queue_full_drops_upload(self):
        """Test that uploads are dropped when queue is full."""
        with patch('core.birdweather_service.BIRDWEATHER_ID', 'test-station-123'), \
             patch('core.birdweather_service.subprocess.run') as mock_run, \
             patch('core.birdweather_service.BIRDWEATHER_QUEUE_MAXSIZE', 1), \
             patch('os.path.exists', return_value=True), \
             patch('os.remove') as mock_remove:

            mock_run.return_value = MagicMock(returncode=0)

            # Import after patching maxsize
            import core.birdweather_service as bws
            bws._birdweather_service = None

            # Create service with tiny queue (maxsize=1)
            # We need to reload to get the patched maxsize
            from core.birdweather_service import BirdWeatherService
            service = BirdWeatherService('test-station-123')

            # Block the worker so queue fills up
            import queue as q
            service._queue = q.Queue(maxsize=1)

            detection = {
                'timestamp': '2024-01-15T10:30:00',
                'common_name': 'American Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85
            }

            # First publish should succeed (queue empty)
            service.publish(detection, '/path/to/audio1.wav', 0.0, 3.0)
            assert service._queue.qsize() == 1

            # Second publish should be dropped (queue full)
            service.publish(detection, '/path/to/audio2.wav', 0.0, 3.0)
            assert service._queue.qsize() == 1  # Still 1, second was dropped

            # Verify cleanup was called for dropped upload
            assert mock_remove.call_count >= 1
