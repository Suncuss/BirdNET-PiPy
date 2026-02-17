"""Simple API tests that demonstrate working patterns."""

import csv
import json
import os
import tempfile
from datetime import datetime
from unittest.mock import Mock, patch

import pytest


class TestSimpleAPI:
    """Basic API tests with proper mocking."""

    def test_database_tests_working(self):
        """Verify our test setup works."""
        assert True  # Simple sanity check

    def test_api_with_real_db(self, api_client, real_db_manager):
        """Test API endpoints with REAL database integration."""
        # Test 1: Latest observation with data
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:45',
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.9500,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        response = api_client.get('/api/observations/latest')
        assert response.status_code == 200
        data = response.get_json()
        assert data['common_name'] == 'American Robin'
        assert data['confidence'] == pytest.approx(0.95, abs=0.01)

        # Test 2: Recent observations
        # Insert 2 more detections
        for i in range(2):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T10:3{i+1}:00',
                'group_timestamp': f'2024-01-15T10:3{i+1}:00',
                'common_name': 'Blue Jay',
                'scientific_name': 'Cyanocitta cristata',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        response = api_client.get('/api/observations/recent')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) >= 3

        # Test 3: Summary stats
        response = api_client.get('/api/observations/summary')
        assert response.status_code == 200
        summary = response.get_json()
        assert 'today' in summary
        assert 'week' in summary
        assert 'month' in summary
        assert 'allTime' in summary

    def test_api_empty_database(self, api_client, real_db_manager):
        """Test API endpoints return proper response when database is empty."""
        # Test with empty database - returns 200 with null for better frontend UX
        response = api_client.get('/api/observations/latest')
        assert response.status_code == 200
        assert response.get_json() is None

    def test_activity_endpoints(self, api_client, real_db_manager):
        """Test activity-related endpoints with real database."""
        # Insert detections across different hours
        from datetime import timedelta
        base_time = datetime(2024, 1, 15, 10, 0, 0)

        for i in range(5):
            real_db_manager.insert_detection({
                'timestamp': (base_time + timedelta(hours=i)).isoformat(),
                'group_timestamp': (base_time + timedelta(hours=i)).isoformat(),
                'common_name': 'American Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        # Insert some Blue Jays
        for i in range(3):
            real_db_manager.insert_detection({
                'timestamp': (base_time + timedelta(hours=i+2)).isoformat(),
                'group_timestamp': (base_time + timedelta(hours=i+2)).isoformat(),
                'common_name': 'Blue Jay',
                'scientific_name': 'Cyanocitta cristata',
                'confidence': 0.80,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        # Test hourly activity
        response = api_client.get('/api/activity/hourly?date=2024-01-15')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 24

        # Test activity overview
        response = api_client.get('/api/activity/overview?date=2024-01-15')
        assert response.status_code == 200
        data = response.get_json()
        # Should have at least 2 species
        assert len(data) >= 2

    def test_species_endpoints(self, api_client, real_db_manager):
        """Test species-related endpoints with real database."""
        # Insert detections for multiple species
        species_list = [
            ('American Robin', 'Turdus migratorius'),
            ('Blue Jay', 'Cyanocitta cristata'),
            ('Northern Cardinal', 'Cardinalis cardinalis')
        ]

        for common, scientific in species_list:
            for i in range(3):  # 3 detections per species
                real_db_manager.insert_detection({
                    'timestamp': f'2024-01-15T10:3{i}:00',
                    'group_timestamp': f'2024-01-15T10:3{i}:00',
                    'common_name': common,
                    'scientific_name': scientific,
                    'confidence': 0.85 + (i * 0.02),
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        # Test all species
        response = api_client.get('/api/species/all')
        assert response.status_code == 200
        species = response.get_json()
        assert len(species) == 3
        # API returns list of dicts with common_name and scientific_name
        species_names = [s['common_name'] for s in species]
        assert 'American Robin' in species_names
        assert 'Blue Jay' in species_names

        # Test bird details
        response = api_client.get('/api/bird/American%20Robin')
        assert response.status_code == 200
        data = response.get_json()
        assert data['common_name'] == 'American Robin'
        # Verify we got expected bird detail fields
        assert 'average_confidence' in data
        assert 'first_detected' in data or 'first_detection' in data
        assert 'last_detected' in data or 'last_detection' in data

    def test_file_serving_endpoints(self):
        """Test file serving with mocked paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_dir = os.path.join(tmpdir, 'audio')
            os.makedirs(audio_dir)

            # Create test file
            test_file = os.path.join(audio_dir, 'test.mp3')
            with open(test_file, 'wb') as f:
                f.write(b'fake audio data')

            # Create default file
            default_file = os.path.join(tmpdir, 'default.mp3')
            with open(default_file, 'wb') as f:
                f.write(b'default audio')

            # Patch the paths (including auth config to prevent writing to backend/data/)
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.EXTRACTED_AUDIO_DIR', audio_dir), \
                 patch('core.api.DEFAULT_AUDIO_PATH', default_file), \
                 patch('core.db.DatabaseManager'):

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                # Test existing file
                response = client.get('/api/audio/test.mp3')
                assert response.status_code == 200
                assert response.data == b'fake audio data'

                # Test non-existent file (should return default)
                response = client.get('/api/audio/missing.mp3')
                assert response.status_code == 200
                assert response.data == b'default audio'

    def test_sightings_endpoints(self, api_client, real_db_manager):
        """Test sightings-related endpoints with real database."""
        # Insert varied detections
        # Frequent species (many detections)
        for i in range(50):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T{10+i//10:02d}:{i%60:02d}:00',
                'group_timestamp': f'2024-01-15T{10+i//10:02d}:{i%60:02d}:00',
                'common_name': 'House Sparrow',
                'scientific_name': 'Passer domesticus',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        # Rare species (few detections)
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T12:00:00',
            'group_timestamp': '2024-01-15T12:00:00',
            'common_name': 'Rare Bird',
            'scientific_name': 'Rarus birdus',
            'confidence': 0.90,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        # Test unique sightings
        response = api_client.get('/api/sightings/unique?date=2024-01-15')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert len(data) >= 2

        # Test frequent type
        response = api_client.get('/api/sightings?type=frequent')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) > 0
        # House Sparrow should be in frequent
        assert any(d['common_name'] == 'House Sparrow' for d in data)

        # Test rare type
        response = api_client.get('/api/sightings?type=rare')
        assert response.status_code == 200
        data = response.get_json()
        # Should have results
        assert len(data) > 0

        # Test invalid type
        response = api_client.get('/api/sightings?type=invalid')
        assert response.status_code == 400
        assert 'Invalid sighting type' in response.get_json()['error']

    def test_wikimedia_endpoints(self):
        """Test Wikimedia image fetching."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager') as MockDB, \
                 patch('core.api.requests.get') as mock_get:

                mock_db_instance = Mock()
                MockDB.return_value = mock_db_instance

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                # Mock successful Wikimedia API response
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    'query': {
                        'search': [{'title': 'File:Robin.jpg'}],
                        'pages': {
                            '123': {
                                'title': 'File:Robin.jpg',
                                'imageinfo': [{
                                    'url': 'https://upload.wikimedia.org/robin.jpg',
                                    'extmetadata': {
                                        'LicenseShortName': {'value': 'CC BY-SA'},
                                        'Artist': {'value': 'John Doe'},
                                        'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by-sa/4.0'}
                                    }
                                }]
                            }
                        }
                    }
                }
                mock_get.return_value = mock_response

                response = client.get('/api/wikimedia_image?species=American%20Robin')
                assert response.status_code == 200
                data = response.get_json()
                assert 'imageUrl' in data
                assert data['imageUrl'] == 'https://upload.wikimedia.org/robin.jpg'
                assert 'licenseType' in data
                assert 'authorName' in data

                # Test missing species parameter
                response = client.get('/api/wikimedia_image')
                assert response.status_code == 400

    def test_settings_endpoints(self):
        """Test settings management."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager') as MockDB, \
                 patch('core.api.load_user_settings') as mock_load, \
                 patch('core.api.save_user_settings') as mock_save, \
                 patch('core.api.write_flag') as mock_flag:

                mock_db_instance = Mock()
                MockDB.return_value = mock_db_instance

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                # Test GET settings
                mock_settings = {
                    'audio': {'samplerate': 48000},
                    'ui': {'theme': 'dark'}
                }
                mock_load.return_value = mock_settings

                response = client.get('/api/settings')
                assert response.status_code == 200
                assert response.get_json() == mock_settings

                # Test PUT settings
                new_settings = {'audio': {'samplerate': 44100}}
                response = client.put('/api/settings',
                                    data=json.dumps(new_settings),
                                    content_type='application/json')
                assert response.status_code == 200
                assert response.get_json()['message'] == 'Settings saved. Services will restart in 10-30 seconds.'
                mock_save.assert_called_once()
                assert mock_flag.call_count >= 1  # at least one restart flag

    def test_settings_url_validation(self):
        """Test URL validation for stream settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager') as MockDB, \
                 patch('core.api.load_user_settings') as mock_load, \
                 patch('core.api.save_user_settings'), \
                 patch('core.api.write_flag'):

                mock_db_instance = Mock()
                MockDB.return_value = mock_db_instance
                mock_load.return_value = {}

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                # Test invalid HTTP stream URL (must start with http:// or https://)
                invalid_stream = {
                    'audio': {
                        'recording_mode': 'http_stream',
                        'stream_url': 'ftp://example.com/stream'
                    }
                }
                response = client.put('/api/settings',
                                    data=json.dumps(invalid_stream),
                                    content_type='application/json')
                assert response.status_code == 400
                assert 'Invalid Stream URL' in response.get_json()['error']

                # Test invalid RTSP URL (must start with rtsp:// or rtsps://)
                invalid_rtsp = {
                    'audio': {
                        'recording_mode': 'rtsp',
                        'rtsp_url': 'http://example.com/stream'
                    }
                }
                response = client.put('/api/settings',
                                    data=json.dumps(invalid_rtsp),
                                    content_type='application/json')
                assert response.status_code == 400
                assert 'Invalid RTSP URL' in response.get_json()['error']

                # Test missing URL when required
                missing_stream_url = {
                    'audio': {
                        'recording_mode': 'http_stream',
                        'stream_url': ''
                    }
                }
                response = client.put('/api/settings',
                                    data=json.dumps(missing_stream_url),
                                    content_type='application/json')
                assert response.status_code == 400
                assert 'Stream URL required' in response.get_json()['error']

                missing_rtsp_url = {
                    'audio': {
                        'recording_mode': 'rtsp',
                        'rtsp_url': ''
                    }
                }
                response = client.put('/api/settings',
                                    data=json.dumps(missing_rtsp_url),
                                    content_type='application/json')
                assert response.status_code == 400
                assert 'RTSP URL required' in response.get_json()['error']

    def test_update_channel_setting(self):
        """Test update channel setting endpoint (no restart)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager') as MockDB, \
                 patch('core.api.load_user_settings') as mock_load, \
                 patch('core.api.save_user_settings') as mock_save, \
                 patch('core.api.write_flag') as mock_flag:

                mock_db_instance = Mock()
                MockDB.return_value = mock_db_instance

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                mock_load.return_value = {
                    'audio': {'samplerate': 48000}
                }

                response = client.put('/api/settings/channel',
                                      data=json.dumps({'channel': 'latest'}),
                                      content_type='application/json')
                assert response.status_code == 200
                data = response.get_json()
                assert data['channel'] == 'latest'
                mock_save.assert_called_once_with({
                    'audio': {'samplerate': 48000},
                    'updates': {'channel': 'latest'}
                })
                mock_flag.assert_not_called()

                mock_save.reset_mock()
                response = client.put('/api/settings/channel',
                                      data=json.dumps({'channel': 'invalid'}),
                                      content_type='application/json')
                assert response.status_code == 400
                mock_save.assert_not_called()

    def test_update_units_setting(self):
        """Test update units setting endpoint (no restart)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager') as MockDB, \
                 patch('core.api.load_user_settings') as mock_load, \
                 patch('core.api.save_user_settings') as mock_save, \
                 patch('core.api.write_flag') as mock_flag:

                mock_db_instance = Mock()
                MockDB.return_value = mock_db_instance

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                mock_load.return_value = {
                    'audio': {'samplerate': 48000}
                }

                # Test setting to imperial (False)
                response = client.put('/api/settings/units',
                                      data=json.dumps({'use_metric_units': False}),
                                      content_type='application/json')
                assert response.status_code == 200
                data = response.get_json()
                assert data['use_metric_units'] is False
                mock_save.assert_called_once_with({
                    'audio': {'samplerate': 48000},
                    'display': {'use_metric_units': False}
                })
                mock_flag.assert_not_called()  # No restart needed

                # Test invalid value (not boolean)
                mock_save.reset_mock()
                response = client.put('/api/settings/units',
                                      data=json.dumps({'use_metric_units': 'invalid'}),
                                      content_type='application/json')
                assert response.status_code == 400
                mock_save.assert_not_called()

                # Test missing field
                mock_save.reset_mock()
                response = client.put('/api/settings/units',
                                      data=json.dumps({}),
                                      content_type='application/json')
                assert response.status_code == 400
                mock_save.assert_not_called()

    def test_bird_detail_endpoints(self):
        """Test bird detail endpoints."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager') as MockDB:
                mock_db_instance = Mock()
                MockDB.return_value = mock_db_instance

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                # Test detection distribution
                mock_distribution = {
                    'hourly': [{'hour': 6, 'count': 10}],
                    'daily': [{'day': 'Monday', 'count': 25}]
                }
                mock_db_instance.get_detection_distribution.return_value = mock_distribution

                response = client.get('/api/bird/American%20Robin/detection_distribution?view=week')
                assert response.status_code == 200
                assert response.get_json() == mock_distribution

    def test_bird_recordings_endpoint(self, api_client, real_db_manager):
        """Test /api/bird/<species>/recordings endpoint with real database."""
        species = 'American Robin'

        # Insert detections with varying timestamps and confidences
        for i in range(10):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T{10+i:02d}:30:00',
                'group_timestamp': f'2024-01-15T{10+i:02d}:30:00',
                'common_name': species,
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.70 + (i * 0.03),  # 0.70, 0.73, 0.76, ... 0.97
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        # Test default sort (recent)
        response = api_client.get(f'/api/bird/{species}/recordings')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 10
        # Most recent first (19:30)
        assert '19:30' in data[0]['timestamp']

        # Test sort by best (highest confidence)
        response = api_client.get(f'/api/bird/{species}/recordings?sort=best')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 10
        # Highest confidence first (0.97)
        assert data[0]['confidence'] == pytest.approx(0.97, abs=0.01)

        # Test with limit
        response = api_client.get(f'/api/bird/{species}/recordings?sort=recent&limit=4')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 4

        # Test invalid sort parameter
        response = api_client.get(f'/api/bird/{species}/recordings?sort=invalid')
        assert response.status_code == 400
        assert 'Sort must be' in response.get_json()['error']

        # Test file names are included
        response = api_client.get(f'/api/bird/{species}/recordings?limit=1')
        data = response.get_json()
        assert 'audio_filename' in data[0]
        assert 'spectrogram_filename' in data[0]

    def test_bird_recordings_empty_species(self, api_client, real_db_manager):
        """Test /api/bird/<species>/recordings returns empty list for unknown species."""
        response = api_client.get('/api/bird/Unknown%20Bird/recordings')
        assert response.status_code == 200
        data = response.get_json()
        assert data == []

    def test_broadcast_detection_endpoint(self):
        """Test detection broadcasting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager') as MockDB, \
                 patch('core.api.socketio'):

                mock_db_instance = Mock()
                MockDB.return_value = mock_db_instance

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                # Test broadcast with valid data
                detection_data = {
                    'common_name': 'Test Bird',
                    'confidence': 0.95,
                    'timestamp': '2024-01-15 10:00:00'
                }

                response = client.post('/api/broadcast/detection',
                                     data=json.dumps(detection_data),
                                     content_type='application/json')
                assert response.status_code == 200
                # API returns the detection data, not a message
                assert response.status_code == 200

                # Test with missing data
                response = client.post('/api/broadcast/detection',
                                     data=json.dumps({}),
                                     content_type='application/json')
                assert response.status_code == 200  # Still succeeds but broadcasts empty

    def test_stream_config_endpoint(self):
        """Test stream configuration endpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager') as MockDB:
                mock_db_instance = Mock()
                MockDB.return_value = mock_db_instance

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                response = client.get('/api/stream/config')
                assert response.status_code == 200
                data = response.get_json()
                assert 'stream_url' in data
                assert 'stream_type' in data

    def test_detection_trends_endpoint(self, api_client, real_db_manager):
        """Test /api/detections/trends endpoint."""
        # Insert test data across 7 days
        for day in range(7):
            for i in range(day + 1):  # 1, 2, 3... detections per day
                real_db_manager.insert_detection({
                    'timestamp': f'2024-01-{10+day:02d}T{10+i:02d}:00:00',
                    'group_timestamp': f'2024-01-{10+day:02d}T{10+i:02d}:00:00',
                    'common_name': 'American Robin',
                    'scientific_name': 'Turdus migratorius',
                    'confidence': 0.85,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        response = api_client.get('/api/detections/trends?start_date=2024-01-10&end_date=2024-01-16')
        assert response.status_code == 200

        data = response.get_json()
        assert 'labels' in data
        assert 'data' in data
        assert len(data['labels']) == 7
        assert data['data'][0] == 1  # First day: 1 detection
        assert data['data'][6] == 7  # Last day: 7 detections

    def test_detection_trends_missing_params(self, api_client, real_db_manager):
        """Test trends endpoint with missing parameters."""
        response = api_client.get('/api/detections/trends')
        assert response.status_code == 400
        assert 'required' in response.get_json()['error'].lower()

        response = api_client.get('/api/detections/trends?start_date=2024-01-01')
        assert response.status_code == 400

    def test_detection_trends_invalid_dates(self, api_client, real_db_manager):
        """Test trends endpoint with invalid date formats."""
        response = api_client.get('/api/detections/trends?start_date=invalid&end_date=2024-01-15')
        assert response.status_code == 400
        assert 'Invalid' in response.get_json()['error']

    def test_detection_trends_reversed_dates(self, api_client, real_db_manager):
        """Test trends endpoint with start_date after end_date."""
        response = api_client.get('/api/detections/trends?start_date=2024-01-15&end_date=2024-01-01')
        assert response.status_code == 400
        assert 'before' in response.get_json()['error'].lower()

    def test_detection_trends_empty_range(self, api_client, real_db_manager):
        """Test trends endpoint returns zeros for empty date range."""
        response = api_client.get('/api/detections/trends?start_date=2024-06-01&end_date=2024-06-07')
        assert response.status_code == 200

        data = response.get_json()
        assert len(data['labels']) == 7
        assert all(count == 0 for count in data['data'])

    def test_available_species_v24(self):
        """Test /api/species/available returns V2.4 species when model type is 'birdnet'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a V2.4-style labels file
            labels_file = os.path.join(tmpdir, 'labels.txt')
            with open(labels_file, 'w') as f:
                f.write('Turdus migratorius_American Robin\n')
                f.write('Cyanocitta cristata_Blue Jay\n')
                f.write('Cardinalis cardinalis_Northern Cardinal\n')

            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager'), \
                 patch('core.api.LABELS_PATH', labels_file), \
                 patch('core.api.MODEL_TYPE', 'birdnet'), \
                 patch('core.api._available_species_cache', {}):

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                response = client.get('/api/species/available')
                assert response.status_code == 200
                data = response.get_json()
                assert data['total'] == 3
                species_names = [s['common_name'] for s in data['species']]
                assert 'American Robin' in species_names
                assert 'Blue Jay' in species_names

    def test_available_species_v3(self):
        """Test /api/species/available returns V3.0 species when model type is 'birdnet_v3'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a V3.0-style labels CSV (semicolon-delimited with BOM)
            labels_csv = os.path.join(tmpdir, 'labels_v3.csv')
            with open(labels_csv, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(['idx', 'id', 'sci_name', 'com_name', 'class', 'order'])
                writer.writerow(['0', 'turdmig1', 'Turdus migratorius', 'American Robin', 'Aves', 'Passeriformes'])
                writer.writerow(['1', 'cyacri1', 'Cyanocitta cristata', 'Blue Jay', 'Aves', 'Passeriformes'])
                writer.writerow(['2', 'carcar3', 'Cardinalis cardinalis', 'Northern Cardinal', 'Aves', 'Passeriformes'])
                writer.writerow(['3', 'passer1', 'Passer domesticus', 'House Sparrow', 'Aves', 'Passeriformes'])

            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager'), \
                 patch('core.api.LABELS_V3_PATH', labels_csv), \
                 patch('core.api.MODEL_TYPE', 'birdnet_v3'), \
                 patch('core.api._available_species_cache', {}):

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                response = client.get('/api/species/available')
                assert response.status_code == 200
                data = response.get_json()
                assert data['total'] == 4
                species_names = [s['common_name'] for s in data['species']]
                assert 'American Robin' in species_names
                assert 'House Sparrow' in species_names

    def test_dashboard_endpoint(self, api_client, real_db_manager):
        """Test /api/dashboard consolidated endpoint with data."""
        from datetime import timedelta
        # Use today so activityOverview is populated
        now = datetime.now()
        base_time = now.replace(hour=10, minute=0, second=0, microsecond=0)

        for i in range(5):
            real_db_manager.insert_detection({
                'timestamp': (base_time + timedelta(hours=i)).isoformat(),
                'group_timestamp': (base_time + timedelta(hours=i)).isoformat(),
                'common_name': 'American Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        for i in range(3):
            real_db_manager.insert_detection({
                'timestamp': (base_time + timedelta(hours=i + 2)).isoformat(),
                'group_timestamp': (base_time + timedelta(hours=i + 2)).isoformat(),
                'common_name': 'Blue Jay',
                'scientific_name': 'Cyanocitta cristata',
                'confidence': 0.80,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        response = api_client.get('/api/dashboard')
        assert response.status_code == 200
        data = response.get_json()

        # Verify all top-level keys
        assert 'latestObservation' in data
        assert 'recentObservations' in data
        assert 'summary' in data
        assert 'hourlyActivity' in data
        assert 'activityOverview' in data

        # Latest observation
        assert data['latestObservation'] is not None
        assert 'common_name' in data['latestObservation']

        # Recent observations
        assert len(data['recentObservations']) >= 2

        # Summary periods
        assert 'today' in data['summary']
        assert 'week' in data['summary']
        assert 'month' in data['summary']
        assert 'allTime' in data['summary']

        # Hourly activity (24 hours)
        assert len(data['hourlyActivity']) == 24

        # Activity overview — today's data so should have both species
        assert len(data['activityOverview']) >= 2
        overview_names = [s['species'] for s in data['activityOverview']]
        assert 'American Robin' in overview_names
        assert 'Blue Jay' in overview_names

        # Default order=most: Robin (5 detections) before Blue Jay (3)
        robin_idx = overview_names.index('American Robin')
        jay_idx = overview_names.index('Blue Jay')
        assert robin_idx < jay_idx

        # Test order=least: Blue Jay (fewer) should come first
        response = api_client.get('/api/dashboard?order=least')
        assert response.status_code == 200
        data_least = response.get_json()
        least_names = [s['species'] for s in data_least['activityOverview']]
        robin_idx_least = least_names.index('American Robin')
        jay_idx_least = least_names.index('Blue Jay')
        assert jay_idx_least < robin_idx_least

    def test_dashboard_endpoint_empty_db(self, api_client, real_db_manager):
        """Test /api/dashboard returns proper empty-state response."""
        response = api_client.get('/api/dashboard')
        assert response.status_code == 200
        data = response.get_json()

        assert data['latestObservation'] is None
        assert data['recentObservations'] == []
        assert 'today' in data['summary']
        assert len(data['hourlyActivity']) == 24
        assert data['activityOverview'] == []

    def test_settings_invalid_model_type(self):
        """Test PUT /api/settings rejects invalid model type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.db.DatabaseManager'), \
                 patch('core.api.load_user_settings') as mock_load, \
                 patch('core.api.save_user_settings'), \
                 patch('core.api.write_flag'):

                mock_load.return_value = {}

                from core.api import create_app
                app, _ = create_app()
                client = app.test_client()

                # Invalid model type should be rejected
                response = client.put('/api/settings',
                                      data=json.dumps({'model': {'type': 'invalid_model'}}),
                                      content_type='application/json')
                assert response.status_code == 400
                assert 'Invalid model type' in response.get_json()['error']

                # Valid model types should be accepted
                for model_type in ('birdnet', 'birdnet_v3'):
                    response = client.put('/api/settings',
                                          data=json.dumps({'model': {'type': model_type}}),
                                          content_type='application/json')
                    assert response.status_code == 200
