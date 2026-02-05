"""
Tests for _normalize_detection helper method.
Ensures consistent detection normalization across all DB methods.
"""
import json


class TestNormalizeDetection:
    """Tests for the _normalize_detection helper method."""

    def test_normalize_detection_with_filenames(self, test_db_manager):
        """Test normalization with filename generation."""
        # Insert a detection
        detection = {
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Cyanocitta cristata',
            'common_name': 'Blue Jay',
            'confidence': 0.876,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': json.dumps({'model': 'birdnet_v2'})
        }
        detection_id = test_db_manager.insert_detection(detection)

        # Get the raw row
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM detections WHERE id = ?", (detection_id,))
            row = cur.fetchone()

        # Test normalization with filenames
        result = test_db_manager._normalize_detection(row, include_filenames=True)

        # Check basic fields
        assert result['common_name'] == 'Blue Jay'
        assert result['scientific_name'] == 'Cyanocitta cristata'
        assert result['confidence'] == 0.876

        # Check extra is parsed
        assert isinstance(result['extra'], dict)
        assert result['extra'].get('model') == 'birdnet_v2'

        # Check filenames are generated
        # Time uses dashes for filesystem compatibility (Windows doesn't allow colons)
        assert 'audio_filename' in result
        assert 'spectrogram_filename' in result
        assert result['audio_filename'] == 'Blue_Jay_88_2024-01-15-birdnet-10-30-45.mp3'
        assert result['spectrogram_filename'] == 'Blue_Jay_88_2024-01-15-birdnet-10-30-45.webp'

    def test_normalize_detection_without_filenames(self, test_db_manager):
        """Test normalization without filename generation."""
        detection = {
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.92,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        }
        detection_id = test_db_manager.insert_detection(detection)

        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM detections WHERE id = ?", (detection_id,))
            row = cur.fetchone()

        result = test_db_manager._normalize_detection(row, include_filenames=False)

        # Check basic fields
        assert result['common_name'] == 'American Robin'
        assert result['confidence'] == 0.92

        # Check extra is parsed (default empty dict)
        assert isinstance(result['extra'], dict)
        assert result['extra'] == {}

        # Check filenames are NOT present
        assert 'audio_filename' not in result
        assert 'spectrogram_filename' not in result

    def test_normalize_detection_handles_null_extra(self, test_db_manager):
        """Test that null extra field is handled correctly."""
        detection = {
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': None
        }
        detection_id = test_db_manager.insert_detection(detection)

        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM detections WHERE id = ?", (detection_id,))
            row = cur.fetchone()

        result = test_db_manager._normalize_detection(row)

        # Extra should be empty dict, not None
        assert result['extra'] == {}

    def test_normalize_detection_handles_invalid_json_extra(self, test_db_manager):
        """Test that invalid JSON in extra field is handled gracefully."""
        detection = {
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.85,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25
        }
        detection_id = test_db_manager.insert_detection(detection)

        # Manually set invalid JSON
        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE detections SET extra = ? WHERE id = ?",
                       ('not valid json {{{', detection_id))
            conn.commit()

        with test_db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM detections WHERE id = ?", (detection_id,))
            row = cur.fetchone()

        result = test_db_manager._normalize_detection(row)

        # Should return empty dict for invalid JSON
        assert result['extra'] == {}


class TestNormalizationConsistency:
    """Tests ensuring consistent normalization across all DB methods that return detections."""

    def test_get_latest_detections_uses_normalization(self, test_db_manager):
        """Test that get_latest_detections uses normalized format."""
        detection = {
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Cyanocitta cristata',
            'common_name': 'Blue Jay',
            'confidence': 0.88,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': json.dumps({'source': 'test'})
        }
        test_db_manager.insert_detection(detection)

        results = test_db_manager.get_latest_detections(1)
        assert len(results) == 1

        result = results[0]
        # Check extra is parsed
        assert isinstance(result['extra'], dict)
        assert result['extra'].get('source') == 'test'
        # Check filenames (legacy naming)
        assert 'bird_song_file_name' in result
        assert 'spectrogram_file_name' in result

    def test_get_bird_recordings_uses_normalization(self, test_db_manager):
        """Test that get_bird_recordings uses normalized format."""
        detection = {
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Cyanocitta cristata',
            'common_name': 'Blue Jay',
            'confidence': 0.88,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': json.dumps({'source': 'recording_test'})
        }
        test_db_manager.insert_detection(detection)

        results = test_db_manager.get_bird_recordings('Blue Jay')
        assert len(results) == 1

        result = results[0]
        # Check extra is parsed
        assert isinstance(result['extra'], dict)
        assert result['extra'].get('source') == 'recording_test'
        # Check filenames (standard naming)
        assert 'audio_filename' in result
        assert 'spectrogram_filename' in result

    def test_get_paginated_detections_uses_normalization(self, test_db_manager):
        """Test that get_paginated_detections uses normalized format."""
        detection = {
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Cyanocitta cristata',
            'common_name': 'Blue Jay',
            'confidence': 0.88,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': json.dumps({'source': 'paginated_test'})
        }
        test_db_manager.insert_detection(detection)

        results, total = test_db_manager.get_paginated_detections(page=1, per_page=10)
        assert total == 1
        assert len(results) == 1

        result = results[0]
        # Check extra is parsed
        assert isinstance(result['extra'], dict)
        assert result['extra'].get('source') == 'paginated_test'
        # Check filenames (standard naming)
        assert 'audio_filename' in result
        assert 'spectrogram_filename' in result

    def test_get_detection_by_id_uses_normalization(self, test_db_manager):
        """Test that get_detection_by_id uses normalized format."""
        detection = {
            'timestamp': '2024-01-15T10:30:45',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Cyanocitta cristata',
            'common_name': 'Blue Jay',
            'confidence': 0.88,
            'latitude': 40.7128,
            'longitude': -74.0060,
            'cutoff': 0.5,
            'sensitivity': 0.75,
            'overlap': 0.25,
            'extra': json.dumps({'source': 'id_test'})
        }
        detection_id = test_db_manager.insert_detection(detection)

        result = test_db_manager.get_detection_by_id(detection_id)
        assert result is not None

        # Check extra is parsed
        assert isinstance(result['extra'], dict)
        assert result['extra'].get('source') == 'id_test'
        # Check filenames (standard naming)
        assert 'audio_filename' in result
        assert 'spectrogram_filename' in result

    def test_get_detection_by_id_returns_none_for_missing(self, test_db_manager):
        """Test that get_detection_by_id returns None for non-existent ID."""
        result = test_db_manager.get_detection_by_id(99999)
        assert result is None
