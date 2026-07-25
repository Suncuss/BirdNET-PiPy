"""Tests for schema creation and versioned migrations (core.db_schema).

Covers the user_version-gated framework, migration 3's legacy-index drop
(idx_detections_common_name / _scientific_name / _week / _location:
week/location were never queried, the single-column name indexes are
prefix-redundant with the composites), and the EXPLAIN QUERY PLAN guards
pinning that the composite indexes keep serving species equality lookups
— the property that made dropping the single-column indexes safe.
"""
import os
import sqlite3
import tempfile

import pytest

from core.db import DatabaseManager
from core.db_schema import SCHEMA_VERSION

LEGACY_INDEXES = (
    'idx_detections_common_name',
    'idx_detections_scientific_name',
    'idx_detections_week',
    'idx_detections_location',
)

LEGACY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_detections_common_name ON detections(common_name);
CREATE INDEX IF NOT EXISTS idx_detections_scientific_name ON detections(scientific_name);
CREATE INDEX IF NOT EXISTS idx_detections_week ON detections(week);
CREATE INDEX IF NOT EXISTS idx_detections_location ON detections(latitude, longitude);
"""


@pytest.fixture
def temp_db_path():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


def get_index_names(db_path):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


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

    def test_fresh_database_schema_is_complete(self, temp_db_path):
        """A fresh database never runs migrations, so DATABASE_SCHEMA alone
        must contain everything the migrations would have added."""
        DatabaseManager(db_path=temp_db_path)

        conn = sqlite3.connect(temp_db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(detections)")}
        conn.close()
        assert 'extra' in columns
        assert 'audio_source' in columns
        indexes = get_index_names(temp_db_path)
        for legacy in LEGACY_INDEXES:
            assert legacy not in indexes
        # The indexes that queries actually rely on are created
        assert 'idx_detections_scientific_timestamp' in indexes
        assert 'idx_detections_scientific_confidence' in indexes
        assert 'idx_detections_species_date' in indexes

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
        conn.close()

        assert get_user_version(temp_db_path) == SCHEMA_VERSION
        assert 'extra' in columns
        assert 'audio_source' in columns
        assert 'idx_detections_week' not in get_index_names(temp_db_path)

    def test_postversioning_legacy_indexes_dropped(self, temp_db_path):
        """The migration handles databases an old release left with the
        legacy indexes present and, crucially, user_version still 0 —
        versioning shipped after these indexes left the schema."""
        DatabaseManager(db_path=temp_db_path)
        conn = sqlite3.connect(temp_db_path)
        conn.executescript(LEGACY_INDEX_SQL)
        conn.execute("PRAGMA user_version = 0")
        conn.close()
        assert set(LEGACY_INDEXES) <= get_index_names(temp_db_path)

        # Next startup migrates it
        DatabaseManager(db_path=temp_db_path)

        indexes = get_index_names(temp_db_path)
        for legacy in LEGACY_INDEXES:
            assert legacy not in indexes
        assert 'idx_detections_scientific_timestamp' in indexes

    def test_reinit_is_a_noop(self, temp_db_path):
        DatabaseManager(db_path=temp_db_path)
        DatabaseManager(db_path=temp_db_path)  # second init must not raise
        assert get_user_version(temp_db_path) == SCHEMA_VERSION

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

        assert 'idx_detections_week' in get_index_names(temp_db_path)

    def test_init_creates_planner_statistics(self, temp_db_path,
                                             sample_detection):
        """Every init runs a bounded ANALYZE so the query planner has real
        statistics instead of schema-order heuristics."""
        manager = DatabaseManager(db_path=temp_db_path)
        manager.insert_detection(sample_detection)
        # Second init analyzes the now-populated table
        DatabaseManager(db_path=temp_db_path)

        conn = sqlite3.connect(temp_db_path)
        stats = conn.execute(
            "SELECT COUNT(*) FROM sqlite_stat1 WHERE tbl = 'detections'"
        ).fetchone()[0]
        conn.close()
        assert stats > 0


class TestCompositeIndexesCoverSpeciesLookups:
    """Species equality lookups must be index searches, not table scans.

    This is the property that made dropping the single-column name
    indexes safe; if a query shape regresses to SCAN, a covering index
    was lost.
    """

    @pytest.mark.parametrize('query', [
        "SELECT id FROM detections WHERE scientific_name = 'x'",
        "SELECT id FROM detections WHERE scientific_name = 'x' ORDER BY timestamp DESC",
        "SELECT id FROM detections WHERE scientific_name = 'x' ORDER BY confidence DESC",
        "SELECT id FROM detections WHERE common_name = 'x'",
        "SELECT id FROM detections WHERE common_name = 'x' AND date(timestamp) = date('2026-01-01')",
    ])
    def test_species_equality_uses_index_search(self, temp_db_path, query):
        manager = DatabaseManager(db_path=temp_db_path)

        with manager.get_db_connection() as conn:
            plan = conn.execute(f"EXPLAIN QUERY PLAN {query}").fetchall()
            details = ' | '.join(row['detail'] for row in plan)

        assert 'SEARCH detections USING' in details, details
        assert 'SCAN detections' not in details, details
