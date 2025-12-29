"""Tests for the extra JSON field functionality."""
import pytest


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


class TestExtraFieldHelpers:
    """Test extra field helper methods."""

    def test_get_extra_field(self, test_db_manager, sample_detection):
        """Test getting a specific field from extra."""
        sample_detection['extra'] = {'weather': 'sunny', 'temperature': 72}
        detection_id = test_db_manager.insert_detection(sample_detection)

        weather = test_db_manager.get_extra_field(detection_id, 'weather')
        assert weather == 'sunny'

    def test_get_extra_field_missing(self, test_db_manager, sample_detection):
        """Test getting a missing field returns None."""
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_extra_field(detection_id, 'nonexistent')
        assert result is None

    def test_get_extra_field_with_default(self, test_db_manager, sample_detection):
        """Test getting a missing field with custom default."""
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.get_extra_field(detection_id, 'nonexistent', default='N/A')
        assert result == 'N/A'

    def test_get_extra_field_nonexistent_detection(self, test_db_manager):
        """Test getting extra field for nonexistent detection returns default."""
        result = test_db_manager.get_extra_field(99999, 'field', default='fallback')
        assert result == 'fallback'

    def test_update_extra_field(self, test_db_manager, sample_detection):
        """Test updating a specific field in extra."""
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.update_extra_field(detection_id, 'notes', 'Beautiful song!')
        assert result is True

        notes = test_db_manager.get_extra_field(detection_id, 'notes')
        assert notes == 'Beautiful song!'

    def test_update_extra_field_preserves_existing(self, test_db_manager, sample_detection):
        """Test updating extra field preserves other fields."""
        sample_detection['extra'] = {'weather': 'sunny'}
        detection_id = test_db_manager.insert_detection(sample_detection)

        test_db_manager.update_extra_field(detection_id, 'notes', 'Great recording')

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result['extra']['weather'] == 'sunny'
        assert result['extra']['notes'] == 'Great recording'

    def test_update_extra_field_nonexistent_detection(self, test_db_manager):
        """Test updating extra field for nonexistent detection returns False."""
        result = test_db_manager.update_extra_field(99999, 'field', 'value')
        assert result is False

    def test_set_extra_replaces_all(self, test_db_manager, sample_detection):
        """Test set_extra replaces the entire extra dict."""
        sample_detection['extra'] = {'old_key': 'old_value'}
        detection_id = test_db_manager.insert_detection(sample_detection)

        result = test_db_manager.set_extra(detection_id, {'new_key': 'new_value'})
        assert result is True

        detection = test_db_manager.get_detection_by_id(detection_id)
        assert detection['extra'] == {'new_key': 'new_value'}
        assert 'old_key' not in detection['extra']

    def test_set_extra_nonexistent_detection(self, test_db_manager):
        """Test set_extra for nonexistent detection returns False."""
        result = test_db_manager.set_extra(99999, {'key': 'value'})
        assert result is False

    def test_set_extra_requires_dict(self, test_db_manager, sample_detection):
        """Test set_extra raises error for non-dict input."""
        detection_id = test_db_manager.insert_detection(sample_detection)

        with pytest.raises(ValueError, match="must be a dictionary"):
            test_db_manager.set_extra(detection_id, "not a dict")


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

    def test_get_all_detections_for_export_includes_extra(self, test_db_manager, sample_detection):
        """Test get_all_detections_for_export includes extra as raw JSON string."""
        sample_detection['extra'] = {'export_test': True}
        test_db_manager.insert_detection(sample_detection)

        results = test_db_manager.get_all_detections_for_export()
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
