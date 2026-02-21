"""Tests for notification-related database query methods."""

import os
import sys
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from fixtures.test_config import TEST_DATABASE_SCHEMA


@pytest.fixture
def notif_db():
    """Create a DatabaseManager with temporary database for notification query tests."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name

    with patch('config.settings.DATABASE_PATH', db_path):
        with patch('config.settings.DATABASE_SCHEMA', TEST_DATABASE_SCHEMA):
            from core.db import DatabaseManager
            manager = DatabaseManager(db_path=db_path)
            yield manager

    if os.path.exists(db_path):
        os.unlink(db_path)


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

    def test_counts_detections_on_same_day(self, notif_db):
        """Counts detections that fall on the same calendar day."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T08:00:00')
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T12:00:00')
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T18:00:00')

        count = notif_db.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T23:59:59')
        assert count == 3

    def test_excludes_detections_from_other_days(self, notif_db):
        """Does not count detections from previous or next day."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-14T23:59:59')
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T10:00:00')
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-16T00:01:00')

        count = notif_db.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T23:59:59')
        assert count == 1

    def test_day_boundary_midnight(self, notif_db):
        """Detection at exactly midnight counts for the new day."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T00:00:00')

        count = notif_db.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T12:00:00')
        assert count == 1

    def test_before_timestamp_upper_bound(self, notif_db):
        """Only counts detections up to and including the before_timestamp."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T10:00:00')
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T10:05:00')

        # Query with timestamp of first detection only
        count = notif_db.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_filters_by_species(self, notif_db):
        """Counts only detections of the specified species."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T10:00:00')
        insert(notif_db, 'Cyanocitta cristata', 'Blue Jay', '2024-06-15T10:00:00')

        count = notif_db.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T23:59:59')
        assert count == 1

    def test_returns_zero_for_no_detections(self, notif_db):
        """Returns 0 when there are no matching detections."""
        count = notif_db.get_today_detection_count(
            'Turdus migratorius', before_timestamp='2024-06-15T10:00:00')
        assert count == 0


class TestGetRecentDetectionCount:
    """Tests for get_recent_detection_count."""

    def test_counts_detections_within_window(self, notif_db):
        """Counts detections within the specified day window."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-10T10:00:00')
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-12T10:00:00')
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-14T10:00:00')

        count = notif_db.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 3

    def test_excludes_detections_outside_window(self, notif_db):
        """Does not count detections older than the window."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-01T10:00:00')
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-14T10:00:00')

        count = notif_db.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_window_edge_exactly_7_days_ago(self, notif_db):
        """Detection exactly at the window boundary is included."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-08T10:00:00')

        count = notif_db.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_window_edge_just_outside(self, notif_db):
        """Detection just before the window boundary is excluded."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-08T09:59:59')

        count = notif_db.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 0

    def test_before_timestamp_upper_bound(self, notif_db):
        """Only counts detections up to and including before_timestamp."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T10:00:00')
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-15T10:05:00')

        count = notif_db.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_filters_by_species(self, notif_db):
        """Counts only detections of the specified species."""
        insert(notif_db, 'Turdus migratorius', 'Robin', '2024-06-14T10:00:00')
        insert(notif_db, 'Cyanocitta cristata', 'Blue Jay', '2024-06-14T10:00:00')

        count = notif_db.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 1

    def test_returns_zero_for_no_detections(self, notif_db):
        """Returns 0 when there are no matching detections."""
        count = notif_db.get_recent_detection_count(
            'Turdus migratorius', days=7, before_timestamp='2024-06-15T10:00:00')
        assert count == 0
