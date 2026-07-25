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

        # The fixture data is anchored in 2024, well outside today/week/month
        # relative to the test clock — so it lands in the allTime bucket.
        now = datetime.now()
        all_stats = test_db_manager.get_summary_stats_all_periods(
            now.replace(hour=0, minute=0, second=0, microsecond=0),
            now - timedelta(weeks=1),
            now - timedelta(days=30),
        )

        # allTime sees the full fixture.
        stats = all_stats['allTime']
        assert 'totalObservations' in stats
        assert 'uniqueSpecies' in stats
        assert stats['totalObservations'] == 11
        assert stats['uniqueSpecies'] == 2
        assert stats['mostCommonBird'] == 'American Robin'
        assert stats['rarestBird'] == 'Hooded Warbler'

        # Today/week/month buckets stay empty — the WHERE c_<period> > 0
        # guards in the SQL must prevent leaking historical detections
        # into recent buckets.
        for period in ('today', 'week', 'month'):
            empty = all_stats[period]
            assert empty['totalObservations'] == 0, period
            assert empty['uniqueSpecies'] == 0, period
            assert empty['mostActiveHour'] == 'N/A', period
            assert empty['mostCommonBird'] == 'N/A', period
            assert empty['rarestBird'] == 'N/A', period

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

        # Each species carries its latest detection timestamp so the Species
        # Catalog needs no per-species detail fetch.
        assert all(s['last_detected'] == '2024-01-15T12:00:00' for s in result)


