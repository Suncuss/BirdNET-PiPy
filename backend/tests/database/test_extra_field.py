"""Tests for the extra JSON field functionality."""


class TestExtraFieldInsert:
    """Test inserting detections with extra data."""

    def test_insert_with_extra_dict(self, test_db_manager, sample_detection):
        """Test inserting detection with extra data as dict."""
        sample_detection['extra'] = {'weather': 'sunny', 'temperature': 72}
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result['extra'] == {'weather': 'sunny', 'temperature': 72}

    def test_insert_without_extra(self, test_db_manager, sample_detection):
        """Test inserting detection without extra data defaults to empty dict."""
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result['extra'] == {}

    def test_insert_with_none_extra(self, test_db_manager, sample_detection):
        """Test inserting detection with None extra normalizes to empty dict."""
        sample_detection['extra'] = None
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result['extra'] == {}

    def test_insert_with_nested_extra(self, test_db_manager, sample_detection):
        """Test inserting detection with nested extra data."""
        sample_detection['extra'] = {
            'weather': {
                'condition': 'partly_cloudy',
                'temperature_f': 68,
                'humidity_percent': 45
            },
            'tags': ['favorite', 'rare']
        }
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result['extra']['weather']['condition'] == 'partly_cloudy'
        assert result['extra']['tags'] == ['favorite', 'rare']


class TestExtraFieldInQueries:
    """Test that extra field is included in query results."""

    def test_get_latest_detections_includes_extra(self, test_db_manager, sample_detection):
        """Test get_latest_detections includes extra field."""
        sample_detection['extra'] = {'source': 'test'}
        test_db_manager.insert_detection(sample_detection)

        results = test_db_manager.get_latest_detections(limit=1)
        assert len(results) == 1
        assert results[0]['extra'] == {'source': 'test'}

    def test_get_paginated_detections_includes_extra(self, test_db_manager, sample_detection):
        """Test get_paginated_detections includes extra field."""
        sample_detection['extra'] = {'source': 'paginated_test'}
        test_db_manager.insert_detection(sample_detection)

        results, total = test_db_manager.get_paginated_detections(page=1, per_page=10)
        assert len(results) == 1
        assert results[0]['extra'] == {'source': 'paginated_test'}

    def test_get_bird_recordings_includes_extra(self, test_db_manager, sample_detection):
        """Test get_bird_recordings includes extra field."""
        sample_detection['extra'] = {'quality': 'excellent'}
        test_db_manager.insert_detection(sample_detection)

        results = test_db_manager.get_bird_recordings('American Robin')
        assert len(results) == 1
        assert results[0]['extra'] == {'quality': 'excellent'}

    def test_get_detections_for_export_batch_includes_extra(self, test_db_manager, sample_detection):
        """Test get_detections_for_export_batch includes extra as raw JSON string."""
        sample_detection['extra'] = {'export_test': True}
        test_db_manager.insert_detection(sample_detection)

        results = test_db_manager.get_detections_for_export_batch(limit=100)
        assert len(results) == 1
        # Export keeps raw JSON string
        assert results[0]['extra'] == '{"export_test": true}'

    def test_get_detections_by_date_range_includes_extra(self, test_db_manager, sample_detection):
        """Test get_detections_by_date_range includes parsed extra field."""
        sample_detection['extra'] = {'date_range_test': 'value'}
        test_db_manager.insert_detection(sample_detection)

        results = test_db_manager.get_detections_by_date_range('2024-01-01', '2024-12-31')
        assert len(results) == 1
        assert results[0]['extra'] == {'date_range_test': 'value'}

    def test_get_detections_by_date_range_unique_includes_extra(self, test_db_manager, sample_detection):
        """Test get_detections_by_date_range with unique=True includes parsed extra."""
        sample_detection['extra'] = {'unique_test': True}
        test_db_manager.insert_detection(sample_detection)

        results = test_db_manager.get_detections_by_date_range('2024-01-01', '2024-12-31', unique=True)
        assert len(results) == 1
        assert results[0]['extra'] == {'unique_test': True}

    def test_get_species_sightings_includes_extra(self, test_db_manager, sample_detection):
        """Test get_species_sightings includes parsed extra field."""
        sample_detection['extra'] = {'sighting_test': 123}
        test_db_manager.insert_detection(sample_detection)

        results = test_db_manager.get_species_sightings(limit=10)
        assert len(results) == 1
        assert results[0]['extra'] == {'sighting_test': 123}

    def test_get_species_sightings_rare_includes_extra(self, test_db_manager, sample_detection):
        """Test get_species_sightings with most_frequent=False includes parsed extra."""
        sample_detection['extra'] = {'rare_test': 'bird'}
        test_db_manager.insert_detection(sample_detection)

        results = test_db_manager.get_species_sightings(limit=10, most_frequent=False)
        assert len(results) == 1
        assert results[0]['extra'] == {'rare_test': 'bird'}


