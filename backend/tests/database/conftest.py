"""
Database-specific test fixtures and configuration.
"""
from datetime import datetime

import pytest


@pytest.fixture
def frozen_db_now(monkeypatch):
    """Pin core.db.local_now to a fixed mid-day for the duration of the test.

    The summary SQL (get_summary_stats_for_period) uses local_now() as its
    upper-bound clock. Pinning it to mid-day decouples tests from CI wall
    time — without this, tests that insert detections at small negative
    second-offsets flake near midnight.
    """
    fixed = datetime(2026, 5, 20, 12, 0, 0)
    monkeypatch.setattr('core.db.local_now', lambda: fixed)
    return fixed


def summary_all_periods(db, today_start, week_start, month_start):
    """The dashboard's four summary periods, each through
    get_summary_stats_for_period (what /api/dashboard/summary serves)."""
    starts = {'today': today_start, 'week': week_start,
              'month': month_start, 'allTime': datetime.min}
    return {period: db.get_summary_stats_for_period(start)
            for period, start in starts.items()}


@pytest.fixture
def sample_detection():
    """Standard bird detection for testing."""
    return {
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


def insert_legacy(db, timestamp, common='American Robin',
                  scientific='Turdus migratorius', confidence=0.9,
                  extra='{}', audio_source=None):
    """A row as downgraded/pre-migration code would leave it: media_bytes
    and media_nonce both NULL (unresolved, the frontier's job)."""
    with db.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO detections (timestamp, group_timestamp, "
            "scientific_name, common_name, confidence, extra, audio_source, "
            "media_bytes, media_nonce) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
            (timestamp, timestamp, scientific, common, confidence,
             extra, audio_source))
        conn.commit()
        return cur.lastrowid


def media_rows(db, detection_id):
    with db.get_db_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT filename, kind, rank, bytes FROM detection_media "
            "WHERE detection_id = ? ORDER BY kind, rank",
            (detection_id,)).fetchall()]


def media_count(db):
    with db.get_db_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM detection_media").fetchone()[0]


def stamped_bytes(db, detection_id):
    with db.get_db_connection() as conn:
        return conn.execute(
            "SELECT media_bytes FROM detections WHERE id = ?",
            (detection_id,)).fetchone()[0]
