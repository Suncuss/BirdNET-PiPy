"""
Basic database operations tests.
Tests for fundamental CRUD operations and simple queries.
"""
from datetime import datetime, timedelta


class TestDatabaseBasicOperations:
    """Tests for basic database operations."""

    def test_insert_and_retrieve(self, test_db_manager):
        """Test basic insert and retrieve operations."""
        # Insert a detection with ISO format timestamp
        detection = {
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.95,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        }

        row_id = test_db_manager.insert_detection(detection)
        assert isinstance(row_id, int)

        # Retrieve
        results = test_db_manager.get_latest_detections(1)
        assert len(results) == 1
        assert results[0]['common_name'] == 'American Robin'

    def test_get_latest_detections_file_names(self, test_db_manager):
        """Test that get_latest_detections() adds correct file names."""
        detection = {
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:45',
            'scientific_name': 'Cyanocitta cristata',
            'common_name': 'Blue Jay',
            'confidence': 0.876,  # Will round to 88
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        }
        test_db_manager.insert_detection(detection)

        results = test_db_manager.get_latest_detections(1)
        assert len(results) == 1

        result = results[0]
        # Time uses dashes for filesystem compatibility (Windows doesn't allow colons)
        assert result['bird_song_file_name'] == 'Blue_Jay_88_2024-01-15-birdnet-10-30-45.mp3'
        assert result['spectrogram_file_name'] == 'Blue_Jay_88_2024-01-15-birdnet-10-30-45.webp'

    def test_get_detections_by_date_range(self, test_db_manager):
        """Test date range filtering with proper date handling."""
        base_date = datetime(2024, 1, 15)

        # Insert detections across multiple days
        for days_offset in [-2, -1, 0, 1, 2]:
            detection_time = base_date + timedelta(days=days_offset, hours=12)
            detection = {
                'timestamp': detection_time.isoformat(),
                'group_timestamp': detection_time.isoformat(),
                'scientific_name': 'Turdus migratorius',
                'common_name': 'American Robin',
                'confidence': 0.8,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        # Query for 3 days centered on base_date
        start_date = '2024-01-14'
        end_date = '2024-01-16'

        results = test_db_manager.get_detections_by_date_range(start_date, end_date)

        # Should get 3 detections
        assert len(results) == 3

    def test_get_hourly_activity(self, test_db_manager):
        """Test hourly activity returns 24 hours."""
        test_date = '2024-01-15'

        # Insert detections at specific hours
        for hour in [0, 6, 12, 18, 23]:
            detection = {
                'timestamp': f'2024-01-15T{hour:02d}:00:00',
                'group_timestamp': f'2024-01-15T{hour:02d}:00:00',
                'scientific_name': 'Turdus migratorius',
                'common_name': 'American Robin',
                'confidence': 0.8,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        result = test_db_manager.get_hourly_activity(test_date)

        # Should always return 24 entries
        assert len(result) == 24
        assert result[0]['hour'] == '00:00'
        assert result[0]['count'] == 1
        assert result[1]['hour'] == '01:00'
        assert result[1]['count'] == 0

    def test_get_summary_stats(self, test_db_manager):
        """Test summary statistics structure."""
        # Insert some detections
        base_time = datetime(2024, 1, 15, 10, 0, 0)

        # Common bird
        for i in range(10):
            detection = {
                'timestamp': (base_time - timedelta(hours=i)).isoformat(),
                'group_timestamp': (base_time - timedelta(hours=i)).isoformat(),
                'scientific_name': 'Turdus migratorius',
                'common_name': 'American Robin',
                'confidence': 0.8,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        # Rare bird
        rare_detection = {
            'timestamp': (base_time - timedelta(days=1)).isoformat(),
            'group_timestamp': (base_time - timedelta(days=1)).isoformat(),
            'scientific_name': 'Setophaga citrina',
            'common_name': 'Hooded Warbler',
            'confidence': 0.7,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        }
        test_db_manager.insert_detection(rare_detection)

        stats = test_db_manager.get_summary_stats()

        # Check structure
        assert 'totalObservations' in stats
        assert 'uniqueSpecies' in stats
        assert stats['totalObservations'] == 11
        assert stats['uniqueSpecies'] == 2
        assert stats['mostCommonBird'] == 'American Robin'
        assert stats['rarestBird'] == 'Hooded Warbler'

    def test_get_bird_details(self, test_db_manager):
        """Test bird details with proper data."""
        species = 'American Robin'
        scientific = 'Turdus migratorius'

        # Insert detections across multiple months
        for month in [1, 2, 3, 6, 9, 12]:
            detection = {
                'timestamp': f'2024-{month:02d}-15T14:30:00',
                'group_timestamp': f'2024-{month:02d}-15T14:30:00',
                'scientific_name': scientific,
                'common_name': species,
                'confidence': 0.80,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        details = test_db_manager.get_bird_details(species)

        assert details is not None
        assert details['common_name'] == species
        assert details['scientific_name'] == scientific
        assert details['total_visits'] == 6
        # Check seasonality - 6 months should be Multi-season
        assert details['seasonality'] in ['Multi-season', 'Year-round']

    def test_get_bird_recordings_sort_best(self, test_db_manager):
        """Test get_bird_recordings sorted by confidence (best)."""
        species = 'Blue Jay'

        # Insert detections with varying confidences
        confidences = [0.95, 0.88, 0.76, 0.92, 0.81]

        for i, conf in enumerate(confidences):
            detection = {
                'timestamp': f'2024-01-15T10:{30+i:02d}:00',
                'group_timestamp': f'2024-01-15T10:{30+i:02d}:00',
                'scientific_name': 'Cyanocitta cristata',
                'common_name': species,
                'confidence': conf,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        # Test sort by best (confidence DESC) with limit
        recordings = test_db_manager.get_bird_recordings(species, sort='best', limit=3)

        # Should get top 3 by confidence
        assert len(recordings) == 3
        assert recordings[0]['confidence'] == 0.95
        assert recordings[1]['confidence'] == 0.92
        assert recordings[2]['confidence'] == 0.88

        # Check file names
        assert 'audio_filename' in recordings[0]
        assert 'spectrogram_filename' in recordings[0]

    def test_get_bird_recordings_sort_recent(self, test_db_manager):
        """Test get_bird_recordings sorted by timestamp (recent)."""
        species = 'Blue Jay'

        # Insert detections with varying timestamps
        for i in range(5):
            detection = {
                'timestamp': f'2024-01-15T{10+i:02d}:30:00',
                'group_timestamp': f'2024-01-15T{10+i:02d}:30:00',
                'scientific_name': 'Cyanocitta cristata',
                'common_name': species,
                'confidence': 0.80 + (i * 0.02),
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        # Test sort by recent (timestamp DESC) - default
        recordings = test_db_manager.get_bird_recordings(species, sort='recent', limit=3)

        # Should get 3 most recent by timestamp (14:30, 13:30, 12:30)
        assert len(recordings) == 3
        assert '14:30' in recordings[0]['timestamp']
        assert '13:30' in recordings[1]['timestamp']
        assert '12:30' in recordings[2]['timestamp']

    def test_get_bird_recordings_no_limit(self, test_db_manager):
        """Test get_bird_recordings without limit returns all."""
        species = 'Blue Jay'

        # Insert 5 detections
        for i in range(5):
            detection = {
                'timestamp': f'2024-01-15T10:{30+i:02d}:00',
                'group_timestamp': f'2024-01-15T10:{30+i:02d}:00',
                'scientific_name': 'Cyanocitta cristata',
                'common_name': species,
                'confidence': 0.80,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        # Test without limit - should return all
        recordings = test_db_manager.get_bird_recordings(species, sort='recent', limit=None)
        assert len(recordings) == 5

    def test_get_bird_recordings_with_limit(self, test_db_manager):
        """Test get_bird_recordings with limit parameter."""
        species = 'Blue Jay'

        # Insert 10 detections
        for i in range(10):
            detection = {
                'timestamp': f'2024-01-15T10:{30+i:02d}:00',
                'group_timestamp': f'2024-01-15T10:{30+i:02d}:00',
                'scientific_name': 'Cyanocitta cristata',
                'common_name': species,
                'confidence': 0.80,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        # Test with limit=4
        recordings = test_db_manager.get_bird_recordings(species, sort='recent', limit=4)
        assert len(recordings) == 4

        # Test with limit=16
        recordings = test_db_manager.get_bird_recordings(species, sort='recent', limit=16)
        assert len(recordings) == 10  # Only 10 exist

    def test_get_all_unique_species(self, test_db_manager):
        """Test getting all unique species."""
        species_list = [
            ('American Robin', 'Turdus migratorius'),
            ('Blue Jay', 'Cyanocitta cristata'),
            ('Northern Cardinal', 'Cardinalis cardinalis')
        ]

        # Insert multiple detections of each species
        for common, scientific in species_list:
            for i in range(3):
                detection = {
                    'timestamp': f'2024-01-15T{10+i:02d}:00:00',
                    'group_timestamp': f'2024-01-15T{10+i:02d}:00:00',
                    'scientific_name': scientific,
                    'common_name': common,
                    'confidence': 0.8,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                }
                test_db_manager.insert_detection(detection)

        result = test_db_manager.get_all_unique_species()

        # Should get 3 unique species
        assert len(result) == 3
        assert all('common_name' in s and 'scientific_name' in s for s in result)

        # Check alphabetical order
        names = [s['common_name'] for s in result]
        assert names == sorted(names)
