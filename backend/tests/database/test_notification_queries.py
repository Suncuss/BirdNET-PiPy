"""Tests for notification-related database query methods."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


def insert(db, sci_name, common_name, timestamp, confidence=0.9):
    db.insert_detection({
        'timestamp': timestamp,
        'group_timestamp': timestamp,
        'scientific_name': sci_name,
        'common_name': common_name,
        'confidence': confidence,
        'latitude': 40.7128,
        'longitude': -74.0060,
        'cutoff': 0.5,
        'sensitivity': 0.75,
        'overlap': 0.25
    })


class TestGetTodayDetectionCount:
    """Tests for get_today_detection_count."""

    def test_counts_detections_on_same_day(self, test_db_manager):
        """Counts detections that fall on the same calendar day."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T08:00:00')
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T12:00:00')
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T18:00:00')

        count = test_db_manager.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T23:59:59')
        assert count == 3

    def test_excludes_detections_from_other_days(self, test_db_manager):
        """Does not count detections from previous or next day."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-14T23:59:59')
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T10:00:00')
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-16T00:01:00')

        count = test_db_manager.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T23:59:59')
        assert count == 1

    def test_day_boundary_midnight(self, test_db_manager):
        """Detection at exactly midnight counts for the new day."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T00:00:00')

        count = test_db_manager.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T12:00:00')
        assert count == 1

    def test_before_timestamp_upper_bound(self, test_db_manager):
        """Only counts detections up to and including the before_timestamp."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T10:00:00')
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T10:05:00')

        # Query with timestamp of first detection only
        count = test_db_manager.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_filters_by_species(self, test_db_manager):
        """Counts only detections of the specified species."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T10:00:00')
        insert(test_db_manager, 'Cyanocitta cristata', 'Blue Jay', '2024-06-15T10:00:00')

        count = test_db_manager.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T23:59:59')
        assert count == 1

    def test_returns_zero_for_no_detections(self, test_db_manager):
        """Returns 0 when there are no matching detections."""
        count = test_db_manager.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T10:00:00')
        assert count == 0


class TestGetRecentDetectionCount:
    """Tests for get_recent_detection_count."""

    def test_counts_detections_within_window(self, test_db_manager):
        """Counts detections within the specified day window."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-10T10:00:00')
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-12T10:00:00')
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-14T10:00:00')

        count = test_db_manager.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 3

    def test_excludes_detections_outside_window(self, test_db_manager):
        """Does not count detections older than the window."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-01T10:00:00')
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-14T10:00:00')

        count = test_db_manager.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_window_edge_exactly_7_days_ago(self, test_db_manager):
        """Detection exactly at the window boundary is included."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-08T10:00:00')

        count = test_db_manager.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_window_edge_just_outside(self, test_db_manager):
        """Detection just before the window boundary is excluded."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-08T09:59:59')

        count = test_db_manager.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 0

    def test_before_timestamp_upper_bound(self, test_db_manager):
        """Only counts detections up to and including before_timestamp."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T10:00:00')
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-15T10:05:00')

        count = test_db_manager.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_filters_by_species(self, test_db_manager):
        """Counts only detections of the specified species."""
        insert(test_db_manager, 'Turdus migratorius', 'Robin', '2024-06-14T10:00:00')
        insert(test_db_manager, 'Cyanocitta cristata', 'Blue Jay', '2024-06-14T10:00:00')

        count = test_db_manager.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_returns_zero_for_no_detections(self, test_db_manager):
        """Returns 0 when there are no matching detections."""
        count = test_db_manager.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 0