class TestParseExtra:
    """Test the _parse_extra helper method."""

    def test_parse_extra_valid_json(self, test_db_manager):
        """Test parsing valid JSON string."""
        result = test_db_manager._parse_extra('{"key": "value"}')
        assert result == {'key': 'value'}

    def test_parse_extra_empty_string(self, test_db_manager):
        """Test parsing empty string returns empty dict."""
        result = test_db_manager._parse_extra('')
        assert result == {}

    def test_parse_extra_none(self, test_db_manager):
        """Test parsing None returns empty dict."""
        result = test_db_manager._parse_extra(None)
        assert result == {}

    def test_parse_extra_invalid_json(self, test_db_manager):
        """Test parsing invalid JSON returns empty dict."""
        result = test_db_manager._parse_extra('not valid json')
        assert result == {}

    def test_parse_extra_already_dict(self, test_db_manager):
        """Test parsing already-dict returns same dict."""
        input_dict = {'already': 'parsed'}
        result = test_db_manager._parse_extra(input_dict)
        assert result == input_dict


class TestEbirdCodeInExtra:
    """Test eBird code storage in the extra field."""

    def test_ebird_code_saved_to_database(self, test_db_manager, sample_detection):
        """Test that ebird_code is persisted in database extra field."""
        sample_detection['extra'] = {'ebird_code': 'amerob'}
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result['extra']['ebird_code'] == 'amerob'

    def test_null_ebird_code_saved(self, test_db_manager, sample_detection):
        """Test that null ebird_code is persisted correctly."""
        sample_detection['extra'] = {'ebird_code': None}
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result['extra']['ebird_code'] is None

    def test_ebird_code_with_other_extra_data(self, test_db_manager, sample_detection):
        """Test ebird_code alongside other extra data."""
        sample_detection['extra'] = {
            'ebird_code': 'norcar',
            'notes': 'Beautiful song',
            'quality': 'excellent'
        }
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result['extra']['ebird_code'] == 'norcar'
        assert result['extra']['notes'] == 'Beautiful song'
        assert result['extra']['quality'] == 'excellent'

    def test_ebird_code_in_query_results(self, test_db_manager, sample_detection):
        """Test that ebird_code is included in various query results."""
        sample_detection['extra'] = {'ebird_code': 'blujay'}
        test_db_manager.insert_detection(sample_detection)

        # Test get_latest_detections
        results = test_db_manager.get_latest_detections(limit=10)
        assert len(results) == 1
        assert results[0]['extra']['ebird_code'] == 'blujay'

    def test_model_info_saved_to_database(self, test_db_manager, sample_detection):
        """Test that model info is persisted in database extra field."""
        sample_detection['extra'] = {
            'ebird_code': 'amerob',
            'model': 'birdnet',
            'model_version': '2.4'
        }
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result['extra']['model'] == 'birdnet'
        assert result['extra']['model_version'] == '2.4'
        assert result['extra']['ebird_code'] == 'amerob'
