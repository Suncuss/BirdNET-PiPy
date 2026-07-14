"""Schema and versioned migrations for the detections database.

DATABASE_SCHEMA is the complete CURRENT shape — a fresh database gets it
via ensure_schema() and is stamped at SCHEMA_VERSION without ever running
a migration. MIGRATIONS is the append-only history that brings EXISTING
databases up to that shape, gated on ``PRAGMA user_version`` so each step
runs exactly once per database; migrations 4+ may therefore rely on true
versioned state.

Databases created before versioning existed report user_version 0 but may
already have any subset of migrations 1-3 applied (they ran as ad-hoc
state probes back then), so those three stay idempotent.
"""
from core.logging_config import get_logger

logger = get_logger(__name__)


# Canonical stored-timestamp layout: T-separated ISO-8601 at second
# precision, fixed width. Range binds (db.py _iso_ts), the migration
# importer's transform, and the fixed-offset substr() bucketing in
# _get_bird_details_from_rollup all depend on this exact layout.
TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S'


DATABASE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    group_timestamp DATETIME NOT NULL,
    scientific_name VARCHAR(100) NOT NULL,
    common_name VARCHAR(100) NOT NULL,
    confidence DECIMAL(5,4) NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    latitude DECIMAL(10,8) CHECK(latitude >= -90 AND latitude <= 90),
    longitude DECIMAL(11,8) CHECK(longitude >= -180 AND longitude <= 180),
    cutoff DECIMAL(4,3) CHECK(cutoff > 0 AND cutoff <= 1),
    sensitivity DECIMAL(4,3) CHECK(sensitivity > 0),
    overlap DECIMAL(4,3) CHECK(overlap >= 0 AND overlap <= 1),
    week INT GENERATED ALWAYS AS (strftime('%W', timestamp)) STORED,
    extra TEXT DEFAULT '{}',
    audio_source TEXT
);

CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_detections_timestamp_date ON detections(date(timestamp));
CREATE INDEX IF NOT EXISTS idx_detections_species_date ON detections(common_name, date(timestamp));
CREATE INDEX IF NOT EXISTS idx_detections_scientific_timestamp ON detections(scientific_name, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_detections_group_timestamp ON detections(group_timestamp);
CREATE INDEX IF NOT EXISTS idx_detections_scientific_confidence ON detections(scientific_name, confidence DESC);

-- Per-species rollup, fully derivable from detections (see core/db_species.py:
-- writers maintain it in-transaction; any drift triggers a startup rebuild).
CREATE TABLE IF NOT EXISTS species (
    species_key TEXT PRIMARY KEY,
    scientific_name TEXT NOT NULL,
    common_name TEXT NOT NULL,
    ebird_code TEXT,
    detection_count INTEGER NOT NULL,
    sum_confidence REAL NOT NULL,
    first_detected TEXT NOT NULL,
    last_detected TEXT NOT NULL,
    latest_id INTEGER NOT NULL
) WITHOUT ROWID;
'''


def _existing_columns(cursor):
    cursor.execute("PRAGMA table_info(detections)")
    return {row[1] for row in cursor.fetchall()}


def _add_extra_column(cursor):
    if 'extra' not in _existing_columns(cursor):
        cursor.execute("ALTER TABLE detections ADD COLUMN extra TEXT DEFAULT '{}'")
        cursor.execute("UPDATE detections SET extra = '{}' WHERE extra IS NULL")


def _add_audio_source_column(cursor):
    if 'audio_source' not in _existing_columns(cursor):
        cursor.execute("ALTER TABLE detections ADD COLUMN audio_source TEXT")


def _drop_legacy_indexes(cursor):
    # week/location were never queried; the single-column name indexes are
    # prefix-redundant with the composite indexes the planner already
    # prefers. Freed pages go to the freelist for reuse; the file only
    # shrinks on VACUUM, which we deliberately don't run here (long
    # exclusive lock, needs ~DB-size free disk).
    for index_name in ('idx_detections_common_name',
                       'idx_detections_scientific_name',
                       'idx_detections_week',
                       'idx_detections_location'):
        cursor.execute(f"DROP INDEX IF EXISTS {index_name}")


# Append-only. Never renumber or edit a shipped entry — databases in the
# field record which steps they have run via user_version.
MIGRATIONS = [
    (1, "add 'extra' column", _add_extra_column),
    (2, "add 'audio_source' column", _add_audio_source_column),
    (3, "drop unused legacy indexes", _drop_legacy_indexes),
]

SCHEMA_VERSION = MIGRATIONS[-1][0]


def ensure_schema(cursor):
    """Create or upgrade the database to the current schema.

    A genuinely fresh database (no detections table) gets DATABASE_SCHEMA
    and is stamped at SCHEMA_VERSION directly — migrations never run
    against it, so DATABASE_SCHEMA alone must stay the complete current
    shape and new migrations may rely on versioned state. An existing
    database replays the migrations newer than its user_version.

    Takes the caller's cursor rather than opening its own: a second cursor
    on the same connection hits SQLITE_LOCKED on DROP INDEX/ALTER TABLE
    whenever the first cursor still holds an un-reset statement (e.g. the
    unfetched row a PRAGMA returns). The caller owns the surrounding commit.
    """
    cursor.execute("SELECT 1 FROM sqlite_master "
                   "WHERE type='table' AND name='detections'")
    is_fresh = cursor.fetchone() is None

    cursor.executescript(DATABASE_SCHEMA)

    if is_fresh:
        cursor.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return

    cursor.execute("PRAGMA user_version")
    db_version = cursor.fetchone()[0]
    for version, description, migrate in MIGRATIONS:
        if version <= db_version:
            continue
        migrate(cursor)
        # Stamp after each step so a crash mid-sequence resumes at the
        # first unapplied one. (PRAGMA can't take bound parameters;
        # version is a literal int from MIGRATIONS.)
        cursor.execute(f"PRAGMA user_version = {version}")
        logger.info(f"Migrated database to version {version}: {description}")
