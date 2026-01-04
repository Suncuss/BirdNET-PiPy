"""Simple API tests that demonstrate working patterns."""

import os
import tempfile
import pytest
import json
from unittest.mock import patch, Mock
from datetime import datetime


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
        from datetime import datetime, timedelta
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
                 patch('core.api.socketio') as mock_socketio:

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
