"""
API-specific test fixtures and configuration.
"""
import contextlib
import os
import sys
import tempfile
from unittest.mock import Mock, patch

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


@pytest.fixture
def real_db_manager():
    """Create a real database manager with temporary database for API integration tests."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    # Import after path is set
    from core.db import DatabaseManager
    manager = DatabaseManager(db_path=db_path)

    yield manager

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def mock_db_manager():
    """Mock database manager for API tests (legacy - prefer real_db_manager)."""
    mock = Mock()
    # Configure common return values
    mock.get_latest_detections.return_value = []
    mock.get_all_unique_species.return_value = []
    return mock


@contextlib.contextmanager
def _sandboxed_app(db_manager):
    """Yield a Flask test client with the auth and user-settings file paths
    redirected into a tempdir, so the suite never reads or writes the real
    backend/data/ config files. USER_SETTINGS_PATH is patched in every module
    that imported it by value."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_path = os.path.join(tmpdir, 'user_settings.json')
        with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
             patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
             patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
             patch('config.settings.USER_SETTINGS_PATH', settings_path), \
             patch('core.runtime_config.USER_SETTINGS_PATH', settings_path), \
             patch('core.timezone_service.USER_SETTINGS_PATH', settings_path), \
             patch('core.api.USER_SETTINGS_PATH', settings_path), \
             patch('core.api.db_manager', db_manager), \
             patch('core.api.socketio'):
            from core.api import create_app
            app, _ = create_app()
            app.config['TESTING'] = True

            with app.test_client() as client:
                yield client


@pytest.fixture
def api_client(real_db_manager):
    """Create a test client for the Flask API with REAL database integration."""
    with _sandboxed_app(real_db_manager) as client:
        yield client


@pytest.fixture
def api_client_with_mock(mock_db_manager):
    """Create a test client with mocked database (for specific unit tests only)."""
    with _sandboxed_app(mock_db_manager) as client:
        yield client


@pytest.fixture
def sample_wikimedia_response():
    """Sample response from Wikimedia API for testing."""
    return {
        'query': {
            'search': [{
                'title': 'File:American_Robin.jpg'
            }],
            'pages': {
                '12345': {
                    'imageinfo': [{
                        'url': 'https://upload.wikimedia.org/example.jpg',
                        'extmetadata': {
                            'LicenseShortName': {'value': 'CC BY-SA 4.0'},
                            'Artist': {'value': '<a href="http://example.com">John Doe</a>'}
                        }
                    }]
                }
            }
        }
    }


@pytest.fixture
def sample_api_detection():
    """Sample detection data with API-specific fields."""
    return {
        'id': 1,
        'common_name': 'American Robin',
        'scientific_name': 'Turdus migratorius',
        'confidence': 0.95,
        'timestamp': '2024-01-15T10:30:00',
        'audio_file': 'robin_20240115_103000.wav',
        'spectrogram_file': 'robin_20240115_103000.png',
        'bird_song_file_name': 'American_Robin_95_2024-01-15-birdnet-10:30:00.mp3',
        'spectrogram_file_name': 'American_Robin_95_2024-01-15-birdnet-10:30:00.webp'
    }
