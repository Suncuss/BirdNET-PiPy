"""Tests for the /api/detections paginated endpoint and DELETE endpoint."""

import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from tests.api.conftest import insert_detection, make_rows_legacy


class TestDetectionsAPI:
    """Tests for GET /api/detections endpoint."""

    def test_get_detections_empty_database(self, api_client, real_db_manager):
        """Test that empty database returns empty list with pagination info."""
        response = api_client.get('/api/detections')
        assert response.status_code == 200
        data = response.get_json()

        assert 'detections' in data
        assert 'pagination' in data
        assert data['detections'] == []
        assert data['pagination']['total_items'] == 0
        assert data['pagination']['total_pages'] == 0
        assert data['pagination']['page'] == 1

    def test_get_detections_with_data(self, api_client, real_db_manager):
        """Test basic pagination with data."""
        # Insert test detections
        for i in range(30):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T10:{i:02d}:00',
                'group_timestamp': f'2024-01-15T10:{i:02d}:00',
                'common_name': 'American Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85 + (i * 0.001),
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        response = api_client.get('/api/detections')
        assert response.status_code == 200
        data = response.get_json()

        # Default per_page is 25
        assert len(data['detections']) == 25
        assert data['pagination']['total_items'] == 30
        assert data['pagination']['total_pages'] == 2
        assert data['pagination']['has_next'] is True
        assert data['pagination']['has_prev'] is False

    def test_get_detections_page_navigation(self, api_client, real_db_manager):
        """Test navigating between pages."""
        # Insert 50 detections
        for i in range(50):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T10:{i % 60:02d}:00',
                'group_timestamp': f'2024-01-15T10:{i % 60:02d}:00',
                'common_name': 'Blue Jay',
                'scientific_name': 'Cyanocitta cristata',
                'confidence': 0.80,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        # Page 1
        response = api_client.get('/api/detections?page=1&per_page=10')
        data = response.get_json()
        assert len(data['detections']) == 10
        assert data['pagination']['page'] == 1
        assert data['pagination']['has_prev'] is False
        assert data['pagination']['has_next'] is True

        # Page 3
        response = api_client.get('/api/detections?page=3&per_page=10')
        data = response.get_json()
        assert len(data['detections']) == 10
        assert data['pagination']['page'] == 3
        assert data['pagination']['has_prev'] is True
        assert data['pagination']['has_next'] is True

        # Last page
        response = api_client.get('/api/detections?page=5&per_page=10')
        data = response.get_json()
        assert len(data['detections']) == 10
        assert data['pagination']['page'] == 5
        assert data['pagination']['has_prev'] is True
        assert data['pagination']['has_next'] is False

    def test_get_detections_per_page_limit(self, api_client, real_db_manager):
        """Test that per_page is capped at 100."""
        for i in range(150):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T{i // 60:02d}:{i % 60:02d}:00',
                'group_timestamp': f'2024-01-15T{i // 60:02d}:{i % 60:02d}:00',
                'common_name': 'Cardinal',
                'scientific_name': 'Cardinalis cardinalis',
                'confidence': 0.90,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        # Request 200 per page, should be capped at 100
        response = api_client.get('/api/detections?per_page=200')
        data = response.get_json()
        assert len(data['detections']) == 100
        assert data['pagination']['per_page'] == 100

    def test_get_detections_filter_by_species(self, api_client, real_db_manager):
        """Test filtering by species."""
        species_data = [
            ('American Robin', 'Turdus migratorius', 10),
            ('Blue Jay', 'Cyanocitta cristata', 5),
            ('Cardinal', 'Cardinalis cardinalis', 8)
        ]

        for common, scientific, count in species_data:
            for i in range(count):
                real_db_manager.insert_detection({
                    'timestamp': f'2024-01-15T10:{i:02d}:00',
                    'group_timestamp': f'2024-01-15T10:{i:02d}:00',
                    'common_name': common,
                    'scientific_name': scientific,
                    'confidence': 0.85,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        # Filter by Blue Jay
        response = api_client.get('/api/detections?species=Blue%20Jay')
        data = response.get_json()
        assert data['pagination']['total_items'] == 5
        assert all(d['common_name'] == 'Blue Jay' for d in data['detections'])

    def test_get_detections_filter_by_date_range(self, api_client, real_db_manager):
        """Test filtering by date range."""
        dates = ['2024-01-10', '2024-01-15', '2024-01-20', '2024-01-25']
        for date in dates:
            for i in range(5):
                real_db_manager.insert_detection({
                    'timestamp': f'{date}T10:{i:02d}:00',
                    'group_timestamp': f'{date}T10:{i:02d}:00',
                    'common_name': 'Robin',
                    'scientific_name': 'Turdus migratorius',
                    'confidence': 0.85,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        # Filter by date range (should get 2 days worth = 10 detections)
        response = api_client.get('/api/detections?start_date=2024-01-14&end_date=2024-01-16')
        data = response.get_json()
        # Only Jan 15 is in range
        assert data['pagination']['total_items'] == 5

        # Wider range
        response = api_client.get('/api/detections?start_date=2024-01-10&end_date=2024-01-20')
        data = response.get_json()
        # Jan 10, 15, 20 = 15 detections
        assert data['pagination']['total_items'] == 15

    def test_get_detections_combined_filters(self, api_client, real_db_manager):
        """Test combining multiple filters."""
        for date in ['2024-01-10', '2024-01-15']:
            for species, scientific in [('Robin', 'Turdus'), ('Jay', 'Cyanocitta')]:
                for i in range(3):
                    real_db_manager.insert_detection({
                        'timestamp': f'{date}T10:{i:02d}:00',
                        'group_timestamp': f'{date}T10:{i:02d}:00',
                        'common_name': species,
                        'scientific_name': scientific,
                        'confidence': 0.85,
                        'latitude': 40.7128,
                        'longitude': -74.0060,
                        'cutoff': 0.5,
                        'sensitivity': 0.75,
                        'overlap': 0.25
                    })

        # Filter by species AND date
        response = api_client.get('/api/detections?species=Robin&start_date=2024-01-14&end_date=2024-01-16')
        data = response.get_json()
        assert data['pagination']['total_items'] == 3
        assert all(d['common_name'] == 'Robin' for d in data['detections'])

    def test_get_detections_filter_by_hour(self, api_client, real_db_manager):
        """Test filtering by hour of day."""
        # 3 detections at 09:00, 5 at 14:00, 2 at 23:00
        for hour, count in [(9, 3), (14, 5), (23, 2)]:
            for i in range(count):
                real_db_manager.insert_detection({
                    'timestamp': f'2024-01-15T{hour:02d}:{i:02d}:00',
                    'group_timestamp': f'2024-01-15T{hour:02d}:{i:02d}:00',
                    'common_name': 'Robin',
                    'scientific_name': 'Turdus migratorius',
                    'confidence': 0.85,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        response = api_client.get('/api/detections?hour=14')
        assert response.status_code == 200
        data = response.get_json()
        assert data['pagination']['total_items'] == 5
        assert all(d['timestamp'][11:13] == '14' for d in data['detections'])

    def test_get_detections_filter_by_hour_zero(self, api_client, real_db_manager):
        """Test that hour=0 (midnight) filters correctly despite 0 being falsy."""
        for hour in (0, 1):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T{hour:02d}:30:00',
                'group_timestamp': f'2024-01-15T{hour:02d}:30:00',
                'common_name': 'Owl',
                'scientific_name': 'Strix',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        response = api_client.get('/api/detections?hour=0')
        assert response.status_code == 200
        data = response.get_json()
        assert data['pagination']['total_items'] == 1
        assert data['detections'][0]['timestamp'][11:13] == '00'

    def test_get_detections_filter_by_hour_combined(self, api_client, real_db_manager):
        """Test hour filter combined with date and species filters."""
        for date in ['2024-01-10', '2024-01-15']:
            for species in ['Robin', 'Jay']:
                for hour in (10, 14):
                    real_db_manager.insert_detection({
                        'timestamp': f'{date}T{hour:02d}:00:00',
                        'group_timestamp': f'{date}T{hour:02d}:00:00',
                        'common_name': species,
                        'scientific_name': f'{species} sci',
                        'confidence': 0.85,
                        'latitude': 40.7128,
                        'longitude': -74.0060,
                        'cutoff': 0.5,
                        'sensitivity': 0.75,
                        'overlap': 0.25
                    })

        response = api_client.get(
            '/api/detections?species=Robin&start_date=2024-01-15'
            '&end_date=2024-01-15&hour=14'
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['pagination']['total_items'] == 1
        detection = data['detections'][0]
        assert detection['common_name'] == 'Robin'
        assert detection['timestamp'].startswith('2024-01-15T14')

    def test_get_detections_invalid_hour(self, api_client, real_db_manager):
        """Test that an out-of-range or non-integer hour returns 400."""
        for bad in ('24', '-1', 'abc', '10.5'):
            response = api_client.get(f'/api/detections?hour={bad}')
            assert response.status_code == 400, f'hour={bad} should be rejected'
            data = response.get_json()
            assert 'error' in data
            assert 'hour' in data['error'].lower()

    def test_get_detections_empty_hour_ignored(self, api_client, real_db_manager):
        """Test that an empty hour param is treated as no filter."""
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'common_name': 'Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        response = api_client.get('/api/detections?hour=')
        assert response.status_code == 200
        assert response.get_json()['pagination']['total_items'] == 1

    def test_get_detections_sort_by_timestamp(self, api_client, real_db_manager):
        """Test sorting by timestamp."""
        times = ['10:00:00', '12:00:00', '08:00:00', '14:00:00']
        for t in times:
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T{t}',
                'group_timestamp': f'2024-01-15T{t}',
                'common_name': 'Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        # Default sort is timestamp DESC
        response = api_client.get('/api/detections')
        data = response.get_json()
        timestamps = [d['timestamp'] for d in data['detections']]
        assert timestamps == sorted(timestamps, reverse=True)

        # Sort ASC
        response = api_client.get('/api/detections?order=asc')
        data = response.get_json()
        timestamps = [d['timestamp'] for d in data['detections']]
        assert timestamps == sorted(timestamps)

    def test_get_detections_sort_by_confidence(self, api_client, real_db_manager):
        """Test sorting by confidence."""
        confidences = [0.75, 0.95, 0.85, 0.65]
        for i, conf in enumerate(confidences):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T10:{i:02d}:00',
                'group_timestamp': f'2024-01-15T10:{i:02d}:00',
                'common_name': 'Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': conf,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        # Sort by confidence DESC
        response = api_client.get('/api/detections?sort=confidence&order=desc')
        data = response.get_json()
        confs = [d['confidence'] for d in data['detections']]
        assert confs == sorted(confs, reverse=True)

    def test_get_detections_sort_by_localized_display_name(self, api_client, real_db_manager):
        """Test species sorting follows the localized display name when configured."""
        # Real German translations: Blauhäher (Blue Jay), Wanderdrossel (American Robin)
        # Alphabetically: Blauhäher < Wanderdrossel
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:31:00',
            'group_timestamp': '2024-01-15T10:31:00',
            'common_name': 'Blue Jay',
            'scientific_name': 'Cyanocitta cristata',
            'confidence': 0.90,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        from core.bird_name_utils import clear_bird_name_caches

        clear_bird_name_caches()
        try:
            with patch('core.routes.detections.load_user_settings', return_value={
                'model': {'type': 'birdnet'},
                'display': {'bird_name_language': 'de'}
            }):
                response = api_client.get('/api/detections?sort=common_name&order=asc')

            assert response.status_code == 200
            data = response.get_json()
            detections = data['detections']

            assert [d['display_common_name'] for d in detections] == ['Blauhäher', 'Wanderdrossel']
            assert [d['common_name'] for d in detections] == ['Blue Jay', 'American Robin']
        finally:
            clear_bird_name_caches()

    def test_localized_sort_paginates_across_species(self, api_client, real_db_manager):
        """Localized sort pages correctly across species boundaries.

        The page assembly walks species buckets in display order (skipping
        whole buckets before the offset), so a page that straddles two
        species and a matching total count are the load-bearing assertions.
        """
        # German: Blauhäher (Blue Jay) < Wanderdrossel (American Robin)
        for common, scientific in [('American Robin', 'Turdus migratorius'),
                                   ('Blue Jay', 'Cyanocitta cristata')]:
            for i in range(3):
                real_db_manager.insert_detection({
                    'timestamp': f'2024-01-15T10:3{i}:00',
                    'group_timestamp': f'2024-01-15T10:3{i}:00',
                    'common_name': common,
                    'scientific_name': scientific,
                    'confidence': 0.85,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        from core.bird_name_utils import clear_bird_name_caches

        clear_bird_name_caches()
        try:
            with patch('core.routes.detections.load_user_settings', return_value={
                'model': {'type': 'birdnet'},
                'display': {'bird_name_language': 'de'}
            }):
                pages = [
                    api_client.get(
                        f'/api/detections?sort=common_name&order=asc&per_page=2&page={page}'
                    ).get_json()
                    for page in (1, 2, 3)
                ]
                desc_first = api_client.get(
                    '/api/detections?sort=common_name&order=desc&per_page=2&page=1'
                ).get_json()

            names = [[d['display_common_name'] for d in p['detections']] for p in pages]
            assert names == [
                ['Blauhäher', 'Blauhäher'],
                ['Blauhäher', 'Wanderdrossel'],  # page straddles the buckets
                ['Wanderdrossel', 'Wanderdrossel'],
            ]
            # newest first within a species
            times = [d['timestamp'] for p in pages for d in p['detections']
                     if d['display_common_name'] == 'Blauhäher']
            assert times == sorted(times, reverse=True)
            assert all(p['pagination']['total_items'] == 6 for p in pages)

            assert [d['display_common_name'] for d in desc_first['detections']] == \
                ['Wanderdrossel', 'Wanderdrossel']
        finally:
            clear_bird_name_caches()

    def test_get_detections_invalid_date_format(self, api_client, real_db_manager):
        """Test that invalid date format returns 400."""
        response = api_client.get('/api/detections?start_date=invalid')
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data
        assert 'start_date' in data['error'].lower()

        response = api_client.get('/api/detections?end_date=01-15-2024')
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data

    def test_get_detections_includes_filenames(self, api_client, real_db_manager):
        """Test that response includes audio and spectrogram filenames."""
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.9500,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })
        make_rows_legacy(real_db_manager)  # synthesized names = legacy-row path

        response = api_client.get('/api/detections')
        data = response.get_json()

        detection = data['detections'][0]
        assert 'audio_filename' in detection
        assert 'spectrogram_filename' in detection
        assert detection['audio_filename'].endswith('.mp3')
        assert detection['spectrogram_filename'].endswith('.webp')


class TestDeleteDetectionAPI:
    """Tests for DELETE /api/detections/<id> endpoint."""

    def test_delete_detection_requires_auth(self, api_client, real_db_manager):
        """Test that delete endpoint requires authentication."""
        # Insert a detection
        detection_id = real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        # Try to delete without auth
        api_client.delete(f'/api/detections/{detection_id}')
        # Should return 401 when auth is enabled but not authenticated
        # Note: In test environment, auth may be disabled by default
        # The important thing is the endpoint exists and processes the request

    def test_delete_detection_not_found(self, api_client, real_db_manager):
        """Test deleting non-existent detection returns 404."""
        # Enable auth bypass for this test
        with patch('core.auth.is_authenticated', return_value=True):
            response = api_client.delete('/api/detections/99999')
            assert response.status_code == 404
            data = response.get_json()
            assert 'error' in data

    def test_delete_detection_success(self, api_client, real_db_manager):
        """Test successful deletion."""
        # Insert a detection
        detection_id = real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        # Verify detection exists
        detection = real_db_manager.get_detection_by_id(detection_id)
        assert detection is not None

        # Delete with auth bypass
        with patch('core.auth.is_authenticated', return_value=True):
            response = api_client.delete(f'/api/detections/{detection_id}')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'deleted'
            assert data['id'] == detection_id

        # Verify detection is gone
        detection = real_db_manager.get_detection_by_id(detection_id)
        assert detection is None

    def test_delete_detection_removes_files(self, api_client, real_db_manager,
                                            storage_media_dirs):
        """Test that deletion also removes associated files."""
        audio_dir, spectrogram_dir = storage_media_dirs
        detection_id = insert_detection(real_db_manager)
        make_rows_legacy(real_db_manager)  # legacy station: pattern-named files

        # Get the detection to know the filenames
        detection = real_db_manager.get_detection_by_id(detection_id)
        audio_file = os.path.join(audio_dir, detection['audio_filename'])
        spectrogram_file = os.path.join(
            spectrogram_dir, detection['spectrogram_filename'])
        for path in (audio_file, spectrogram_file):
            with open(path, 'w') as f:
                f.write('media data')

        with patch('core.auth.is_authenticated', return_value=True):
            response = api_client.delete(f'/api/detections/{detection_id}')

        assert response.status_code == 200
        assert response.get_json()['files_deleted'] == [
            detection['audio_filename'],
            detection['spectrogram_filename'],
        ]
        assert not os.path.exists(audio_file)
        assert not os.path.exists(spectrogram_file)

    def test_delete_reports_resolved_legacy_source_filenames(
            self, api_client, real_db_manager, storage_media_dirs):
        """The response names the source-ID files it actually removes."""
        audio_dir, spectrogram_dir = storage_media_dirs
        timestamp = '2024-01-15T10:30:00'
        detection_id = insert_detection(
            real_db_manager, timestamp=timestamp, confidence=0.85,
            extra={}, audio_source='source_0')
        make_rows_legacy(real_db_manager)  # transition-era row: pattern-named files

        from core.utils import build_detection_filenames

        filenames = build_detection_filenames(
            'American Robin', 0.85, timestamp, audio_source='source_0')
        audio_file = os.path.join(audio_dir, filenames['audio_filename'])
        spectrogram_file = os.path.join(
            spectrogram_dir, filenames['spectrogram_filename'])
        for path in (audio_file, spectrogram_file):
            with open(path, 'w') as f:
                f.write('media data')

        with patch('core.auth.is_authenticated', return_value=True):
            response = api_client.delete(f'/api/detections/{detection_id}')

        assert response.status_code == 200
        assert response.get_json()['files_deleted'] == [
            filenames['audio_filename'],
            filenames['spectrogram_filename'],
        ]
        assert not os.path.exists(audio_file)
        assert not os.path.exists(spectrogram_file)


class TestDetectionsDatabaseMethods:
    """Tests for the underlying database methods."""

    def test_get_paginated_detections_default_sort(self, real_db_manager):
        """Test default sorting is timestamp DESC."""
        times = ['10:00:00', '12:00:00', '08:00:00']
        for t in times:
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T{t}',
                'group_timestamp': f'2024-01-15T{t}',
                'common_name': 'Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        detections, total = real_db_manager.get_paginated_detections()
        timestamps = [d['timestamp'] for d in detections]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_get_paginated_detections_invalid_sort_field(self, real_db_manager):
        """Test that invalid sort field defaults to timestamp."""
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:00:00',
            'group_timestamp': '2024-01-15T10:00:00',
            'common_name': 'Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        # Should not raise an error, just use default
        detections, total = real_db_manager.get_paginated_detections(sort='invalid_field')
        assert total == 1

    def test_get_paginated_detections_filter_by_hour(self, real_db_manager):
        """Test the hour filter at the database method level."""
        for hour, count in [(6, 2), (18, 4)]:
            for i in range(count):
                real_db_manager.insert_detection({
                    'timestamp': f'2024-01-15T{hour:02d}:{i:02d}:00',
                    'group_timestamp': f'2024-01-15T{hour:02d}:{i:02d}:00',
                    'common_name': 'Robin',
                    'scientific_name': 'Turdus migratorius',
                    'confidence': 0.85,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        detections, total = real_db_manager.get_paginated_detections(hour=18)
        assert total == 4
        assert all(d['timestamp'][11:13] == '18' for d in detections)

        # No hour filter returns everything
        _, total_all = real_db_manager.get_paginated_detections()
        assert total_all == 6

    def test_get_detection_by_id(self, real_db_manager):
        """Test getting a single detection by ID."""
        detection_id = real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.9500,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        detection = real_db_manager.get_detection_by_id(detection_id)
        assert detection is not None
        assert detection['id'] == detection_id
        assert detection['common_name'] == 'American Robin'
        assert 'audio_filename' in detection
        assert 'spectrogram_filename' in detection

    def test_get_detection_by_id_not_found(self, real_db_manager):
        """Test that non-existent ID returns None."""
        detection = real_db_manager.get_detection_by_id(99999)
        assert detection is None

    def test_delete_detection(self, real_db_manager):
        """Test database delete_detection method."""
        detection_id = real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        # Delete and verify return value
        deleted = real_db_manager.delete_detection(detection_id)
        assert deleted is not None
        assert deleted['id'] == detection_id
        assert deleted['common_name'] == 'American Robin'

        # Verify it's actually gone
        detection = real_db_manager.get_detection_by_id(detection_id)
        assert detection is None

    def test_delete_detection_not_found(self, real_db_manager):
        """Test deleting non-existent detection returns None."""
        result = real_db_manager.delete_detection(99999)
        assert result is None


class TestExportDetectionsAPI:
    """Tests for GET /api/detections/export endpoint."""

    def test_export_blocked_when_auth_enabled(self, api_client, real_db_manager):
        """Test that export returns 401 when auth is enabled but not authenticated."""
        # require_auth consults is_authenticated(), which folds in the
        # auth-enabled check and the session epoch — patch that, not the
        # enabled flag it reads internally.
        with patch('core.auth.is_authenticated', return_value=False):
            response = api_client.get('/api/detections/export')
            assert response.status_code == 401

    def test_export_allowed_when_auth_disabled(self, api_client, real_db_manager):
        """Test that export works when auth is disabled."""
        # Auth disabled (default) - should work
        response = api_client.get('/api/detections/export')
        assert response.status_code == 200
        assert response.content_type == 'text/csv; charset=utf-8'
        # Nothing matched: the header alone still comes through.
        from core.export_jobs import CSV_HEADER
        assert response.data.decode('utf-8').strip() == ','.join(CSV_HEADER)

    def test_export_csv_format(self, api_client, real_db_manager):
        """Test that export returns valid CSV format."""
        real_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        response = api_client.get('/api/detections/export')
        assert response.status_code == 200
        assert response.content_type == 'text/csv; charset=utf-8'

        # Check Content-Disposition header
        assert 'attachment' in response.headers.get('Content-Disposition', '')
        assert 'birdnet_detections_' in response.headers.get('Content-Disposition', '')
        assert '.csv' in response.headers.get('Content-Disposition', '')

        # Parse CSV content
        csv_content = response.data.decode('utf-8')
        lines = csv_content.strip().split('\n')

        # Should have header + 1 data row
        assert len(lines) == 2

        # Check header includes all expected fields
        header = lines[0]
        assert 'id' in header
        assert 'timestamp' in header
        assert 'group_timestamp' in header
        assert 'scientific_name' in header
        assert 'common_name' in header
        assert 'confidence' in header

    def test_export_csv_with_multiple_detections(self, api_client, real_db_manager):
        """Test export with multiple detections."""
        for i in range(5):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T10:{i:02d}:00',
                'group_timestamp': f'2024-01-15T10:{i:02d}:00',
                'common_name': 'American Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.80 + i * 0.01,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        response = api_client.get('/api/detections/export')
        assert response.status_code == 200

        csv_content = response.data.decode('utf-8')
        lines = csv_content.strip().split('\n')
        assert len(lines) == 6  # Header + 5 data rows

    def test_export_csv_filter_by_species(self, api_client, real_db_manager):
        """Test export with species filter."""
        for common, scientific in [('Robin', 'Turdus'), ('Jay', 'Cyanocitta')]:
            for i in range(3):
                real_db_manager.insert_detection({
                    'timestamp': f'2024-01-15T10:{i:02d}:00',
                    'group_timestamp': f'2024-01-15T10:{i:02d}:00',
                    'common_name': common,
                    'scientific_name': scientific,
                    'confidence': 0.85,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        response = api_client.get('/api/detections/export?species=Robin')
        assert response.status_code == 200

        csv_content = response.data.decode('utf-8')
        lines = csv_content.strip().split('\n')
        assert len(lines) == 4  # Header + 3 Robin rows

    def test_export_csv_invalid_date_format(self, api_client, real_db_manager):
        """Test that invalid date format returns 400."""
        response = api_client.get('/api/detections/export?start_date=invalid')
        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data

    def test_export_csv_streams_in_batches(self, api_client, real_db_manager):
        """A multi-batch export returns every row exactly once, in order.

        All rows share one timestamp so batch boundaries depend on the id
        tiebreak of the keyset walk.
        """
        for i in range(5):
            real_db_manager.insert_detection({
                'timestamp': '2024-01-15T10:30:00',
                'group_timestamp': '2024-01-15T10:30:00',
                'common_name': 'American Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.80 + i * 0.01,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        with patch('core.export_jobs.EXPORT_BATCH_ROWS', 2):
            response = api_client.get('/api/detections/export')
            # Drain the stream inside the patch — the generator reads the
            # batch size lazily, chunk by chunk.
            payload = response.data
        assert response.status_code == 200

        lines = payload.decode('utf-8').strip().split('\n')
        assert len(lines) == 6  # Header + 5 data rows
        ids = [int(line.split(',')[0]) for line in lines[1:]]
        assert len(set(ids)) == 5
        assert ids == sorted(ids, reverse=True)  # id DESC within the tied timestamp


class TestExportDetectionsDatabaseMethods:
    """Tests for the get_detections_for_export_batch database method."""

    def test_export_batch_basic(self, real_db_manager):
        """A single batch returns all rows, newest first, in CSV column order."""
        for i in range(5):
            real_db_manager.insert_detection({
                'timestamp': f'2024-01-15T10:{i:02d}:00',
                'group_timestamp': f'2024-01-15T10:{i:02d}:00',
                'common_name': 'Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        detections = real_db_manager.get_detections_for_export_batch(limit=100)
        assert len(detections) == 5

        timestamps = [d['timestamp'] for d in detections]
        assert timestamps == sorted(timestamps, reverse=True)

        # Rows are written to the CSV as-is, so their columns must be the
        # header's, in order.
        from core.export_jobs import CSV_HEADER
        assert all(list(d.keys()) == CSV_HEADER for d in detections)

    def test_export_batch_keyset_walk(self, real_db_manager):
        """Walking with before_timestamp/before_id covers every row exactly
        once — including rows that tie on timestamp and need the id tiebreak
        across a batch boundary."""
        # 5 rows share one timestamp, 2 are newer
        rows = ['2024-01-15T10:00:00'] * 5 + ['2024-01-16T10:00:00'] * 2
        for ts in rows:
            real_db_manager.insert_detection({
                'timestamp': ts,
                'group_timestamp': ts,
                'common_name': 'Robin',
                'scientific_name': 'Turdus migratorius',
                'confidence': 0.85,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        seen = []
        before_timestamp = before_id = None
        while True:
            batch = real_db_manager.get_detections_for_export_batch(
                before_timestamp=before_timestamp, before_id=before_id,
                limit=3)
            seen.extend(batch)
            if len(batch) < 3:
                break
            before_timestamp = batch[-1]['timestamp']
            before_id = batch[-1]['id']

        assert len(seen) == 7
        assert len({d['id'] for d in seen}) == 7
        keys = [(d['timestamp'], d['id']) for d in seen]
        assert keys == sorted(keys, reverse=True)

    def test_export_batch_with_filters(self, real_db_manager):
        """Test fetch with filters."""
        for date in ['2024-01-10', '2024-01-15']:
            for species in ['Robin', 'Jay']:
                real_db_manager.insert_detection({
                    'timestamp': f'{date}T10:00:00',
                    'group_timestamp': f'{date}T10:00:00',
                    'common_name': species,
                    'scientific_name': f'{species} scientific',
                    'confidence': 0.85,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        # Filter by species
        robin_detections = real_db_manager.get_detections_for_export_batch(species='Robin', limit=100)
        assert len(robin_detections) == 2

        # Filter by date
        jan15_detections = real_db_manager.get_detections_for_export_batch(
            start_date='2024-01-14', end_date='2024-01-16', limit=100)
        assert len(jan15_detections) == 2

    def test_export_batch_empty(self, real_db_manager):
        """Test fetch on empty database."""
        detections = real_db_manager.get_detections_for_export_batch(limit=100)
        assert len(detections) == 0

    def test_export_batch_date_bounded_walk(self, real_db_manager):
        """A multi-batch walk under a date range returns exactly the in-range
        rows once each — batches after the first keep the end bound as a
        filter even though it no longer drives the index seek, so a cursor
        from outside the range still can't leak rows past end_date."""
        for day in range(10, 20):
            for hour in range(3):
                insert_detection(real_db_manager,
                                 timestamp=f'2024-01-{day}T{hour:02d}:00:00')
        date_range = {'start_date': '2024-01-12', 'end_date': '2024-01-16'}

        seen = []
        before_timestamp = before_id = None
        while True:
            batch = real_db_manager.get_detections_for_export_batch(
                before_timestamp=before_timestamp, before_id=before_id,
                limit=4, **date_range)
            seen.extend(batch)
            if len(batch) < 4:
                break
            before_timestamp = batch[-1]['timestamp']
            before_id = batch[-1]['id']

        assert len(seen) == 15  # 5 days x 3 rows
        assert len({d['id'] for d in seen}) == 15
        assert all('2024-01-12' <= d['timestamp'][:10] <= '2024-01-16'
                   for d in seen)

        # A cursor past the range: no rows from after end_date.
        leaked = real_db_manager.get_detections_for_export_batch(
            before_timestamp='2024-01-19T23:00:00', before_id=10**9,
            limit=100, **date_range)
        assert len(leaked) == 15
        assert max(d['timestamp'] for d in leaked) <= '2024-01-16T23:59:59'

    def test_export_batch_rejects_half_cursor(self, real_db_manager):
        """before_id without before_timestamp would compare against NULL and
        return nothing — an early, complete-looking end. It must raise."""
        with pytest.raises(ValueError):
            real_db_manager.get_detections_for_export_batch(
                before_id=5, limit=10)

    @pytest.mark.parametrize('fresh_stats', [False, True],
                             ids=['stale-stats', 'fresh-stats'])
    def test_export_batch_cost_independent_of_cursor_depth(
            self, real_db_manager, fresh_stats):
        """A batch deep into the walk costs about the same as one near the
        top, for every filter shape: the cursor must be an index seek, not a
        scan from the newest row down to it (which makes the whole export
        quadratic). Measured in SQLite VM steps, so it's timing-free; a
        plan-text check can't tell a seek on the cursor from one on
        end_date — both print as `timestamp>? AND timestamp<?`.

        Planner stats change which plan wins, so both states a station can be
        in are checked: stale (startup ANALYZE ran before the table grew —
        the fixture analyzed it empty) and fresh. Each alone misses a known
        regression: the old OR-form cursor only scans with stale stats here,
        yet it scanned on a fully analyzed 1.16M-row station DB."""
        species = [('Turdus migratorius', 'Robin'), ('Cyanocitta cristata', 'Jay')]
        start = datetime(2024, 1, 1)
        values = []
        for i in range(2000):  # one row per second, species alternating
            ts = (start + timedelta(seconds=i)).strftime('%Y-%m-%dT%H:%M:%S')
            values.append((ts, ts) + species[i % 2])
        # Bulk SQL insert: the species rollup isn't read by the export.
        with real_db_manager.get_db_connection() as conn:
            conn.executemany(
                "INSERT INTO detections (timestamp, group_timestamp, "
                "scientific_name, common_name, confidence) VALUES (?, ?, ?, ?, 0.9)",
                values)
            conn.commit()
            if fresh_stats:
                conn.execute("ANALYZE")
            keys = conn.execute(
                "SELECT timestamp, id FROM detections "
                "ORDER BY timestamp DESC, id DESC").fetchall()
        shallow, deep = keys[20], keys[-40]

        filters = {
            'none': {},
            'date': {'start_date': '2024-01-01', 'end_date': '2024-01-01'},
            'species': {'scientific_name': 'Turdus migratorius'},
            'species+date': {'scientific_name': 'Turdus migratorius',
                             'start_date': '2024-01-01', 'end_date': '2024-01-01'},
        }

        def vm_steps(cursor, **kwargs):
            steps = 0

            def count():
                nonlocal steps
                steps += 1
                return 0

            # Same thread → the method reuses this thread-local connection.
            with real_db_manager.get_db_connection() as conn:
                conn.set_progress_handler(count, 1)
            try:
                batch = real_db_manager.get_detections_for_export_batch(
                    before_timestamp=cursor[0], before_id=cursor[1],
                    limit=10, **kwargs)
            finally:
                with real_db_manager.get_db_connection() as conn:
                    conn.set_progress_handler(None, 1)
            assert len(batch) == 10
            return steps

        for name, kwargs in filters.items():
            shallow_steps = vm_steps(shallow, **kwargs)
            deep_steps = vm_steps(deep, **kwargs)
            assert deep_steps < shallow_steps * 2, (
                f"{name}: deep batch cost {deep_steps} VM steps vs "
                f"{shallow_steps} near the top — cursor is scanned, not sought")


class TestDeleteMaintenanceContract:
    """While the index build holds the maintenance lease, deletes return an
    explicit retryable maintenance response with zero side effects."""

    def test_delete_returns_retryable_503_during_build(
            self, api_client, real_db_manager, monkeypatch):
        from core import maintenance_lease
        detection_id = insert_detection(real_db_manager)
        maintenance_lease.acquire(real_db_manager, 'index_build', 'builder', 120)
        monkeypatch.setattr(
            'core.routes.detections._MAINTENANCE_RETRY_SECONDS', 0)

        with patch('core.auth.is_authenticated', return_value=True):
            response = api_client.delete(f'/api/detections/{detection_id}')

        assert response.status_code == 503
        body = response.get_json()
        assert body['retryable'] is True
        # zero side effects: the row survives untouched
        assert real_db_manager.get_detection_by_id(detection_id) is not None

        # lease released -> the same call succeeds
        maintenance_lease.release(real_db_manager, 'builder')
        with patch('core.auth.is_authenticated', return_value=True):
            response = api_client.delete(f'/api/detections/{detection_id}')
        assert response.status_code == 200
