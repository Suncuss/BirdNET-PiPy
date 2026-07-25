
"""
Additional database query method tests for coverage.
"""
from datetime import datetime, timedelta

import pytest

from core.timezone_service import local_now


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

        overview = test_db_manager.get_activity_overview(test_date)

        # Should get all 3 species
        assert len(overview) == 3
        assert overview[0]['species'] == 'American Robin'  # 5 detections
        assert overview[0]['totalObservations'] == 5
        assert len(overview[0]['hourlyActivity']) == 24

        # Check hourly activity array
        assert overview[0]['hourlyActivity'][6] == 1  # 6 AM
        assert overview[0]['hourlyActivity'][0] == 0  # Midnight

    def test_day_windows_are_half_open(self, test_db_manager):
        """A detection at exactly the next midnight belongs to the next day —
        it must not appear in the previous day's hourly activity or overview."""
        base = {
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.8,
            'latitude': 40.7128, 'longitude': -74.0060,
            'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
        }
        for ts in ('2024-01-15T23:59:59', '2024-01-16T00:00:00'):
            test_db_manager.insert_detection(
                dict(base, timestamp=ts, group_timestamp=ts))

        hourly = test_db_manager.get_hourly_activity('2024-01-15')
        assert sum(entry['count'] for entry in hourly) == 1
        assert hourly[23]['count'] == 1

        overview = test_db_manager.get_activity_overview('2024-01-15')
        assert overview[0]['totalObservations'] == 1

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

    def test_get_species_sightings_one_row_per_species_on_tied_timestamp(
        self, test_db_manager
    ):
        """Two detections of one species sharing the latest timestamp must
        still yield exactly one sighting row."""
        for _ in range(2):
            test_db_manager.insert_detection({
                'timestamp': '2024-01-15T10:00:00',
                'group_timestamp': '2024-01-15T10:00:00',
                'scientific_name': 'Turdus migratorius',
                'common_name': 'American Robin',
                'confidence': 0.8,
                'latitude': 40.7128,
                'longitude': -74.0060,
                'cutoff': 0.5,
                'sensitivity': 0.75,
                'overlap': 0.25,
            })

        result = test_db_manager.get_species_sightings(limit=10, most_frequent=True)

        robins = [r for r in result if r['common_name'] == 'American Robin']
        assert len(robins) == 1

    def test_get_detection_distribution_day_view(self, test_db_manager):
        """Day view buckets by hour; detections on adjacent days stay out."""
        species = 'American Robin'
        for ts in ('2024-01-15T06:15:00', '2024-01-15T06:45:00',
                   '2024-01-15T18:00:00', '2024-01-16T06:00:00'):
            test_db_manager.insert_detection({
                'timestamp': ts, 'group_timestamp': ts,
                'scientific_name': 'Turdus migratorius',
                'common_name': species, 'confidence': 0.8,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
            })

        result = test_db_manager.get_detection_distribution(
            species, 'day', '2024-01-15')

        assert len(result['labels']) == 24
        assert result['data'][6] == 2
        assert result['data'][18] == 1
        assert sum(result['data']) == 3  # next-day detection excluded

    def test_get_detection_distribution_6month_view(self, test_db_manager):
        """Second-half anchor covers Jul-Dec; first-half months excluded."""
        species = 'American Robin'
        for month in (3, 7, 9, 12):
            ts = f'2024-{month:02d}-10T12:00:00'
            test_db_manager.insert_detection({
                'timestamp': ts, 'group_timestamp': ts,
                'scientific_name': 'Turdus migratorius',
                'common_name': species, 'confidence': 0.8,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
            })

        result = test_db_manager.get_detection_distribution(
            species, '6month', '2024-08-15')

        assert result['labels'] == ['Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        assert result['data'] == [1, 0, 1, 0, 0, 1]  # March excluded

    def test_get_detection_distribution_scientific_name_path(self, test_db_manager):
        """The preferred scientific_name filter merges rows across differing
        English common names for the same species."""
        for common in ('Eurasian Blackbird', 'Common Blackbird'):
            ts = '2024-01-15T08:00:00'
            test_db_manager.insert_detection({
                'timestamp': ts, 'group_timestamp': ts,
                'scientific_name': 'Turdus merula',
                'common_name': common, 'confidence': 0.8,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
            })

        result = test_db_manager.get_detection_distribution(
            None, 'day', '2024-01-15', scientific_name='Turdus merula')

        assert result['data'][8] == 2

    def test_get_detection_distribution_invalid_view(self, test_db_manager):
        with pytest.raises(ValueError, match="Invalid view"):
            test_db_manager.get_detection_distribution(
                'American Robin', 'hourly', '2024-01-15')

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

    def test_get_latest_detections_unique_returns_one_per_species(self, test_db_manager):
        """Test unique=True returns one row per species, most recent of each."""
        base_detections = [
            ('American Robin', '2024-01-15T10:00:00', '2024-01-15T10:00:00'),
            ('American Robin', '2024-01-15T11:00:00', '2024-01-15T11:00:00'),
            ('American Robin', '2024-01-15T12:00:00', '2024-01-15T12:00:00'),
            ('Blue Jay', '2024-01-15T09:00:00', '2024-01-15T09:00:00'),
            ('Blue Jay', '2024-01-15T13:00:00', '2024-01-15T13:00:00'),
            ('Northern Cardinal', '2024-01-15T08:00:00', '2024-01-15T08:00:00'),
            ('Northern Cardinal', '2024-01-15T14:00:00', '2024-01-15T14:00:00'),
            ('Northern Cardinal', '2024-01-15T15:00:00', '2024-01-15T15:00:00'),
            ('Hooded Warbler', '2024-01-15T07:00:00', '2024-01-15T07:00:00'),
            ('Hooded Warbler', '2024-01-15T16:00:00', '2024-01-15T16:00:00'),
        ]
        for species, ts, gts in base_detections:
            test_db_manager.insert_detection({
                'timestamp': ts, 'group_timestamp': gts,
                'scientific_name': f'{species}_scientific',
                'common_name': species, 'confidence': 0.8,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25
            })

        results = test_db_manager.get_latest_detections(limit=15, unique=True)

        assert len(results) == 4
        species_seen = [r['common_name'] for r in results]
        assert len(set(species_seen)) == 4  # each species exactly once

        # Ordered by timestamp DESC — Hooded Warbler 16:00 is most recent
        assert results[0]['common_name'] == 'Hooded Warbler'
        assert results[0]['timestamp'] == '2024-01-15T16:00:00'

        # Each result should be the most recent detection of that species
        expected_latest = {
            'American Robin': '2024-01-15T12:00:00',
            'Blue Jay': '2024-01-15T13:00:00',
            'Northern Cardinal': '2024-01-15T15:00:00',
            'Hooded Warbler': '2024-01-15T16:00:00',
        }
        for r in results:
            assert r['timestamp'] == expected_latest[r['common_name']]

    def test_get_latest_detections_unique_respects_limit(self, test_db_manager):
        """Test unique=True with limit returns at most limit results."""
        for i, species in enumerate(['Robin', 'Jay', 'Cardinal', 'Warbler', 'Sparrow']):
            test_db_manager.insert_detection({
                'timestamp': f'2024-01-15T{10+i:02d}:00:00',
                'group_timestamp': f'2024-01-15T{10+i:02d}:00:00',
                'scientific_name': f'{species}_sci',
                'common_name': species, 'confidence': 0.8,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25
            })

        results = test_db_manager.get_latest_detections(limit=3, unique=True)
        assert len(results) == 3

    def test_get_latest_detections_unique_survives_dominant_species(
        self, test_db_manager
    ):
        """A species dominating recent history must not crowd other species
        out of the unique-latest list (served off the species rollup — the
        old prefetch-window approach failed exactly this scenario)."""
        base_time = datetime(2024, 1, 20, 12, 0, 0)

        for i in range(600):
            timestamp = (base_time - timedelta(seconds=i)).isoformat()
            test_db_manager.insert_detection({
                'timestamp': timestamp,
                'group_timestamp': timestamp,
                'scientific_name': 'Dominantus noisii',
                'common_name': 'Dominant Bird',
                'confidence': 0.8,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
            })

        for i, species in enumerate([
            'Robin', 'Jay', 'Cardinal', 'Warbler', 'Sparrow', 'Nuthatch',
        ]):
            timestamp = (base_time - timedelta(days=1, seconds=i)).isoformat()
            test_db_manager.insert_detection({
                'timestamp': timestamp,
                'group_timestamp': timestamp,
                'scientific_name': f'{species}_sci',
                'common_name': species,
                'confidence': 0.8,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
            })

        results = test_db_manager.get_latest_detections(limit=7, unique=True)

        assert len(results) == 7
        assert {row['common_name'] for row in results} == {
            'Dominant Bird', 'Robin', 'Jay', 'Cardinal',
            'Warbler', 'Sparrow', 'Nuthatch',
        }
        # Newest species first, one row per species
        assert results[0]['common_name'] == 'Dominant Bird'

    def test_get_latest_detections_unique_vs_default(self, test_db_manager):
        """Test unique=True collapses same species, default does not."""
        for i in range(3):
            test_db_manager.insert_detection({
                'timestamp': f'2024-01-15T{10+i:02d}:00:00',
                'group_timestamp': f'2024-01-15T{10+i:02d}:00:00',
                'scientific_name': 'Turdus migratorius',
                'common_name': 'American Robin', 'confidence': 0.8,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25
            })

        default_results = test_db_manager.get_latest_detections(limit=10, unique=False)
        unique_results = test_db_manager.get_latest_detections(limit=10, unique=True)

        assert len(default_results) == 3
        assert len(unique_results) == 1
        assert unique_results[0]['common_name'] == 'American Robin'

    def test_get_group_detection_windows(self, test_db_manager, sample_detection):
        """Sibling windows: same species + same recording (group) + same audio
        source only, ordered by timestamp — what the player's analysis-window
        bar uses to label every 3s window that fired."""
        def insert(**overrides):
            return test_db_manager.insert_detection({**sample_detection, **overrides})

        # Chunks 0 and 1 of the same recording, same species (incl. the row itself)
        target_id = insert(timestamp='2024-01-15T10:30:00')
        insert(timestamp='2024-01-15T10:30:03', confidence=0.65)
        # Same recording, different species — excluded
        insert(timestamp='2024-01-15T10:30:03', common_name='Blue Jay',
               scientific_name='Cyanocitta cristata')
        # Same species, different recording — excluded
        insert(timestamp='2024-01-15T10:31:00', group_timestamp='2024-01-15T10:31:00')
        # Same species and recording window, different audio source — excluded
        insert(timestamp='2024-01-15T10:30:06', audio_source='cam2')

        detection = test_db_manager.get_detection_by_id(target_id)
        windows = test_db_manager.get_group_detection_windows(detection)

        assert windows == [
            {'timestamp': '2024-01-15T10:30:00', 'confidence': 0.95},
            {'timestamp': '2024-01-15T10:30:03', 'confidence': 0.65},
        ]

    def test_get_group_detection_windows_species_key_fallback(
            self, test_db_manager, sample_detection):
        """Legacy rows with empty scientific_name group on common_name (the
        same species key the display dedup partitions on)."""
        def insert(**overrides):
            return test_db_manager.insert_detection(
                {**sample_detection, 'scientific_name': '', **overrides})

        target_id = insert(timestamp='2024-01-15T10:30:00')
        insert(timestamp='2024-01-15T10:30:03', confidence=0.55)
        insert(timestamp='2024-01-15T10:30:06', common_name='Blue Jay')

        detection = test_db_manager.get_detection_by_id(target_id)
        windows = test_db_manager.get_group_detection_windows(detection)

        assert [w['timestamp'] for w in windows] == [
            '2024-01-15T10:30:00', '2024-01-15T10:30:03',
        ]

    def test_empty_database_queries(self, test_db_manager):
        """Test various queries on empty database."""
        # Test methods that should handle empty database gracefully
        assert test_db_manager.get_latest_detections(10) == []
        assert test_db_manager.get_all_unique_species() == []

        # Use local_now() (same source the SQL uses) so the test does not
        # depend on the docker container's system tz matching the configured
        # timezone in user_settings.json.
        now = local_now()
        all_stats = test_db_manager.get_summary_stats_all_periods(
            now.replace(hour=0, minute=0, second=0, microsecond=0),
            now - timedelta(weeks=1),
            now - timedelta(days=30),
        )
        for period in ('today', 'week', 'month', 'allTime'):
            stats = all_stats[period]
            assert stats['totalObservations'] == 0
            assert stats['uniqueSpecies'] == 0
            assert stats['mostActiveHour'] == 'N/A'
            assert stats['mostCommonBird'] == 'N/A'
            assert stats['rarestBird'] == 'N/A'

    def test_summary_stats_buckets_by_period(self, test_db_manager, frozen_db_now):
        """Detections in different time windows land in the right buckets.

        Pins the load-bearing semantic of get_summary_stats_all_periods: the
        CASE-WHEN-driven per-period counts (and the empty-period guards)
        must correctly route a detection at -2 days into today/week/month
        but not all-time-only, and a detection at -45 days into all-time
        only, not into today/week/month.
        """
        now = frozen_db_now
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(weeks=1)
        month_start = now - timedelta(days=30)

        def _insert(when, common_name, scientific_name):
            test_db_manager.insert_detection({
                'timestamp': when.isoformat(),
                'group_timestamp': when.isoformat(),
                'common_name': common_name,
                'scientific_name': scientific_name,
                'confidence': 0.85,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
            })

        # 3 of species A within today; 1 of species B 2 days ago (week+month
        # but not today); 1 of species C 45 days ago (all-time only).
        for offset_s in (10, 20, 30):
            _insert(now - timedelta(seconds=offset_s),
                    'Common Bird', 'Speciesus communis')
        _insert(now - timedelta(days=2),
                'Week Bird', 'Speciesus weekensis')
        _insert(now - timedelta(days=45),
                'Old Bird', 'Speciesus antiquus')

        all_stats = test_db_manager.get_summary_stats_all_periods(
            today_start, week_start, month_start,
        )

        assert all_stats['today']['totalObservations'] == 3
        assert all_stats['today']['uniqueSpecies'] == 1
        assert all_stats['today']['mostCommonBird'] == 'Common Bird'

        assert all_stats['week']['totalObservations'] == 4
        assert all_stats['week']['uniqueSpecies'] == 2
        assert all_stats['week']['mostCommonBird'] == 'Common Bird'
        assert all_stats['week']['rarestBird'] == 'Week Bird'

        assert all_stats['month']['totalObservations'] == 4
        assert all_stats['month']['uniqueSpecies'] == 2

        # 45-day-old detection shows up only in allTime.
        assert all_stats['allTime']['totalObservations'] == 5
        assert all_stats['allTime']['uniqueSpecies'] == 3
        assert all_stats['allTime']['rarestBird'] in {'Week Bird', 'Old Bird'}

    def test_summary_stats_picks_most_recent_name_per_species(
        self, test_db_manager, frozen_db_now
    ):
        """When a species appears under multiple common_name values across
        its history (the V2→V3 model-rename scenario), every period bucket
        must report the same canonical name — the one from the most recent
        detection. Without this, today's bucket could show the new name
        while allTime shows the old one for the *same* bird, since both
        are equally valid representatives under MIN/MAX aggregation.

        Names chosen specifically so MIN(common_name) (the broken
        all-time behavior pre-Option-C) and most-recent disagree: 'Alpha
        Historical' is alphabetically MIN, but 'Zulu Today' is the most
        recent. The test asserts 'Zulu Today' — would fail on the broken
        code, passes on Option C.
        """
        now = frozen_db_now
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(weeks=1)
        month_start = now - timedelta(days=30)

        sci = 'Turdus merula'

        # Historical detection — alphabetically MIN common_name. Same
        # _SPECIES_KEY as the recent one below because scientific_name
        # is identical.
        test_db_manager.insert_detection({
            'timestamp': (now - timedelta(days=200)).isoformat(),
            'group_timestamp': (now - timedelta(days=200)).isoformat(),
            'scientific_name': sci,
            'common_name': 'Alpha Historical',
            'confidence': 0.8,
            'latitude': 40.7128, 'longitude': -74.0060,
            'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
        })

        # Recent detection — alphabetically MAX common_name, but
        # chronologically newest.
        test_db_manager.insert_detection({
            'timestamp': (now - timedelta(seconds=10)).isoformat(),
            'group_timestamp': (now - timedelta(seconds=10)).isoformat(),
            'scientific_name': sci,
            'common_name': 'Zulu Today',
            'confidence': 0.8,
            'latitude': 40.7128, 'longitude': -74.0060,
            'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
        })

        all_stats = test_db_manager.get_summary_stats_all_periods(
            today_start, week_start, month_start,
        )

        # Today's bucket: one detection (the recent one); name is naturally
        # 'Zulu Today' — but also note this is the only detection in today,
        # so even MIN over the today subset would pick it. The real
        # discriminator is the allTime assertion below.
        assert all_stats['today']['totalObservations'] == 1
        assert all_stats['today']['mostCommonBird'] == 'Zulu Today'

        # The regression guard: allTime contains both rows. MIN over
        # all-time would return 'Alpha Historical' (A < Z). Option C
        # returns 'Zulu Today' (most recent). This is the case that
        # actually distinguishes the two behaviors.
        assert all_stats['allTime']['totalObservations'] == 2
        assert all_stats['allTime']['mostCommonBird'] == 'Zulu Today'
        assert all_stats['allTime']['rarestBird'] == 'Zulu Today'

    def test_summary_stats_breaks_count_ties_alphabetically(
        self, test_db_manager, frozen_db_now
    ):
        """Contract test for the tiebreaker on the per-period selectors.

        When two species (or hours) tie on c_<period>, the LIMIT 1 pick must
        be deterministic. SQLite today happens to return the species_key
        ASC pick anyway because sort-based GROUP BY emits groups in key
        order, so this test does not currently fail against the pre-fix SQL
        on SQLite 3.40.1 in the Docker image. But the contract is not
        guaranteed by SQL semantics — a future SQLite version that switches
        to hash-based aggregation, an index change, or concurrent writes
        could surface the non-determinism. This test pins the *required*
        contract (alphabetic-ASC tiebreaker) so a future refactor that
        breaks the tiebreaker fails loudly.
        """
        now = frozen_db_now
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(weeks=1)
        month_start = now - timedelta(days=30)

        # Two species, each with one detection today — c_today=1 for both.
        # Without the species_key ASC tiebreaker the pick is plan-dependent.
        # Hours differ (08 and 10) so the hour tiebreaker is also probed.
        # Both must be before frozen_db_now (12:00) or the SQL upper-bound
        # `BETWEEN ... AND :now` silently drops them and the test reduces
        # to a single-species sanity check that passes trivially.
        # Zulu is inserted first so its rowid is lower — without the
        # tiebreaker, SQLite's default group-scan order returns Zulu
        # ahead of Alpha; the assertion then fails.
        test_db_manager.insert_detection({
            'timestamp': today_start.replace(hour=10).isoformat(),
            'group_timestamp': today_start.replace(hour=10).isoformat(),
            'scientific_name': 'Zulu species',
            'common_name': 'Zulu Bird',
            'confidence': 0.8,
            'latitude': 40.7128, 'longitude': -74.0060,
            'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
        })
        test_db_manager.insert_detection({
            'timestamp': today_start.replace(hour=8).isoformat(),
            'group_timestamp': today_start.replace(hour=8).isoformat(),
            'scientific_name': 'Alpha species',
            'common_name': 'Alpha Bird',
            'confidence': 0.8,
            'latitude': 40.7128, 'longitude': -74.0060,
            'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
        })

        all_stats = test_db_manager.get_summary_stats_all_periods(
            today_start, week_start, month_start,
        )

        # Both species tied at c_today=1. Alphabetic species_key wins both
        # the most-common and rarest picks (only one alphabetically minimal
        # row exists). Without the tiebreaker, either pick could come back.
        assert all_stats['today']['mostCommonBird'] == 'Alpha Bird'
        assert all_stats['today']['rarestBird'] == 'Alpha Bird'

        # Hours 08 and 10 both have count=1. The hour ASC tiebreaker means
        # the earlier hour (08) wins.
        assert all_stats['today']['mostActiveHour'] == '08:00'

    def test_single_period_summary_matches_all_periods_contract(
        self, test_db_manager, frozen_db_now
    ):
        """The lazy Summary endpoint must preserve the all-period contract."""
        now = frozen_db_now
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(weeks=1)
        month_start = now - timedelta(days=30)

        rows = [
            (today_start.replace(hour=9), 'Alpha species', 'Alpha Bird'),
            (now - timedelta(days=3), 'Beta species', 'Beta Bird'),
            (now - timedelta(days=20), 'Gamma species', 'Gamma Bird'),
            (now - timedelta(days=200), 'Delta species', 'Delta Bird'),
        ]
        for timestamp, scientific_name, common_name in rows:
            test_db_manager.insert_detection({
                'timestamp': timestamp.isoformat(),
                'group_timestamp': timestamp.isoformat(),
                'scientific_name': scientific_name,
                'common_name': common_name,
                'confidence': 0.8,
                'latitude': 40.7128, 'longitude': -74.0060,
                'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
            })

        all_stats = test_db_manager.get_summary_stats_all_periods(
            today_start, week_start, month_start,
        )

        assert test_db_manager.get_summary_stats_for_period(
            today_start, now=now,
        ) == all_stats['today']
        assert test_db_manager.get_summary_stats_for_period(
            week_start, now=now,
        ) == all_stats['week']
        assert test_db_manager.get_summary_stats_for_period(
            month_start, now=now,
        ) == all_stats['month']
        assert test_db_manager.get_summary_stats_for_period(
            datetime.min, now=now,
        ) == all_stats['allTime']

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
