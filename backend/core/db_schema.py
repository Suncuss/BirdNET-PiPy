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
    audio_source TEXT,
    media_bytes INTEGER,
    media_nonce TEXT
);

CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC);
-- Load-bearing via its common_name PREFIX (the migration-3 single-column
-- name-index drop relied on it): legacy English-name lookups must stay
-- index searches. Its date() second column is vestigial but a replacement
-- would cost an O(n log n) startup rebuild — not worth it (M7 verdict).
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

-- Media ownership: the authoritative list of files each detection owns
-- (design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md).
-- filename PK = exclusive owner; the partial unique index makes canonical
-- (rank 0) selection per kind a database invariant, not a convention.
CREATE TABLE IF NOT EXISTS detection_media (
    filename     TEXT PRIMARY KEY,
    detection_id INTEGER NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('audio', 'spectrogram')),
    rank         INTEGER NOT NULL CHECK (rank >= 0),
    bytes        INTEGER NOT NULL CHECK (bytes >= 0)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_detection_media_det ON detection_media(detection_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_detection_media_canonical
    ON detection_media(detection_id, kind) WHERE rank = 0;

-- Durable key/value state (resolution-frontier cursor, maintenance lease,
-- rollup readiness/revision) and the rollup dirty-day repair queue.
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS rollup_dirty_day (date TEXT PRIMARY KEY) WITHOUT ROWID;

-- Time-axis rollups (core/db_rollups.py): per-day species and hour
-- aggregates, maintained in-transaction by writers, rebuilt per day-bucket
-- from detections on drift. Whole-table dashboard aggregates read these.
CREATE TABLE IF NOT EXISTS species_day (
    species_key TEXT NOT NULL,
    date TEXT NOT NULL,
    count INTEGER NOT NULL,
    sum_confidence REAL NOT NULL,
    max_confidence REAL NOT NULL,
    first_ts TEXT NOT NULL,
    last_ts TEXT NOT NULL,
    PRIMARY KEY (species_key, date)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_species_day_date ON species_day(date);

CREATE TABLE IF NOT EXISTS hour_day (
    date TEXT NOT NULL,
    hour INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (date, hour)
) WITHOUT ROWID;
'''

# Partial indexes over only the rows that still own files — the ONE list
# every consumer derives from (fresh-DB creation below, the coordinated
# build and existence gate in media_frontier). NOT part of DATABASE_SCHEMA:
# ensure_schema executes that script against EVERY database before
# migrations run, and a pre-migration-4 database has no media_bytes column
# (the statements would fail) while a migrated one would pay the O(rows)
# predicate scan during startup. Fresh databases create them at creation
# (empty table, instant); existing ones get the one-time coordinated build
# before the main container's processing threads start — idempotent per
# index, so a release that adds an entry here re-triggers the build for
# just the missing one.
#
#   idx_detections_live_media — cleanup's oldest-first candidate walk.
#   idx_detections_live_media_confidence — the bird-details 'best
#   available recordings' query (PLAYABLE_MEDIA_CLAUSE in core.db):
#   O(page) when matched rows normally own both kinds; worst case
#   O(matching live-media rows) when one-kind rows dominate (mid-import,
#   spectrogram loss) — unlike the pre-feature query, which always
#   stopped after limit+overfetch index entries. A tighter bound would
#   require denormalized playable state, not merely another partial
#   index. Deliberately coexists with the full
#   idx_detections_scientific_confidence: cleanup's keep-per-species
#   protections rank over ALL rows, file-less included.
LIVE_MEDIA_INDEXES = (
    ('idx_detections_live_media',
     "CREATE INDEX IF NOT EXISTS idx_detections_live_media "
     "ON detections(timestamp) WHERE media_bytes > 0"),
    ('idx_detections_live_media_confidence',
     "CREATE INDEX IF NOT EXISTS idx_detections_live_media_confidence "
     "ON detections(scientific_name, confidence DESC) "
     "WHERE media_bytes > 0"),
)


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


def _add_media_ownership_columns(cursor):
    # Guarded like migrations 1-2 so odd restored states (column present,
    # version stamp behind) upgrade cleanly. The detection_media/meta/
    # rollup_dirty_day tables ride DATABASE_SCHEMA's IF NOT EXISTS on every
    # startup; only the detections columns need a versioned step. The
    # partial live-media indexes are deliberately NOT created here — see
    # LIVE_MEDIA_INDEXES.
    existing = _existing_columns(cursor)
    if 'media_bytes' not in existing:
        cursor.execute("ALTER TABLE detections ADD COLUMN media_bytes INTEGER")
    if 'media_nonce' not in existing:
        cursor.execute("ALTER TABLE detections ADD COLUMN media_nonce TEXT")


def _drop_date_expression_indexes(cursor):
    # EXPLAIN-verified unused after the time-rollup conversions: trends
    # reads hour_day (sargable raw fallback off the plain timestamp index
    # when not ready) and nothing filters on bare date(timestamp) anymore.
    # idx_detections_species_date SURVIVED the same verification — its
    # common_name prefix serves legacy English-name equality lookups
    # (the migration-3 drop of the single-column name indexes depends on
    # it), so it stays despite its vestigial date() column.
    cursor.execute("DROP INDEX IF EXISTS idx_detections_timestamp_date")


# Append-only. Never renumber or edit a shipped entry — databases in the
# field record which steps they have run via user_version.
MIGRATIONS = [
    (1, "add 'extra' column", _add_extra_column),
    (2, "add 'audio_source' column", _add_audio_source_column),
    (3, "drop unused legacy indexes", _drop_legacy_indexes),
    (4, "add media ownership columns", _add_media_ownership_columns),
    (5, "drop the unused date-expression index", _drop_date_expression_indexes),
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
        # Empty table, so the partial-index predicate scans are instant here;
        # existing databases build them later, coordinated (see LIVE_MEDIA_INDEXES).
        for _name, index_sql in LIVE_MEDIA_INDEXES:
            cursor.execute(index_sql)
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
