"""Tests for the user_version-gated migration framework in core.db_schema."""
import os
import sqlite3
import tempfile

import pytest

from core.db import DatabaseManager
from core.db_schema import SCHEMA_VERSION


@pytest.fixture
def temp_db_path():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


def get_user_version(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


class TestSchemaMigrations:

    def test_fresh_database_stamped_at_latest_version(self, temp_db_path):
        DatabaseManager(db_path=temp_db_path)
        assert get_user_version(temp_db_path) == SCHEMA_VERSION

    def test_preversioning_database_converges(self, temp_db_path):
        """A database from before versioning (user_version 0, ad-hoc state)
        must come out at SCHEMA_VERSION with every migration applied."""
        # Old shape: no audio_source column, a legacy index present
        conn = sqlite3.connect(temp_db_path)
        conn.executescript("""
            CREATE TABLE detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL,
                group_timestamp DATETIME NOT NULL,
                scientific_name VARCHAR(100) NOT NULL,
                common_name VARCHAR(100) NOT NULL,
                confidence DECIMAL(5,4) NOT NULL,
                latitude DECIMAL(10,8),
                longitude DECIMAL(11,8),
                cutoff DECIMAL(4,3),
                sensitivity DECIMAL(4,3),
                overlap DECIMAL(4,3),
                week INT GENERATED ALWAYS AS (strftime('%W', timestamp)) STORED
            );
            CREATE INDEX idx_detections_week ON detections(week);
        """)
        conn.close()

        DatabaseManager(db_path=temp_db_path)

        conn = sqlite3.connect(temp_db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(detections)")}
        indexes = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        conn.close()

        assert get_user_version(temp_db_path) == SCHEMA_VERSION
        assert 'extra' in columns
        assert 'audio_source' in columns
        assert 'idx_detections_week' not in indexes

    def test_init_creates_planner_statistics(self, temp_db_path):
        """Every init runs a bounded ANALYZE so the query planner has real
        statistics instead of schema-order heuristics."""
        manager = DatabaseManager(db_path=temp_db_path)
        manager.insert_detection({
            'timestamp': '2024-01-15T10:30:00',
            'group_timestamp': '2024-01-15T10:30:00',
            'scientific_name': 'Turdus migratorius',
            'common_name': 'American Robin',
            'confidence': 0.9,
            'latitude': 40.0, 'longitude': -74.0,
            'cutoff': 0.5, 'sensitivity': 0.75, 'overlap': 0.25,
        })
        # Second init analyzes the now-populated table
        DatabaseManager(db_path=temp_db_path)

        conn = sqlite3.connect(temp_db_path)
        stats = conn.execute(
            "SELECT COUNT(*) FROM sqlite_stat1 WHERE tbl = 'detections'"
        ).fetchone()[0]
        conn.close()
        assert stats > 0

    def test_applied_migrations_do_not_rerun(self, temp_db_path):
        """State changed after a migration ran must survive re-init: the
        version gate, not the state probe, decides what runs."""
        DatabaseManager(db_path=temp_db_path)

        # Re-add a legacy index; the DB is already stamped at SCHEMA_VERSION,
        # so migration 3 must NOT run again and remove it.
        conn = sqlite3.connect(temp_db_path)
        conn.execute("CREATE INDEX idx_detections_week ON detections(week)")
        conn.close()

        DatabaseManager(db_path=temp_db_path)

        conn = sqlite3.connect(temp_db_path)
        indexes = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        conn.close()
        assert 'idx_detections_week' in indexes