class TestBirdDetailsDuplicateCommonName:
    """One common name, two scientific names (a taxonomy genus split the model
    label set carries twice, e.g. Charadrius/Thinornis 'Little Ringed Plover').

    The resolver hands the read layer every key for the name; detections can be
    stored under either, so species-keyed reads must match all of them.
    Regression for /bird/<name> and /bird/<name>/recording/<id> rendering blank
    when the resolver's winner isn't the key the station actually stored under.
    """

    OLD_KEY = 'Charadrius dubius'   # in_v2 — where a real station's rows land
    NEW_KEY = 'Thinornis dubius'    # v3-only split — the CSV-last winner
    COMMON = 'Little Ringed Plover'

    def _insert(self, mgr, sci, ts, confidence=0.8):
        return mgr.insert_detection({
            'timestamp': ts, 'group_timestamp': ts,
            'scientific_name': sci, 'common_name': self.COMMON,
            'confidence': confidence,
            'latitude': 40.7, 'longitude': -74.0,
            'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
        })

    def test_details_found_when_stored_under_non_winner_key(self, test_db_manager):
        # Rows exist only under the old-genus key; the resolver's winner is the
        # other. Winner-only (old behavior) misses; both keys now hit.
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-15T08:00:00')
        assert test_db_manager.get_bird_details(
            scientific_name=[self.NEW_KEY]) is None
        details = test_db_manager.get_bird_details(
            scientific_name=[self.NEW_KEY, self.OLD_KEY])
        assert details is not None
        assert details['total_visits'] == 1
        assert details['scientific_name'] == self.OLD_KEY

    def test_details_aggregate_across_both_keys(self, test_db_manager):
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-15T08:00:00')
        self._insert(test_db_manager, self.OLD_KEY, '2024-02-15T08:00:00')
        self._insert(test_db_manager, self.NEW_KEY, '2024-03-15T09:00:00')
        details = test_db_manager.get_bird_details(
            scientific_name=[self.NEW_KEY, self.OLD_KEY])
        assert details['total_visits'] == 3
        assert details['first_detected'] == '2024-01-15T08:00:00'
        assert details['last_detected'] == '2024-03-15T09:00:00'

    def test_single_key_list_matches_legacy_shape(self, test_db_manager):
        # The common (unduplicated) case: a one-element list behaves exactly
        # like the prior single-key read.
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-15T08:00:00')
        one = test_db_manager.get_bird_details(scientific_name=[self.OLD_KEY])
        assert one['total_visits'] == 1
        assert one['scientific_name'] == self.OLD_KEY

    def test_recordings_and_distribution_span_both_keys(self, test_db_manager):
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-15T08:00:00')
        self._insert(test_db_manager, self.NEW_KEY, '2024-01-16T08:00:00')
        recs = test_db_manager.get_bird_recordings(
            scientific_name=[self.NEW_KEY, self.OLD_KEY])
        assert len(recs) == 2
        dist = test_db_manager.get_detection_distribution(
            view='month', anchor_date_str='2024-01-15',
            scientific_name=[self.NEW_KEY, self.OLD_KEY])
        assert sum(dist['data']) == 2

    def test_representative_is_the_most_detected_key(self, test_db_manager):
        # The displayed identity comes from the key the station actually uses,
        # so a rarely-hit duplicate can't relabel the card.
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-15T08:00:00')
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-16T08:00:00')
        self._insert(test_db_manager, self.NEW_KEY, '2024-01-17T08:00:00')
        for order in ([self.NEW_KEY, self.OLD_KEY], [self.OLD_KEY, self.NEW_KEY]):
            details = test_db_manager.get_bird_details(scientific_name=order)
            assert details['scientific_name'] == self.OLD_KEY, order

    def test_representative_tie_breaks_on_caller_order(self, test_db_manager):
        # Equal counts: the resolver's representative (first key) wins rather
        # than whichever row SQLite happens to scan first, so the name shown
        # doesn't flip between requests as counts drift into a tie.
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-15T08:00:00')
        self._insert(test_db_manager, self.NEW_KEY, '2024-01-16T08:00:00')
        first = test_db_manager.get_bird_details(
            scientific_name=[self.NEW_KEY, self.OLD_KEY])
        assert first['scientific_name'] == self.NEW_KEY
        second = test_db_manager.get_bird_details(
            scientific_name=[self.OLD_KEY, self.NEW_KEY])
        assert second['scientific_name'] == self.OLD_KEY

    def test_legacy_common_name_path_aggregates_across_keys(self, test_db_manager):
        # The fallback path (resolver missed, filtering by common_name) must
        # also report the whole species: it used to GROUP BY scientific_name
        # and keep one arbitrary group, under-counting a split species.
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-15T08:00:00')
        self._insert(test_db_manager, self.OLD_KEY, '2024-02-15T08:00:00')
        self._insert(test_db_manager, self.NEW_KEY, '2024-03-15T09:00:00')
        details = test_db_manager.get_bird_details(species_name=self.COMMON)
        assert details['total_visits'] == 3
        assert details['first_detected'] == '2024-01-15T08:00:00'
        assert details['last_detected'] == '2024-03-15T09:00:00'
        # Representative is the most-detected key, not an arbitrary group.
        assert details['scientific_name'] == self.OLD_KEY

    def test_legacy_common_name_path_returns_none_for_unknown(self, test_db_manager):
        # The ungrouped aggregate always yields a row; an unknown species must
        # still read as "no such species" rather than a zero-count record.
        assert test_db_manager.get_bird_details(
            species_name='No Such Bird At All') is None

    def test_catalog_lists_a_split_species_once(self, test_db_manager):
        # The rollup holds a row per scientific_name, so without folding, the
        # catalog renders two identical cards that both open the one detail
        # page merging them — and neither card's count matches that page.
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-15T08:00:00')
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-16T08:00:00')
        self._insert(test_db_manager, self.NEW_KEY, '2024-01-17T08:00:00')

        catalog = test_db_manager.get_all_unique_species()
        entries = [s for s in catalog if s['common_name'] == self.COMMON]
        assert len(entries) == 1
        # Folded entry keeps the most-detected name and the newest sighting.
        assert entries[0]['scientific_name'] == self.OLD_KEY
        assert entries[0]['last_detected'] == '2024-01-17T08:00:00'

    def test_catalog_keeps_distinct_species_separate(self, test_db_manager):
        # Folding must key on the taxon group, not the common name, so genuinely
        # different birds still get their own catalog entries.
        self._insert(test_db_manager, self.OLD_KEY, '2024-01-15T08:00:00')
        test_db_manager.insert_detection({
            'timestamp': '2024-01-15T09:00:00',
            'group_timestamp': '2024-01-15T09:00:00',
            'scientific_name': 'Turdus merula', 'common_name': 'Common Blackbird',
            'confidence': 0.8, 'latitude': 40.7, 'longitude': -74.0,
            'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
        })
        catalog = test_db_manager.get_all_unique_species()
        assert len(catalog) == 2
        assert {s['common_name'] for s in catalog} == {
            self.COMMON, 'Common Blackbird'}
