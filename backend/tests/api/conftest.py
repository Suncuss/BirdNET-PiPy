"""
API-specific test fixtures and configuration.
"""
import contextlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

AUTH_TEST_PASSWORD = 'testpass123'
DEFAULT_STATION_NAME = 'My Secret Station'


def iso_ago(days_ago=0, seconds=0):
    """A timestamp days_ago in the past (recent < 30d = in the public window)."""
    return (datetime.now() - timedelta(days=days_ago, seconds=seconds)).strftime('%Y-%m-%dT%H:%M:%S')


def insert_detection(db_manager, **overrides):
    """Seed one detection row, defaulting the boilerplate columns.

    Most API tests need the same fully-populated row shape and only care about
    one or two fields; keeping the boilerplate here means a schema change (a
    new required column) touches one place. ``group_timestamp`` defaults to
    ``timestamp``. Returns the inserted row id.
    """
    detection = {
        'timestamp': '2024-01-15T10:30:00',
        'common_name': 'American Robin',
        'scientific_name': 'Turdus migratorius',
        'confidence': 0.9,
        'latitude': 40.7128,
        'longitude': -74.0060,
        'cutoff': 0.5,
        'sensitivity': 0.75,
        'overlap': 0.25,
        **overrides,
    }
    detection.setdefault('group_timestamp', detection['timestamp'])
    return db_manager.insert_detection(detection)


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
             patch('core.settings_store.USER_SETTINGS_PATH', settings_path), \
             patch('core.api_infra.db_manager', db_manager), \
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


@contextlib.contextmanager
def sandboxed_auth_env(db_manager=None, settings=None, mock_socketio=True):
    """Tempdir sandbox for auth-ENABLED app tests.

    Same path-redirection idea as _sandboxed_app, but writes a settings file
    the test controls (auth/access tests toggle flags through it) and can keep
    the real SocketIO instance (mock_socketio=False, for websocket tests).
    db_manager=None patches core.api_infra.db_manager with a bare Mock. Yields
    (api_module, settings_file); callers run create_app() themselves so they
    can shape what they need (HTTP test client vs. socketio test client).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_file = os.path.join(tmpdir, 'user_settings.json')
        with open(settings_file, 'w') as f:
            json.dump(settings or {}, f)

        patches = [
            patch('core.auth.AUTH_CONFIG_DIR', tmpdir),
            patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')),
            patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')),
            patch('config.settings.USER_SETTINGS_PATH', settings_file),
            patch('core.runtime_config.USER_SETTINGS_PATH', settings_file),
            patch('core.timezone_service.USER_SETTINGS_PATH', settings_file),
            patch('core.settings_store.USER_SETTINGS_PATH', settings_file),
            patch('core.api_infra.db_manager') if db_manager is None
            else patch('core.api_infra.db_manager', db_manager),
        ]
        if mock_socketio:
            patches.append(patch('core.api.socketio'))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            import core.api as api_module
            from core.runtime_config import invalidate_runtime_settings_cache

            # The runtime-settings cache is module-global; drop any other
            # sandbox's cached file on the way in and our own on the way out.
            invalidate_runtime_settings_cache()
            try:
                yield api_module, settings_file
            finally:
                invalidate_runtime_settings_cache()


@contextlib.contextmanager
def auth_enabled_app(db_manager, access=None):
    """Flask test client with auth SET UP and ENABLED, starting anonymous.

    The existing api_client fixture runs auth-disabled (every caller is
    'owner', so access gating is inert); this harness exercises the gates for
    real. Default access settings: master public_access on, per-feature flags
    off; ``access`` overrides individual keys. Yields (client, settings_file).
    """
    settings = {
        'audio': {'recording_mode': 'pulseaudio'},
        'location': {'latitude': 40.0, 'longitude': -75.0},
        'display': {'station_name': DEFAULT_STATION_NAME},
        'access': {
            'public_access': True,
            'charts_public': False,
            'table_public': False,
            'live_feed_public': False,
        },
    }
    if access:
        settings['access'].update(access)
    with sandboxed_auth_env(db_manager, settings) as (api_module, settings_file):
        app, _ = api_module.create_app()
        app.config['TESTING'] = True
        with app.test_client() as client:
            client.post('/api/auth/setup',
                        data=json.dumps({'password': AUTH_TEST_PASSWORD}),
                        content_type='application/json')
            client.post('/api/auth/logout')  # start anonymous
            yield client, settings_file


def login_owner(client):
    """Sign the test client in as the station owner."""
    client.post('/api/auth/login',
                data=json.dumps({'password': AUTH_TEST_PASSWORD}),
                content_type='application/json')


@pytest.fixture
def media_dirs():
    """Patch the audio/spectrogram directories to empty temp dirs.

    The recordings endpoint skips records whose audio/spectrogram files are
    absent from disk; tests use these dirs to make specific recordings'
    files present (by creating them) or absent (by leaving them out)."""
    with tempfile.TemporaryDirectory() as tmp:
        audio_dir = os.path.join(tmp, 'extracted_songs')
        spectrogram_dir = os.path.join(tmp, 'spectrograms')
        os.makedirs(audio_dir)
        os.makedirs(spectrogram_dir)
        with patch('core.routes.media.EXTRACTED_AUDIO_DIR', audio_dir), \
             patch('core.routes.media.SPECTROGRAM_DIR', spectrogram_dir):
            yield audio_dir, spectrogram_dir


@pytest.fixture
def create_recording_files(media_dirs):
    """Factory that creates on-disk audio+spectrogram files for a species'
    recordings, so the recordings endpoint's media filter treats them as present.

    Call as ``create_recording_files(db_manager, species_name='...')`` or with
    ``scientific_name='...'``. ``choices`` optionally maps a recent-sort index to
    'both' (default), 'audio', 'spectrogram', or 'none'. Returns the recordings
    list (recent sort) so callers can assert which records survive filtering."""
    audio_dir, spectrogram_dir = media_dirs

    def _create(db_manager, *, species_name=None, scientific_name=None, choices=None):
        recordings = db_manager.get_bird_recordings(
            species_name=species_name, scientific_name=scientific_name, sort='recent',
        )
        for index, recording in enumerate(recordings):
            choice = choices.get(index, 'both') if choices else 'both'
            if choice in ('both', 'audio'):
                open(os.path.join(audio_dir, recording['audio_filename']), 'wb').close()
            if choice in ('both', 'spectrogram'):
                open(os.path.join(spectrogram_dir, recording['spectrogram_filename']), 'wb').close()
        return recordings

    return _create


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
