
"""
Additional database query method tests for coverage.
"""
from datetime import datetime, timedelta


class TestDatabaseQueryMethods:
    """Additional tests for better coverage."""

    def test_get_activity_overview(self, test_db_manager):
        """Test get_activity_overview() method."""
        test_date = '2024-01-15'

        # Insert detections for different species at different hours
        species_hours = {
            'American Robin': [6, 7, 8, 17, 18],
            'Blue Jay': [9, 10, 11, 12],
            'Northern Cardinal': [6, 12, 18]
        }

        for species, hours in species_hours.items():
            for hour in hours:
                detection = {
                    'timestamp': f'2024-01-15T{hour:02d}:00:00',
                    'group_timestamp': f'2024-01-15T{hour:02d}:00:00',
                    'scientific_name': f'{species}_scientific',
                    'common_name': species,
                    'confidence': 0.8,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                }
                test_db_manager.insert_detection(detection)

        overview = test_db_manager.get_activity_overview(test_date, num_species=2)

        # Should get top 2 species
        assert len(overview) == 2
        assert overview[0]['species'] == 'American Robin'  # 5 detections
        assert overview[0]['totalObservations'] == 5
        assert len(overview[0]['hourlyActivity']) == 24

        # Check hourly activity array
        assert overview[0]['hourlyActivity'][6] == 1  # 6 AM
        assert overview[0]['hourlyActivity'][0] == 0  # Midnight

    def test_get_activity_overview_both(self, test_db_manager):
        """Test get_activity_overview_both() returns correct results for both orders."""
        test_date = '2024-01-15'

        # Insert detections for different species at different hours
        species_hours = {
            'American Robin': [6, 7, 8, 17, 18],      # 5 detections
            'Blue Jay': [9, 10, 11, 12],               # 4 detections
            'Northern Cardinal': [6, 12, 18],           # 3 detections
        }

        for species, hours in species_hours.items():
            for hour in hours:
                detection = {
                    'timestamp': f'2024-01-15T{hour:02d}:00:00',
                    'group_timestamp': f'2024-01-15T{hour:02d}:00:00',
                    'scientific_name': f'{species}_scientific',
                    'common_name': species,
                    'confidence': 0.8,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                }
                test_db_manager.insert_detection(detection)

        result = test_db_manager.get_activity_overview_both(test_date, num_species=2)

        # Should return dict with 'most' and 'least' keys
        assert 'most' in result
        assert 'least' in result

        # 'most' order: top 2 by totalObservations DESC
        assert len(result['most']) == 2
        assert result['most'][0]['species'] == 'American Robin'
        assert result['most'][0]['totalObservations'] == 5
        assert result['most'][1]['species'] == 'Blue Jay'
        assert result['most'][1]['totalObservations'] == 4

        # 'least' order: bottom 2 by totalObservations ASC
        assert len(result['least']) == 2
        assert result['least'][0]['species'] == 'Northern Cardinal'
        assert result['least'][0]['totalObservations'] == 3
        assert result['least'][1]['species'] == 'Blue Jay'
        assert result['least'][1]['totalObservations'] == 4

        # Verify hourly activity arrays have correct length
        assert len(result['most'][0]['hourlyActivity']) == 24
        assert len(result['least'][0]['hourlyActivity']) == 24

        # Verify specific hourly data
        assert result['most'][0]['hourlyActivity'][6] == 1  # Robin at 6 AM
        assert result['most'][0]['hourlyActivity'][0] == 0  # Robin at midnight

    def test_get_activity_overview_both_empty_db(self, test_db_manager):
        """Test get_activity_overview_both() on empty database."""
        result = test_db_manager.get_activity_overview_both('2024-01-15')

        assert result == {'most': [], 'least': []}

    def test_get_species_sightings_most_frequent(self, test_db_manager):
        """Test get_species_sightings() for most frequent species."""
        # Insert varying numbers of detections for different species
        species_counts = [
            ('American Robin', 10),
            ('Blue Jay', 5),
            ('Northern Cardinal', 2),
            ('Hooded Warbler', 1)
        ]

        base_time = datetime(2024, 1, 15, 10, 0, 0)
        for species, count in species_counts:
            for i in range(count):
                detection = {
                    'timestamp': (base_time - timedelta(hours=i)).isoformat(),
                    'group_timestamp': (base_time - timedelta(hours=i)).isoformat(),
                    'scientific_name': f'{species}_scientific',
                    'common_name': species,
                    'confidence': 0.8,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                }
                test_db_manager.insert_detection(detection)

        # Get most frequent
        most_frequent = test_db_manager.get_species_sightings(limit=2, most_frequent=True)

        assert len(most_frequent) == 2
        # Should return the most recent detection of the most frequent species
        assert most_frequent[0]['common_name'] == 'American Robin'
        assert most_frequent[1]['common_name'] == 'Blue Jay'

    def test_get_species_sightings_rarest(self, test_db_manager):
        """Test get_species_sightings() for rarest species."""
        # Use same data as above
        species_counts = [
            ('American Robin', 10),
            ('Blue Jay', 5),
            ('Northern Cardinal', 2),
            ('Hooded Warbler', 1)
        ]

        base_time = datetime(2024, 1, 15, 10, 0, 0)
        for species, count in species_counts:
            for i in range(count):
                detection = {
                    'timestamp': (base_time - timedelta(hours=i)).isoformat(),
                    'group_timestamp': (base_time - timedelta(hours=i)).isoformat(),
                    'scientific_name': f'{species}_scientific',
                    'common_name': species,
                    'confidence': 0.8,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                }
                test_db_manager.insert_detection(detection)

        # Get rarest
        rarest = test_db_manager.get_species_sightings(limit=2, most_frequent=False)

        assert len(rarest) == 2
        # Should return the most recent detection of the rarest species
        assert rarest[0]['common_name'] == 'Hooded Warbler'
        assert rarest[1]['common_name'] == 'Northern Cardinal'

    def test_get_detection_distribution_week_view(self, test_db_manager):
        """Test get_detection_distribution() for week view."""
        # Use Jan 14, 2024 (Sunday) as anchor - this is the start of the week
        anchor_date = '2024-01-14'  # Sunday
        species = 'American Robin'

        # Insert detections across the week (Sun Jan 14 - Sat Jan 20)
        for days_offset in range(7):
            detection_date = datetime(2024, 1, 14) + timedelta(days=days_offset)
            detection = {
                'timestamp': detection_date.isoformat(),
                'group_timestamp': detection_date.isoformat(),
                'scientific_name': 'Turdus migratorius',
                'common_name': species,
                'confidence': 0.8,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        result = test_db_manager.get_detection_distribution(species, 'week', anchor_date)

        assert 'labels' in result
        assert 'data' in result
        assert len(result['labels']) == 7
        assert len(result['data']) == 7

        # Check labels format (Sunday-start week to match JavaScript's getDay())
        assert result['labels'][0].startswith('Sun')
        assert result['labels'][6].startswith('Sat')

        # Each day should have 1 detection
        assert all(count == 1 for count in result['data'])

    def test_get_detection_distribution_month_view(self, test_db_manager):
        """Test get_detection_distribution() for month view."""
        anchor_date = '2024-01-15'
        species = 'American Robin'

        # Insert detections on specific days
        for day in [1, 5, 10, 15, 20, 25, 31]:
            detection = {
                'timestamp': f'2024-01-{day:02d}T12:00:00',
                'group_timestamp': f'2024-01-{day:02d}T12:00:00',
                'scientific_name': 'Turdus migratorius',
                'common_name': species,
                'confidence': 0.8,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        result = test_db_manager.get_detection_distribution(species, 'month', anchor_date)

        assert len(result['labels']) == 31  # January has 31 days
        assert result['data'][0] == 1  # Day 1
        assert result['data'][4] == 1  # Day 5
        assert result['data'][2] == 0  # Day 3 (no detection)

    def test_get_detection_distribution_year_view(self, test_db_manager):
        """Test get_detection_distribution() for year view."""
        anchor_date = '2024-06-15'
        species = 'American Robin'

        # Insert detections in different months
        for month in [1, 3, 6, 9, 12]:
            detection = {
                'timestamp': f'2024-{month:02d}-15T12:00:00',
                'group_timestamp': f'2024-{month:02d}-15T12:00:00',
                'scientific_name': 'Turdus migratorius',
                'common_name': species,
                'confidence': 0.8,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            }
            test_db_manager.insert_detection(detection)

        result = test_db_manager.get_detection_distribution(species, 'year', anchor_date)

        assert len(result['labels']) == 12
        assert result['labels'] == ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        assert result['data'][0] == 1  # January
        assert result['data'][1] == 0  # February (no detection)
        assert result['data'][2] == 1  # March

    def test_empty_database_queries(self, test_db_manager):
        """Test various queries on empty database."""
        # Test methods that should handle empty database gracefully
        assert test_db_manager.get_latest_detections(10) == []
        assert test_db_manager.get_all_unique_species() == []

        # Test summary stats on empty database
        stats = test_db_manager.get_summary_stats()
        assert stats['totalObservations'] == 0
        assert stats['uniqueSpecies'] == 0
        assert stats['mostActiveHour'] == 'N/A'
        assert stats['mostCommonBird'] == 'N/A'
        assert stats['rarestBird'] == 'N/A'

    def test_get_latest_detections_same_species_same_group(self, test_db_manager):
        """Test get_latest_detections with multiple detections of same species in same group_timestamp.

        This tests a bug where the old query using WHERE (id, confidence) IN (SELECT id, MAX(confidence)...)
        would return empty results because SQLite returns arbitrary id values for non-aggregated columns
        in GROUP BY queries.
        """
        # Insert multiple detections of SAME species in SAME group_timestamp
        # This simulates BirdNET detecting the same bird multiple times in one recording
        detections = [
            {'timestamp': '2024-01-15T10:30:45', 'group_timestamp': '2024-01-15T10:30:00',
             'common_name': 'Brown-headed Nuthatch', 'scientific_name': 'Sitta pusilla',
             'confidence': 0.50},  # Lower confidence
            {'timestamp': '2024-01-15T10:30:47', 'group_timestamp': '2024-01-15T10:30:00',
             'common_name': 'Brown-headed Nuthatch', 'scientific_name': 'Sitta pusilla',
             'confidence': 0.95},  # HIGHEST confidence - should be returned
            {'timestamp': '2024-01-15T10:30:49', 'group_timestamp': '2024-01-15T10:30:00',
             'common_name': 'Brown-headed Nuthatch', 'scientific_name': 'Sitta pusilla',
             'confidence': 0.75},  # Medium confidence
        ]

        for det in detections:
            test_db_manager.insert_detection({
                'timestamp': det['timestamp'],
                'group_timestamp': det['group_timestamp'],
                'scientific_name': det['scientific_name'],
                'common_name': det['common_name'],
                'confidence': det['confidence'],
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        # Query should return exactly 1 result (the highest confidence detection)
        results = test_db_manager.get_latest_detections(limit=10)

        assert len(results) == 1, f"Expected 1 result (highest conf per group), got {len(results)}"
        assert results[0]['common_name'] == 'Brown-headed Nuthatch'
        assert results[0]['confidence'] == 0.95, f"Expected highest confidence 0.95, got {results[0]['confidence']}"

    def test_get_latest_detections_single_detection_fresh_db(self, test_db_manager):
        """Test get_latest_detections with a single detection (fresh database scenario).

        This tests the edge case where the database has just one detection,
        ensuring it's properly returned.
        """
        test_db_manager.insert_detection({
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Sitta pusilla',
            'common_name': 'Brown-headed Nuthatch',
            'confidence': 0.87,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        results = test_db_manager.get_latest_detections(limit=1)

        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        assert results[0]['common_name'] == 'Brown-headed Nuthatch'
        assert results[0]['confidence'] == 0.87


class TestDailyDetectionCounts:
    """Tests for get_daily_detection_counts() method."""

    def test_basic_daily_counts(self, test_db_manager):
        """Test basic daily detection counting."""
        # Insert detections across multiple days
        days_data = [
            ('2024-01-10', 5),
            ('2024-01-11', 3),
            ('2024-01-12', 0),  # No detections (won't insert)
            ('2024-01-13', 8),
        ]

        for date, count in days_data:
            for i in range(count):
                test_db_manager.insert_detection({
                    'timestamp': f'{date}T{10+i:02d}:00:00',
                    'group_timestamp': f'{date}T{10+i:02d}:00:00',
                    'scientific_name': 'Turdus migratorius',
                    'common_name': 'American Robin',
                    'confidence': 0.8,
                    'latitude': 40.7128,
                    'longitude': -74.0060,
                    'cutoff': 0.5,
                    'sensitivity': 0.75,
                    'overlap': 0.25
                })

        result = test_db_manager.get_daily_detection_counts('2024-01-10', '2024-01-13')

        assert 'labels' in result
        assert 'data' in result
        assert len(result['labels']) == 4
        assert result['labels'] == ['2024-01-10', '2024-01-11', '2024-01-12', '2024-01-13']
        assert result['data'] == [5, 3, 0, 8]

    def test_empty_range(self, test_db_manager):
        """Test with no detections in range."""
        result = test_db_manager.get_daily_detection_counts('2024-06-01', '2024-06-07')

        assert len(result['labels']) == 7
        assert all(count == 0 for count in result['data'])

    def test_single_day(self, test_db_manager):
        """Test single day range."""
        test_db_manager.insert_detection({
            'timestamp': '2024-01-15T12:00:00',
            'group_timestamp': '2024-01-15T12:00:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.8,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        })

        result = test_db_manager.get_daily_detection_counts('2024-01-15', '2024-01-15')

        assert len(result['labels']) == 1
        assert result['labels'] == ['2024-01-15']
        assert result['data'] == [1]

    def test_long_range(self, test_db_manager):
        """Test 365-day range returns correct number of days."""
        result = test_db_manager.get_daily_detection_counts('2024-01-01', '2024-12-31')

        # 2024 is a leap year: 366 days
        assert len(result['labels']) == 366
        assert len(result['data']) == 366

    def test_multiple_species_combined(self, test_db_manager):
        """Test that counts combine all species."""
        # Insert different species on same day
        for species in ['American Robin', 'Blue Jay', 'Cardinal']:
            test_db_manager.insert_detection({
                'timestamp': '2024-01-15T12:00:00',
                'group_timestamp': '2024-01-15T12:00:00',
                'scientific_name': f'{species}_scientific',
                'common_name': species,
                'confidence': 0.8,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25
            })

        result = test_db_manager.get_daily_detection_counts('2024-01-15', '2024-01-15')

        assert result['data'] == [3]  # All species combined
