"""
Tests for the legacy-index drop migration in initialize_database.

Four indexes were removed from the schema (idx_detections_common_name,
idx_detections_scientific_name, idx_detections_week,
idx_detections_location): week/location were never queried, and the
single-column name indexes are prefix-redundant with the composite
indexes. These tests pin down that the migration drops them from
existing databases and that the composites keep serving species
equality lookups.
"""
import os
import sqlite3
import tempfile

import pytest

from core.db import DatabaseManager

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


class TestLegacyIndexMigration:

    def test_fresh_database_has_no_legacy_indexes(self, temp_db_path):
        DatabaseManager(db_path=temp_db_path)

        indexes = get_index_names(temp_db_path)
        for legacy in LEGACY_INDEXES:
            assert legacy not in indexes
        # The indexes that queries actually rely on are still created
        assert 'idx_detections_scientific_timestamp' in indexes
        assert 'idx_detections_scientific_confidence' in indexes
        assert 'idx_detections_species_date' in indexes

    def test_existing_database_legacy_indexes_dropped(self, temp_db_path):
        # Build a database the way an old release would have left it:
        # legacy indexes present and, crucially, user_version still 0 —
        # versioning shipped after these indexes were dropped from the schema.
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

    def test_migration_is_idempotent(self, temp_db_path):
        DatabaseManager(db_path=temp_db_path)
        DatabaseManager(db_path=temp_db_path)  # second init must not raise

        indexes = get_index_names(temp_db_path)
        for legacy in LEGACY_INDEXES:
            assert legacy not in indexes


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
