import calendar
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from datetime import time as dt_time

# Direct submodule imports (sys.modules-resolved) rather than the
# package-attr form: the test suite evicts 'core.*' between tests but the
# 'core' package survives with stale attributes, and `from core import X`
# would bind a different module generation than the rest of the import
# graph — splitting shared state (KIND_DIRS) and exception class identity
# (MaintenanceInProgressError caught by routes).
import core.db_rollups as db_rollups
import core.db_species as db_species
import core.maintenance_lease as maintenance_lease
import core.media_ownership as media_ownership
from config.settings import DATABASE_PATH
from core.db_schema import TIMESTAMP_FORMAT, ensure_schema
from core.logging_config import get_logger
from core.storage_manager import delete_detection_files
from core.timezone_service import local_now
from core.utils import build_detection_filenames
from model_service.label_utils import same_taxon_group

# Species identity expression (owned by core.db_species alongside the
# rollup it powers); short private name for the many f-string query sites.
_SPECIES_KEY = db_species.SPECIES_KEY

# Detection fields that must never reach a public JSON payload. Exact
# coordinates pinpoint the user's station. _normalize_detection drops these so
# detection dicts are private-by-default; the api layer imports this same tuple
# for its endpoint-level guard, keeping a single source of truth. The
# authenticated CSV export builds rows from its own query
# (get_detections_for_export_batch), not _normalize_detection, so it keeps coords.
PRIVATE_DETECTION_FIELDS = ('latitude', 'longitude')


def _iso_ts(dt):
    """Render a datetime in the canonical stored-timestamp layout
    (db_schema.TIMESTAMP_FORMAT, e.g. '2026-07-12T20:54:01').

    Always bind timestamps as strings built by this helper, never as raw
    datetime objects: the sqlite3 default adapter renders datetimes
    SPACE-separated (and is deprecated since Python 3.12), so raw binds
    only compare correctly against stored T-format values by the
    lexicographic accident that 'T' sorts above ' '.
    """
    return dt.strftime(TIMESTAMP_FORMAT)


def _distribution_spec(view, anchor):
    """Chart spec for get_detection_distribution: labels, half-open
    [start, end) time range, SQL bucket expression, and a bucket->index map.

    Every view filters on a plain timestamp range so the per-species chart
    query stays index-served (idx_detections_scientific_timestamp);
    strftime()/date() run only over the in-range rows, in SELECT/GROUP BY.
    """
    if view == 'day':
        labels = [f"{i:02d}:00" for i in range(24)]
        return (labels, anchor, anchor + timedelta(days=1),
                "strftime('%H', timestamp)", int)

    if view == 'week':
        # Sunday week start, matching JavaScript's getDay() on the frontend
        week_start = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
        labels = [(week_start + timedelta(days=i)).strftime('%a %m/%d')
                  for i in range(7)]

        def to_index(bucket, _start=week_start):
            return (datetime.strptime(bucket, '%Y-%m-%d') - _start).days
        return (labels, week_start, week_start + timedelta(days=7),
                "date(timestamp)", to_index)

    if view == 'month':
        num_days = calendar.monthrange(anchor.year, anchor.month)[1]
        labels = [str(i) for i in range(1, num_days + 1)]
        start = anchor.replace(day=1)
        end = datetime(anchor.year + (anchor.month == 12),
                       anchor.month % 12 + 1, 1)
        return (labels, start, end,
                "strftime('%d', timestamp)", lambda b: int(b) - 1)

    if view == '6month':
        start_month = 1 if anchor.month <= 6 else 7
        labels = [datetime(anchor.year, start_month + i, 1).strftime('%b')
                  for i in range(6)]
        start = datetime(anchor.year, start_month, 1)
        end = (datetime(anchor.year, 7, 1) if start_month == 1
               else datetime(anchor.year + 1, 1, 1))
        return (labels, start, end,
                "strftime('%m', timestamp)", lambda b: int(b) - start_month)

    if view == 'year':
        labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        return (labels, datetime(anchor.year, 1, 1),
                datetime(anchor.year + 1, 1, 1),
                "strftime('%m', timestamp)", lambda b: int(b) - 1)

    raise ValueError(
        "Invalid view. Use 'day', 'week', 'month', '6month', or 'year'.")


# What _build_detection_filters emits when no filters apply. Callers embed
# it in `WHERE {clause}` compositions; _count_query keys its fast path on
# it — one shared constant so the contract can't silently drift.
_NO_FILTERS = "1=1"


def _count_query(where_clause):
    """COUNT query for a filter set. An unfiltered count omits the WHERE
    entirely so SQLite serves it from the b-tree row counter instead of
    walking a million-entry covering index (14ms vs 36ms measured)."""
    if where_clause == _NO_FILTERS:
        return "SELECT COUNT(*) as total FROM detections"
    return f"SELECT COUNT(*) as total FROM detections WHERE {where_clause}"


def _normalize_species_keys(scientific_name):
    """Normalize the ``scientific_name`` filter arg to a de-duplicated list.

    Accepts a single key, a sequence of keys (an ambiguous common name maps to
    more than one after a taxonomy split), or None/empty. Order is preserved so
    the caller's representative-first ordering survives.
    """
    if not scientific_name:
        return []
    if isinstance(scientific_name, str):
        return [scientific_name]
    seen = []
    for key in scientific_name:
        if key and key not in seen:
            seen.append(key)
    return seen


def _resolve_filter_column(species_name=None, *, scientific_name=None):
    """Resolve a (column, values) pair for species-keyed WHERE clauses.

    Routes resolve their English input through the species table at ingress
    and pass ``scientific_name=`` when known — a single key, or a list of keys
    that denote the same species under duplicate common names in the model
    label set. Legacy or unknown names fall back to ``common_name`` so migrated
    rows stay accessible. ``values`` is always a list; returns ``(None, [])``
    when no species filter was supplied.
    """
    keys = _normalize_species_keys(scientific_name)
    if keys:
        return 'scientific_name', keys
    if species_name:
        return 'common_name', [species_name]
    return None, []


def _species_where(column, values):
    """Build a ``(clause, params)`` fragment for a species-column filter.

    Emits ``col IN (…)``; SQLite folds a single-element IN list to an equality
    seek, so the ~99% one-key case keeps the same covering-index plan a literal
    ``col = ?`` would give. Multi-key filters do give up the index-ordered scan
    under ``ORDER BY … LIMIT`` (a temp B-tree sort), which is acceptable only
    because the ambiguous species are a known-small set.

    Raises on an empty list: ``col IN ()`` is accepted by SQLite as always-false
    and would silently return no rows — a blank page rather than a loud failure.
    """
    if not values:
        raise ValueError(f"_species_where({column!r}) needs at least one value")
    placeholders = ", ".join("?" * len(values))
    return f"{column} IN ({placeholders})", list(values)


def _summary_stats_bucket(total, unique, hour, most_key, rare_key, names):
    """Build the 7-key summary-stats dict shared by the per-period and
    all-periods queries. ``names`` maps a species key to its resolved
    ``(common, scientific)`` name pair."""
    def display(key):
        if not key:
            return "N/A", ""
        return names.get(key, ("N/A", ""))

    most_common, most_sci = display(most_key)
    rarest_common, rarest_sci = display(rare_key)
    return {
        'totalObservations': total or 0,
        'uniqueSpecies': unique or 0,
        'mostActiveHour': f"{hour}:00" if hour else "N/A",
        'mostCommonSpecies': most_common or "N/A",
        'mostCommonSpeciesScientificName': most_sci or "",
        'rarestSpecies': rarest_common or "N/A",
        'rarestSpeciesScientificName': rarest_sci or "",
    }


# Create a custom logger adapter that adds a prefix to all messages
class DBLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[DB] {msg}", kwargs

# Use the existing logger hierarchy with adapter
_base_logger = get_logger(__name__)
logger = DBLoggerAdapter(_base_logger, {})

class DatabaseManager:

    def __init__(self, db_path=DATABASE_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self.ensure_db_directory_exists()
        self.initialize_database()
        logger.info("DatabaseManager initialized", extra={
            'database_path': self.db_path
        })

    def ensure_db_directory_exists(self):
        db_directory = os.path.dirname(self.db_path)
        if not os.path.exists(db_directory):
            os.makedirs(db_directory)

    def _open_connection(self):
        # busy_timeout: with WAL plus multiple connections (executor lane +
        # main pipeline), readers and writers can momentarily contend. Wait
        # up to 30s for the lock rather than failing fast with SQLITE_BUSY.
        # synchronous=NORMAL: skip fsync per transaction; sqlite still
        # syncs on WAL checkpoint. Cannot corrupt the DB, but a power loss
        # can drop the last few committed detections. Acceptable for this
        # app — detections are continuous and eventual-consistency-tolerant.
        # cache_size (8MB) and mmap_size (128MB, file-backed so the kernel
        # reclaims it under memory pressure) only pay off because the
        # connection is long-lived — hot index pages survive between
        # requests instead of being re-read from SD flash on every query.
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row  # This line ensures we get dictionaries instead of tuples
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = -8192")
        conn.execute("PRAGMA mmap_size = 134217728")
        return conn

    @contextmanager
    def get_db_connection(self):
        """Thread-local long-lived connection, opened lazily per thread.

        Each ``with`` block is a logical unit: anything left uncommitted
        when the block exits is rolled back, so state never leaks into the
        next use of the shared connection. An exception inside the block
        discards the connection entirely (its state is suspect — could be
        a disk-level error) and the next call reopens fresh.

        Nesting on the same thread yields the same connection, so an inner
        block's commit also commits the outer's pending writes, and an
        inner block's exception discards the connection out from under the
        outer. Don't hold a block open across calls into other db methods;
        acquire per operation instead (contexts are cheap after the first).
        """
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = self._open_connection()
            self._local.conn = conn
        try:
            yield conn
        except Exception:
            self._local.conn = None
            try:
                conn.close()  # implicitly rolls back anything pending
            except Exception:
                pass
            raise
        finally:
            if getattr(self._local, 'conn', None) is conn and conn.in_transaction:
                conn.rollback()

    def initialize_database(self):
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            # journal_mode=WAL is a database-level property persisted into
            # the DB file; setting it once at init is sufficient. WAL lets
            # readers run concurrently with a writer (and with each other),
            # which is the main reason we can safely move DB work onto a
            # separate executor lane without serializing every read.
            # synchronous and busy_timeout are per-connection, set in
            # get_db_connection() — no value in setting them here on a
            # connection that's about to be closed.
            cursor.execute("PRAGMA journal_mode = WAL")
            ensure_schema(cursor)

            # Self-heal the species rollup: anything that wrote detections
            # without maintaining it (bulk import, a pre-rollup backup)
            # shows up as a count mismatch and triggers a rebuild here.
            db_species.ensure_consistent(cursor)

            # Refresh planner statistics. Without sqlite_stat1 every plan
            # comes from schema-order heuristics, which can flip badly as
            # data distribution shifts. analysis_limit bounds the work by
            # sampling (~0.01s on a 1M-row DB), cheap enough to run at every
            # startup — which also keeps stats current as the table grows.
            # (PRAGMA optimize is NOT a substitute here: it only considers
            # tables the current connection has already queried, so on a
            # fresh init connection it is a no-op.)
            cursor.execute("PRAGMA analysis_limit = 1000")
            cursor.execute("ANALYZE")
            conn.commit()

    def rebuild_species_table(self):
        """Recompute the species rollup from detections. For writers that
        bypass insert_detection (the BirdNET-Pi bulk import)."""
        with self.get_db_connection() as conn:
            db_species.rebuild(conn.cursor())
            conn.commit()

    def open_readonly_connection(self):
        """Fresh read-only connection, bypassing the thread-local cache.

        For probes that must observe the actual database file — e.g. the
        integrity check, which would otherwise read pages a warm connection
        cached before any damage, and must not CREATE a missing file the
        way a default-mode connect silently does. Caller closes it.
        """
        return sqlite3.connect(f"file:{self.db_path}?mode=ro",
                               uri=True, timeout=30)

    def database_exists(self):
        with self.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='detections'")
            return cursor.fetchone() is not None

    def insert_detection(self, detection):
        # Handle extra field - default to empty JSON object
        extra = detection.get('extra', {})
        if extra is None:
            extra = {}
        if isinstance(extra, dict):
            extra_dict = extra
            extra = json.dumps(extra)
        else:
            extra_dict = self._parse_extra(extra)

        query = """
        INSERT INTO detections (timestamp, group_timestamp, scientific_name, common_name, confidence,
                                latitude, longitude, cutoff, sensitivity, overlap, extra, audio_source,
                                media_bytes, media_nonce)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (
                detection['timestamp'],
                detection['group_timestamp'],
                detection['scientific_name'],
                detection['common_name'],
                detection['confidence'],
                detection['latitude'],
                detection['longitude'],
                detection['cutoff'],
                detection['sensitivity'],
                detection['overlap'],
                extra,
                detection.get('audio_source'),
                # Row-first creation: born resolved-and-empty (0, not NULL —
                # NULL would expose the row to the legacy frontier walk),
                # with its media identity persisted before any file exists.
                0,
                media_ownership.mint_media_nonce()
            ))
            detection_id = cur.lastrowid
            # Same transaction: the species and time rollups can never
            # disagree with a committed detection.
            db_species.apply_insert(cur, detection, detection_id, extra_dict)
            db_rollups.apply_insert(cur, detection)
            conn.commit()
            return detection_id

    def get_rollup_revision(self):
        """Cache-validation revision: bumped by every rollup ready/dirty
        transition in any process (durable in meta)."""
        with self.get_db_connection() as conn:
            return db_rollups.get_revision(conn.cursor())

    def get_media_nonce(self, detection_id):
        """The row's persisted media identity (None for legacy rows)."""
        with self.get_db_connection() as conn:
            row = conn.execute(
                "SELECT media_nonce FROM detections WHERE id = ?",
                (detection_id,)).fetchone()
            return row['media_nonce'] if row else None

    def get_or_create_media_nonce(self, detection_id):
        """The row's nonce, lazily initializing legacy NULL rows in one
        transaction (importer Stages 2/3 call this before publishing media
        for rows created by older code). Raises DetectionMissingError for
        a deleted row — before any file could be published against it."""
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            nonce = media_ownership.get_or_create_media_nonce(cur, detection_id)
            conn.commit()
            return nonce

    def get_media_owner(self, filename):
        """The detection_id owning this filename, or None if unowned."""
        with self.get_db_connection() as conn:
            row = conn.execute(
                "SELECT detection_id FROM detection_media WHERE filename = ?",
                (filename,)).fetchone()
            return row['detection_id'] if row else None

    def record_detection_media(self, detection_id, files):
        """Record ownership of published files in one transaction.

        BEGIN IMMEDIATE first: the writer lock is held before the
        detection-existence check, so a concurrent delete cannot commit
        between the check and the ownership inserts (the schema has no FK
        to catch a ghost row — the lock IS the guarantee; implementation
        review finding 2). Raises media_ownership.DetectionMissingError if
        a delete already won — the caller must remove the files it just
        published.
        """
        with self.get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.cursor()
                media_ownership.record_media(cur, detection_id, files)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def get_latest_detections(self, limit=15, unique=False):
        if limit <= 0:
            return []

        # Use window function to deduplicate detections.
        # unique=False (default): highest confidence per (group_timestamp, species_key)
        # unique=True: most recent detection per species (one row per species_key)
        if unique:
            # The species rollup already tracks each species' newest
            # detection — a LIMIT-sized read replaces what used to be a
            # windowed dedup with doubling prefetch windows and a
            # full-table-scan fallback (measured at 2.4s when a few noisy
            # species dominated the recent window).
            rows = self._fetch_latest_unique_by_species(limit)
        else:
            rows = self._fetch_deduplicated(limit)

        detections = self._normalize_detections(rows, include_filenames=True)
        for detection in detections:
            # Use legacy field names for backward compatibility with frontend
            detection['bird_song_file_name'] = detection.pop('audio_filename')
            detection['spectrogram_file_name'] = detection.pop('spectrogram_filename')

        return detections

    def _fetch_deduplicated(self, limit):
        """Latest detections, keeping the highest-confidence row per
        (group_timestamp, species_key, audio_source).

        Partitioning on the species key (scientific_name with a
        common_name fallback for blank-sci legacy rows) merges V2/V3
        model history for the same species into one entry. The window
        function runs over a recent prefetch instead of the full table
        (376K+ rows → 1000ms down to ~1ms).
        """
        pre_fetch = limit * 50
        query = f"""
        SELECT
            id,
            timestamp,
            group_timestamp,
            scientific_name,
            common_name,
            confidence,
            latitude,
            longitude,
            cutoff,
            sensitivity,
            overlap,
            week,
            extra,
            audio_source,
            media_bytes
        FROM detections
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY group_timestamp, {_SPECIES_KEY}, audio_source
                    ORDER BY confidence DESC
                ) as rn
                FROM (SELECT * FROM detections
                      ORDER BY timestamp DESC, id DESC LIMIT {pre_fetch})
            ) WHERE rn = 1
        )
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (limit,))
            return cur.fetchall()

    def _fetch_latest_unique_by_species(self, limit):
        """Each species' newest detection, newest species first — a
        LIMIT-sized read off the species rollup joined back by latest_id."""
        query = """
        SELECT d.*
        FROM (
            SELECT latest_id FROM species
            ORDER BY last_detected DESC, latest_id DESC
            LIMIT ?
        ) s
        JOIN detections d ON d.id = s.latest_id
        ORDER BY d.timestamp DESC, d.id DESC
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (limit,))
            return cur.fetchall()

    def get_detections_by_date_range(self, start_date, end_date, unique=False):
        start_time = time.time()

        # Convert dates to ISO 8601 format
        start_date_iso = datetime.strptime(start_date, '%Y-%m-%d').strftime('%Y-%m-%dT00:00:00')
        end_date_iso = datetime.strptime(end_date, '%Y-%m-%d').strftime('%Y-%m-%dT23:59:59')

        logger.debug("Fetching detections by date range", extra={
            'start_date': start_date,
            'end_date': end_date,
            'unique_only': unique
        })

        if unique:
            # Partition by the species key so V2/V3 English variants of the
            # same species collapse into one representative row, while legacy
            # rows with blank scientific_name fall back to common_name and
            # stay separate from one another.
            query = f"""
            WITH RankedDetections AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY {_SPECIES_KEY}
                        ORDER BY confidence DESC, timestamp DESC
                    ) AS rn
                FROM detections
                WHERE timestamp BETWEEN ? AND ?
            )
            SELECT
                *
            FROM RankedDetections
            WHERE rn = 1
            ORDER BY timestamp DESC;
            """
        else:
            query = """
            SELECT * FROM detections
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp DESC
            """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            if unique:
                cur.execute(query, (start_date_iso, end_date_iso))
            else:
                cur.execute(query, (start_date_iso, end_date_iso))

            rows = cur.fetchall()
            results = []
            for row in rows:
                detection = dict(row)
                detection['extra'] = self._parse_extra(detection.get('extra'))
                results.append(detection)

            query_time = time.time() - start_time
            logger.debug("Date range query completed", extra={
                'results_count': len(results),
                'query_time': round(query_time, 3)
            })

            return results

    def get_hourly_activity(self, date=None):
        if date:
            start_of_day = datetime.strptime(date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_of_day = local_now().replace(hour=0, minute=0, second=0, microsecond=0)

        end_of_day = start_of_day + timedelta(days=1)

        # Half-open range: a detection at exactly the next midnight belongs
        # to the next day, not to both.
        query = """
        SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
        FROM detections
        WHERE timestamp >= ? AND timestamp < ?
        GROUP BY hour
        ORDER BY hour
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (_iso_ts(start_of_day), _iso_ts(end_of_day)))
            results = cur.fetchall()

        hourly_activity = {f"{hour:02d}": 0 for hour in range(24)}
        for row in results:
            hourly_activity[row['hour']] = row['count']

        return [{'hour': f"{hour}:00", 'count': count} for hour, count in hourly_activity.items()]

    def _species_activity_for_day(self, date=None):
        """Per-species hourly activity for one day, unsorted.

        GROUP BY the species key so that mixed V2/V3 English variants of the
        same species merge into one row. A representative common_name comes
        along for display; the API layer resolves the localized name from
        the stable scientific_name key. The MAX(scientific_name) gives the
        row's representative sci_name — for non-legacy data this is the
        constant non-empty value; for blank-sci legacy groups it's ''.
        """
        if date:
            start_of_day = datetime.strptime(date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_of_day = local_now().replace(hour=0, minute=0, second=0, microsecond=0)

        end_of_day = start_of_day + timedelta(days=1)

        query = f"""
        SELECT {_SPECIES_KEY} AS species_key,
               MAX(scientific_name) AS scientific_name,
               MIN(common_name) AS common_name,
               strftime('%H', timestamp) as hour,
               COUNT(*) as count
        FROM detections
        WHERE timestamp >= ? AND timestamp < ?
        GROUP BY species_key, hour
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (_iso_ts(start_of_day), _iso_ts(end_of_day)))
            results = cur.fetchall()

        species_hourly_activity = {}
        for row in results:
            entry = species_hourly_activity.get(row['species_key'])
            if entry is None:
                entry = {
                    'scientific_name': row['scientific_name'] or '',
                    'common_name': row['common_name'],
                    'hourly': [0] * 24,
                }
                species_hourly_activity[row['species_key']] = entry
            entry['hourly'][int(row['hour'])] = row['count']

        return [
            {
                'scientific_name': entry['scientific_name'],
                'species': entry['common_name'],
                'hourlyActivity': entry['hourly'],
                'totalObservations': sum(entry['hourly']),
            }
            for entry in species_hourly_activity.values()
        ]

    def get_activity_overview(self, date=None, order='most'):
        species_activity = self._species_activity_for_day(date)
        species_activity.sort(key=lambda x: x['totalObservations'],
                              reverse=(order != 'least'))

        logger.debug("Activity overview generated", extra={
            'total_species': len(species_activity),
            'returned_species': len(species_activity)
        })
        return species_activity

    def get_activity_overview_both(self, date=None, *, num_species):
        # num_species is required so the caller (the dashboard route) stays
        # the single owner of the cap.
        species_activity = self._species_activity_for_day(date)
        most = sorted(species_activity, key=lambda x: x['totalObservations'],
                      reverse=True)[:num_species]
        least = sorted(species_activity,
                       key=lambda x: x['totalObservations'])[:num_species]

        logger.debug("Activity overview (both) generated", extra={
            'total_species': len(species_activity),
            'returned_species': num_species
        })
        return {'most': most, 'least': least}

    def get_summary_stats_all_periods(self, today_start, week_start, month_start):
        """Compute today/week/month/allTime summary stats in one query.

        Replaces what used to be 4 sequential per-period calls. Each per-period
        bucket has the same 7-key shape: totalObservations, uniqueSpecies,
        mostActiveHour, mostCommonSpecies, mostCommonSpeciesScientificName,
        rarestSpecies, rarestSpeciesScientificName.

        Species are grouped by the species key (scientific_name with a
        common_name fallback for legacy rows) so V2/V3 English drift
        collapses but unrelated blank-sci rows do not.

        The `WHERE c_<period> > 0` filters in the species and hour selects
        are load-bearing — without them a period with no detections would
        return the all-time top species/hour (since the per-period count
        would be 0 but the row still exists in species_counts/hourly_per_period).

        Served from the time rollups when ready (single-snapshot contract:
        readiness and data in one read transaction); raw CTE fallback below.
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN")
            try:
                if db_rollups.rollups_ready(cur):
                    now_dt = local_now()
                    now_iso = now_dt.isoformat()
                    buckets = {}
                    names = {}
                    for label, start in (
                            ('today', today_start), ('week', week_start),
                            ('month', month_start), ('allTime', datetime.min)):
                        if self._rollups_can_serve_period(start):
                            total, unique, hour, most_key, rare_key = \
                                self._summary_bucket_from_rollups(
                                    cur, start.strftime('%Y-%m-%d'), now_dt)
                        else:
                            # Rolling windows keep exact time-of-day bounds
                            # via a cheap bounded raw range scan.
                            total, unique, hour, most_key, rare_key = \
                                self._raw_summary_bucket(
                                    cur, start.isoformat(), now_iso)
                        for key in (most_key, rare_key):
                            if key and key not in names:
                                names[key] = self._get_species_display_name(cur, key)
                        buckets[label] = _summary_stats_bucket(
                            total, unique, hour, most_key, rare_key, names)
                    return buckets
            finally:
                conn.commit()

        now = local_now().isoformat()
        params = {
            'all_time_start': datetime.min.isoformat(),
            'now': now,
            'today_start': today_start.isoformat(),
            'week_start': week_start.isoformat(),
            'month_start': month_start.isoformat(),
        }

        with self.get_db_connection() as conn:
            cur = conn.cursor()

            logger.debug("Calculating summary stats for all periods", extra={
                'today_start': params['today_start'][:10],
                'week_start': params['week_start'][:10],
                'month_start': params['month_start'][:10],
                'now': now[:10],
            })

            query = f"""
            WITH filtered_detections AS (
                SELECT id, scientific_name, common_name, timestamp
                FROM detections
                WHERE timestamp BETWEEN :all_time_start AND :now
            ),
            counts AS (
                SELECT
                    COUNT(*) AS total_all,
                    SUM(CASE WHEN timestamp >= :today_start THEN 1 ELSE 0 END) AS total_today,
                    SUM(CASE WHEN timestamp >= :week_start  THEN 1 ELSE 0 END) AS total_week,
                    SUM(CASE WHEN timestamp >= :month_start THEN 1 ELSE 0 END) AS total_month,
                    COUNT(DISTINCT {_SPECIES_KEY}) AS unique_all,
                    COUNT(DISTINCT CASE WHEN timestamp >= :today_start THEN {_SPECIES_KEY} END) AS unique_today,
                    COUNT(DISTINCT CASE WHEN timestamp >= :week_start  THEN {_SPECIES_KEY} END) AS unique_week,
                    COUNT(DISTINCT CASE WHEN timestamp >= :month_start THEN {_SPECIES_KEY} END) AS unique_month
                FROM filtered_detections
            ),
            hourly_per_period AS (
                SELECT strftime('%H', timestamp) AS hour,
                       SUM(CASE WHEN timestamp >= :today_start THEN 1 ELSE 0 END) AS c_today,
                       SUM(CASE WHEN timestamp >= :week_start  THEN 1 ELSE 0 END) AS c_week,
                       SUM(CASE WHEN timestamp >= :month_start THEN 1 ELSE 0 END) AS c_month,
                       COUNT(*) AS c_all
                FROM filtered_detections
                GROUP BY hour
            ),
            -- Secondary ORDER BY key makes ties deterministic. Without it,
            -- two hours/species at the same count would flap call-to-call
            -- depending on plan choices.
            hour_today AS (SELECT hour FROM hourly_per_period WHERE c_today > 0 ORDER BY c_today DESC, hour ASC LIMIT 1),
            hour_week  AS (SELECT hour FROM hourly_per_period WHERE c_week  > 0 ORDER BY c_week  DESC, hour ASC LIMIT 1),
            hour_month AS (SELECT hour FROM hourly_per_period WHERE c_month > 0 ORDER BY c_month DESC, hour ASC LIMIT 1),
            hour_all   AS (SELECT hour FROM hourly_per_period WHERE c_all   > 0 ORDER BY c_all   DESC, hour ASC LIMIT 1),
            species_counts AS (
                SELECT {_SPECIES_KEY} AS species_key,
                       SUM(CASE WHEN timestamp >= :today_start THEN 1 ELSE 0 END) AS c_today,
                       SUM(CASE WHEN timestamp >= :week_start  THEN 1 ELSE 0 END) AS c_week,
                       SUM(CASE WHEN timestamp >= :month_start THEN 1 ELSE 0 END) AS c_month,
                       COUNT(*) AS c_all
                FROM filtered_detections
                GROUP BY species_key
            ),
            most_today AS (SELECT species_key FROM species_counts WHERE c_today > 0 ORDER BY c_today DESC, species_key ASC LIMIT 1),
            rare_today AS (SELECT species_key FROM species_counts WHERE c_today > 0 ORDER BY c_today ASC,  species_key ASC LIMIT 1),
            most_week  AS (SELECT species_key FROM species_counts WHERE c_week  > 0 ORDER BY c_week  DESC, species_key ASC LIMIT 1),
            rare_week  AS (SELECT species_key FROM species_counts WHERE c_week  > 0 ORDER BY c_week  ASC,  species_key ASC LIMIT 1),
            most_month AS (SELECT species_key FROM species_counts WHERE c_month > 0 ORDER BY c_month DESC, species_key ASC LIMIT 1),
            rare_month AS (SELECT species_key FROM species_counts WHERE c_month > 0 ORDER BY c_month ASC,  species_key ASC LIMIT 1),
            most_all   AS (SELECT species_key FROM species_counts WHERE c_all   > 0 ORDER BY c_all   DESC, species_key ASC LIMIT 1),
            rare_all   AS (SELECT species_key FROM species_counts WHERE c_all   > 0 ORDER BY c_all   ASC,  species_key ASC LIMIT 1)
            SELECT
                (SELECT total_today  FROM counts) AS total_today,
                (SELECT total_week   FROM counts) AS total_week,
                (SELECT total_month  FROM counts) AS total_month,
                (SELECT total_all    FROM counts) AS total_all,
                (SELECT unique_today FROM counts) AS unique_today,
                (SELECT unique_week  FROM counts) AS unique_week,
                (SELECT unique_month FROM counts) AS unique_month,
                (SELECT unique_all   FROM counts) AS unique_all,
                (SELECT hour FROM hour_today) AS hour_today,
                (SELECT hour FROM hour_week)  AS hour_week,
                (SELECT hour FROM hour_month) AS hour_month,
                (SELECT hour FROM hour_all)   AS hour_all,
                (SELECT species_key FROM most_today) AS most_today_key,
                (SELECT species_key FROM rare_today) AS rare_today_key,
                (SELECT species_key FROM most_week)  AS most_week_key,
                (SELECT species_key FROM rare_week)  AS rare_week_key,
                (SELECT species_key FROM most_month) AS most_month_key,
                (SELECT species_key FROM rare_month) AS rare_month_key,
                (SELECT species_key FROM most_all)   AS most_all_key,
                (SELECT species_key FROM rare_all)   AS rare_all_key
            """

            cur.execute(query, params)
            row = cur.fetchone()
            selected_species_names = {}
            if row is not None:
                selected_keys = {
                    row[f'{kind}_{period}_key']
                    for period in ('today', 'week', 'month', 'all')
                    for kind in ('most', 'rare')
                    if row[f'{kind}_{period}_key']
                }
                selected_species_names = {
                    species_key: self._get_species_display_name(
                        cur, species_key)
                    for species_key in selected_keys
                }

        if row is None:
            empty = _summary_stats_bucket(0, 0, None, None, None, {})
            return {key: dict(empty) for key in ('today', 'week', 'month', 'allTime')}

        return {
            'today': _summary_stats_bucket(
                row['total_today'], row['unique_today'], row['hour_today'],
                row['most_today_key'], row['rare_today_key'], selected_species_names,
            ),
            'week': _summary_stats_bucket(
                row['total_week'], row['unique_week'], row['hour_week'],
                row['most_week_key'], row['rare_week_key'], selected_species_names,
            ),
            'month': _summary_stats_bucket(
                row['total_month'], row['unique_month'], row['hour_month'],
                row['most_month_key'], row['rare_month_key'], selected_species_names,
            ),
            'allTime': _summary_stats_bucket(
                row['total_all'], row['unique_all'], row['hour_all'],
                row['most_all_key'], row['rare_all_key'], selected_species_names,
            ),
        }

    @staticmethod
    def _rollups_can_serve_period(period_start):
        """Rollups aggregate whole days, so they can only stand in for a
        raw query whose lower bound is a midnight (today, allTime, or any
        calendar-aligned start). The rolling week/month windows carry a
        time-of-day boundary — serving those from day buckets would
        over-include the boundary day's pre-cutoff rows (implementation
        review finding 1) — and their raw scans are cheap 7/30-day index
        ranges anyway."""
        return period_start.time() == dt_time.min

    def _summary_bucket_from_rollups(self, cur, start_date, now):
        """(total, unique, hour, most_key, rare_key) for [start_date..now]
        with EXACT raw semantics: whole days strictly before today come
        from the rollups (O(rollup rows)); today is a raw
        [midnight..now] slice (one day of rows), merged in Python. That
        keeps the `timestamp <= now` upper bound the raw path has — a
        date-only bound would admit a same-day future timestamp
        (implementation re-review R3). Only valid for midnight-aligned
        starts (_rollups_can_serve_period). ``now`` is the CALLER'S clock
        — one temporal boundary per request; a second local_now() here
        could cross midnight against the caller's raw buckets (second
        re-review S2). Hours are 2-digit strings to match the raw path's
        strftime('%H') (an int 0 would falsy-collapse midnight to N/A in
        the bucket)."""
        today = now.strftime('%Y-%m-%d')
        species = {}
        hours = {}
        cur.execute(
            "SELECT species_key, SUM(count) FROM species_day "
            "WHERE date >= ? AND date < ? GROUP BY species_key",
            (start_date, today))
        for key, count in cur.fetchall():
            species[key] = species.get(key, 0) + count
        cur.execute(
            "SELECT printf('%02d', hour), SUM(count) FROM hour_day "
            "WHERE date >= ? AND date < ? GROUP BY hour",
            (start_date, today))
        for hour, count in cur.fetchall():
            hours[hour] = hours.get(hour, 0) + count
        # Today's raw slice, bounded at now exactly like the raw path.
        cur.execute(
            f"SELECT {_SPECIES_KEY} AS sk, COUNT(*) FROM detections "
            f"WHERE timestamp >= ? AND timestamp <= ? GROUP BY sk",
            (f"{today}T00:00:00", now.isoformat()))
        for key, count in cur.fetchall():
            species[key] = species.get(key, 0) + count
        cur.execute(
            "SELECT strftime('%H', timestamp) AS h, COUNT(*) FROM detections "
            "WHERE timestamp >= ? AND timestamp <= ? GROUP BY h",
            (f"{today}T00:00:00", now.isoformat()))
        for hour, count in cur.fetchall():
            hours[hour] = hours.get(hour, 0) + count

        total = sum(species.values())
        unique = len(species)
        # Tie semantics mirror the raw ORDER BY clauses exactly:
        # count DESC/ASC, then key ASC.
        hour = min(hours.items(), key=lambda kv: (-kv[1], kv[0]))[0] \
            if hours else None
        most_key = min(species.items(), key=lambda kv: (-kv[1], kv[0]))[0] \
            if species else None
        rare_key = min(species.items(), key=lambda kv: (kv[1], kv[0]))[0] \
            if species else None
        return total, unique, hour, most_key, rare_key

    def _raw_summary_bucket(self, cur, period_start_iso, now_iso):
        """(total, unique, hour, most_key, rare_key) for one period from the
        raw event log — exact time-of-day boundaries. Cheap for the rolling
        week/month windows (bounded index range); allTime's full scan is
        what the rollup path exists to avoid."""
        query = f"""
        WITH filtered_detections AS (
            SELECT scientific_name, common_name, timestamp
            FROM detections
            WHERE timestamp BETWEEN :period_start AND :now
        ),
        hourly_counts AS (
            SELECT strftime('%H', timestamp) AS hour, COUNT(*) AS c
            FROM filtered_detections GROUP BY hour
        ),
        species_counts AS (
            SELECT {_SPECIES_KEY} AS species_key, COUNT(*) AS c
            FROM filtered_detections GROUP BY species_key
        )
        SELECT
            (SELECT COUNT(*) FROM filtered_detections) AS total,
            (SELECT COUNT(DISTINCT {_SPECIES_KEY}) FROM filtered_detections) AS unique_species,
            (SELECT hour FROM hourly_counts ORDER BY c DESC, hour ASC LIMIT 1) AS hour,
            (SELECT species_key FROM species_counts ORDER BY c DESC, species_key ASC LIMIT 1) AS most_key,
            (SELECT species_key FROM species_counts ORDER BY c ASC, species_key ASC LIMIT 1) AS rare_key
        """
        cur.execute(query, {'period_start': period_start_iso, 'now': now_iso})
        row = cur.fetchone()
        if row is None:
            return 0, 0, None, None, None
        return (row['total'] or 0, row['unique_species'] or 0,
                row['hour'], row['most_key'], row['rare_key'])

    def get_summary_stats_for_period(self, period_start, now=None):
        """Compute summary stats for one dashboard period.

        Dashboard only shows one summary tab at a time. This period-specific
        query lets the initial page load pay for the visible period instead
        of always scanning the all-time history for hidden tabs.

        Served from the time rollups when they are ready — readiness and
        the data queries share ONE read transaction, so "queue empty" and
        "rollup contents" can never disagree (single-snapshot contract).
        Unready rollups fall back to the raw CTE scan below.
        """
        now_dt = now or local_now()
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN")
            try:
                if (self._rollups_can_serve_period(period_start)
                        and db_rollups.rollups_ready(cur)):
                    total, unique, hour, most_key, rare_key = \
                        self._summary_bucket_from_rollups(
                            cur, period_start.strftime('%Y-%m-%d'), now_dt)
                    names = {
                        key: self._get_species_display_name(cur, key)
                        for key in {most_key, rare_key} if key
                    }
                    return _summary_stats_bucket(
                        total, unique, hour, most_key, rare_key, names)
            finally:
                conn.commit()

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            total, unique, hour, most_key, rare_key = \
                self._raw_summary_bucket(
                    cur, period_start.isoformat(), now_dt.isoformat())
            names = {
                key: self._get_species_display_name(cur, key)
                for key in {most_key, rare_key} if key
            }
        return _summary_stats_bucket(
            total, unique, hour, most_key, rare_key, names)

    def _get_species_display_name(self, cur, species_key):
        """(common, scientific) display names for a summary species key —
        a primary-key rollup read; its common_name is already newest-wins."""
        cur.execute("SELECT common_name, scientific_name FROM species "
                    "WHERE species_key = ?", (species_key,))
        row = cur.fetchone()
        if row is None:
            return "N/A", ""
        return row['common_name'] or "N/A", row['scientific_name'] or ""

    def get_species_sightings(self, limit=10, most_frequent=True):
        # Top-N species by detection_count straight off the rollup, joined
        # back by latest_id for each species' newest detection row.
        order = 'DESC' if most_frequent else 'ASC'
        query = f"""
        SELECT d.*
        FROM (
            SELECT detection_count, latest_id FROM species
            ORDER BY detection_count {order}, species_key ASC
            LIMIT ?
        ) s
        JOIN detections d ON d.id = s.latest_id
        ORDER BY s.detection_count {order}, d.timestamp DESC
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (limit,))
            return [
                self._normalize_detection(row, include_filenames=False)
                for row in cur.fetchall()
            ]



    def get_bird_details(self, species_name=None, *, scientific_name=None):
        """Aggregate detection details for a species.

        ``scientific_name`` is preferred — it merges V2/V3 English variants
        (e.g. "Eurasian Blackbird" + "Common Blackbird" both Turdus merula)
        into one detail record and is served off the species rollup. It may be
        a single key or a list of keys the model duplicates under one common
        name (a taxonomy split); all are aggregated into one record.
        ``species_name`` keeps the legacy English filter (and its original
        full-scan query) for routes where the resolver couldn't map the
        input string.
        """
        keys = _normalize_species_keys(scientific_name)
        if keys:
            return self._get_bird_details_from_rollup(keys)
        if not species_name:
            return None

        ebird = db_species.ebird_expr('d3.')
        # No GROUP BY: one record for the whole common name. Grouping by
        # scientific_name and taking fetchone() reported only one arbitrary
        # group when a common name spans several scientific names, so a
        # migrated row set split across a genus rename under-counted itself.
        # scientific_name is therefore an explicit most-detected representative
        # rather than a bare column picked from an arbitrary row.
        query = f"""
        SELECT
            MIN(common_name) AS common_name,
            (SELECT d4.scientific_name
            FROM detections d4
            WHERE d4.common_name = d1.common_name
            GROUP BY d4.scientific_name
            ORDER BY COUNT(*) DESC, d4.scientific_name ASC
            LIMIT 1) as scientific_name,
            COUNT(*) as total_visits,
            MIN(timestamp) as first_detected,
            MAX(timestamp) as last_detected,
            AVG(confidence) as average_confidence,
            (SELECT strftime('%H:00', timestamp)
            FROM detections d2
            WHERE d2.common_name = d1.common_name
            GROUP BY strftime('%H', timestamp)
            ORDER BY COUNT(*) DESC
            LIMIT 1) as peak_activity_time,
            CASE
                WHEN COUNT(DISTINCT strftime('%m', timestamp)) = 12 THEN 'Year-round'
                WHEN COUNT(DISTINCT strftime('%m', timestamp)) >= 6 THEN 'Multi-season'
                ELSE 'Seasonal'
            END as seasonality,
            (SELECT {ebird}
            FROM detections d3
            WHERE d3.common_name = d1.common_name
              AND {ebird} IS NOT NULL
            LIMIT 1) as ebird_code
        FROM detections d1
        WHERE common_name = ?
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (species_name,))
            result = cur.fetchone()
            # Ungrouped aggregates always return a row; an unknown species comes
            # back as a zero-count row, not an empty result set.
            if not result or not result['total_visits']:
                return None
            return dict(result)

    def _get_bird_details_from_rollup(self, scientific_names):
        """Species detail card off the rollup: count, first/last, average
        confidence and ebird_code are a primary-key read; peak hour and
        seasonality are two bounded passes over the species' rows via the
        covering (scientific_name, timestamp) index. Replaces correlated
        subqueries that re-grouped — and json-parsed — the species' full
        history per call (429-558ms on the top species, now ~tens of ms).

        ``scientific_names`` is a list. It holds one key for almost every
        species (a single ``species_key`` point read, unchanged); it holds
        several only for common names the model label set duplicates across a
        taxonomy split, whose detections can land under either key. Those rows
        are summed into one record so the detail page never blanks just because
        the resolved winner differs from the key the station actually stored.
        """
        keys = _normalize_species_keys(scientific_names)
        if not keys:
            return None
        key_clause, key_params = _species_where('species_key', keys)
        sci_clause, sci_params = _species_where('scientific_name', keys)
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT species_key, common_name, scientific_name, ebird_code, "
                "detection_count, sum_confidence, first_detected, "
                f"last_detected FROM species WHERE {key_clause}",
                key_params)
            rows = cur.fetchall()
            if not rows:
                return None

            # One covering-index pass; at most 12x24 groups come back and
            # Python folds them into peak hour + distinct months. substr at
            # fixed offsets into db_schema.TIMESTAMP_FORMAT beats strftime
            # by ~30% here — no per-row datetime parsing.
            cur.execute(f"""
                SELECT substr(timestamp, 6, 2) AS month,
                       substr(timestamp, 12, 2) AS hour,
                       COUNT(*) AS count
                FROM detections
                WHERE {sci_clause}
                GROUP BY month, hour
                """, sci_params)
            buckets = cur.fetchall()

        months_seen = len({b['month'] for b in buckets})
        hour_counts = {}
        for b in buckets:
            hour_counts[b['hour']] = hour_counts.get(b['hour'], 0) + b['count']
        # Rollup row without detection rows = drift mid-heal; degrade quietly
        peak_time = None
        if hour_counts:
            peak_hour = min(hour_counts, key=lambda h: (-hour_counts[h], h))
            peak_time = f'{peak_hour}:00'

        if months_seen == 12:
            seasonality = 'Year-round'
        elif months_seen >= 6:
            seasonality = 'Multi-season'
        else:
            seasonality = 'Seasonal'

        # Aggregate across the (usually one) matched rollup rows. Rank by
        # detection count so a placeholder duplicate can't outvote the key the
        # station really uses, then by the caller's key order so an exact tie
        # settles on the resolver's representative rather than SQLite's scan
        # order — otherwise the displayed name flips as counts drift.
        key_rank = {key: position for position, key in enumerate(keys)}
        ordered = sorted(
            rows,
            key=lambda r: (-r['detection_count'],
                           key_rank.get(r['species_key'], len(keys))),
        )
        rep = ordered[0]
        total_visits = sum(r['detection_count'] for r in rows)
        sum_confidence = sum(r['sum_confidence'] for r in rows)
        ebird_code = next((r['ebird_code'] for r in ordered if r['ebird_code']), None)
        return {
            'common_name': rep['common_name'],
            'scientific_name': rep['scientific_name'],
            'total_visits': total_visits,
            'first_detected': min(r['first_detected'] for r in rows),
            'last_detected': max(r['last_detected'] for r in rows),
            'average_confidence': sum_confidence / total_visits,
            'peak_activity_time': peak_time,
            'seasonality': seasonality,
            'ebird_code': ebird_code,
        }

    def get_bird_recordings(self, species_name=None, sort='recent', limit=None,
                             *, scientific_name=None, since=None):
        """
        Get recordings for a species with sorting options.

        Filter by ``scientific_name`` when available (the stable path that
        merges V2/V3 English variants); otherwise filter by the legacy
        ``species_name`` (English common_name).

        Args:
            species_name: Bird species common name (legacy fallback)
            sort: 'recent' (timestamp DESC) or 'best' (confidence DESC)
            limit: Optional max number of records (None = all)
            scientific_name: Stable species key (preferred when known)
            since: Optional ISO timestamp lower bound (timestamp >= since), used
                to restrict anonymous callers to a recent window so the public
                view can't surface old all-time clips (incl. via 'best' sort).

        Returns:
            List of recording dicts with id, timestamp, common_name, confidence,
            audio_filename, spectrogram_filename
        """
        filter_col, filter_values = _resolve_filter_column(
            species_name, scientific_name=scientific_name,
        )
        if filter_col is None:
            return []

        # Order column is chosen from a fixed set (not interpolated user input);
        # the filter column/values are validated above. LIMIT uses -1 for
        # unlimited.
        species_clause, species_params = _species_where(filter_col, filter_values)
        window_clause = "AND timestamp >= ?" if since else ""
        order_by = "confidence DESC" if sort == 'best' else "timestamp DESC"
        query = f"""
        SELECT id, timestamp, common_name, confidence, extra, audio_source,
               media_bytes
        FROM detections
        WHERE {species_clause}
        {window_clause}
        ORDER BY {order_by}
        LIMIT ?
        """

        # Use -1 for unlimited (SQLite treats negative LIMIT as no limit)
        limit_param = limit if limit is not None else -1
        params = list(species_params)
        if since:
            params.append(since)
        params.append(limit_param)

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        recordings = self._normalize_detections(rows, include_filenames=True)

        logger.debug("Bird recordings retrieved", extra={
            'species': filter_values,
            'filter_col': filter_col,
            'sort': sort,
            'limit': limit,
            'records_count': len(recordings)
        })
        return recordings

    def get_detection_distribution(self, species_name=None, view=None,
                                    anchor_date_str=None, *, scientific_name=None):
        """Compute detection counts across a time window for a single species.

        Filters by ``scientific_name`` when provided (the stable path that
        merges V2/V3 English variants); otherwise by the legacy
        ``species_name`` English common_name. Every view runs the same
        single query over a sargable timestamp range — see
        _distribution_spec for the per-view labels/range/bucket table.
        """
        filter_col, filter_values = _resolve_filter_column(
            species_name, scientific_name=scientific_name,
        )
        if filter_col is None:
            return {'labels': [], 'data': []}

        anchor = datetime.strptime(anchor_date_str, '%Y-%m-%d')
        labels, start, end, bucket_expr, to_index = _distribution_spec(
            view, anchor)

        logger.debug("Getting detection distribution", extra={
            'species': filter_values,
            'filter_col': filter_col,
            'view': view,
            'date': anchor_date_str
        })

        # filter_col/values are validated above; bucket_expr comes from the
        # fixed per-view table. The plain timestamp range (unlike the previous
        # per-row date()/strftime() predicates) keeps this a bounded index
        # search — 52-207ms/chart -> ~1ms on the top species of a 1M-row DB.
        species_clause, species_params = _species_where(filter_col, filter_values)
        query = f"""
        SELECT {bucket_expr} as bucket, COUNT(*) as count
        FROM detections
        WHERE {species_clause} AND timestamp >= ? AND timestamp < ?
        GROUP BY bucket
        """

        data = [0] * len(labels)
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (*species_params, _iso_ts(start), _iso_ts(end)))
            for row in cur.fetchall():
                index = to_index(row['bucket'])
                if 0 <= index < len(data):
                    data[index] = row['count']

        logger.debug("Detection distribution calculated", extra={
            'data_points': len([d for d in data if d > 0]),
            'total_detections': sum(data)
        })
        return {'labels': labels, 'data': data}

    def get_daily_detection_counts(self, start_date, end_date):
        """Get total detection counts per day for a date range.

        Args:
            start_date: Start date string (YYYY-MM-DD)
            end_date: End date string (YYYY-MM-DD)

        Returns:
            dict: {'labels': ['YYYY-MM-DD', ...], 'data': [count, ...]}
                  Labels are all dates in range (including zeros for continuity)
        """
        logger.debug("Getting daily detection counts", extra={
            'start_date': start_date,
            'end_date': end_date
        })

        # Parse dates
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')

        # Generate all dates in range for labels (ensures continuous data)
        all_dates = []
        current = start_dt
        while current <= end_dt:
            all_dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

        # Initialize data with zeros
        data = {date: 0 for date in all_dates}

        # Counts per day: from the time rollups when ready (readiness and
        # data share one read transaction), else a sargable raw range scan
        # off the plain timestamp index — no date(timestamp) expression
        # filter anywhere, which is what let migration 5 retire the
        # expression indexes.
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN")
            try:
                if db_rollups.rollups_ready(cur):
                    cur.execute(
                        "SELECT date AS day, SUM(count) AS count FROM hour_day "
                        "WHERE date >= ? AND date <= ? GROUP BY date ORDER BY date",
                        (start_date, end_date))
                else:
                    cur.execute(
                        "SELECT substr(timestamp, 1, 10) AS day, COUNT(*) AS count "
                        "FROM detections WHERE timestamp >= ? "
                        "AND timestamp < datetime(?, '+1 day') "
                        "GROUP BY day ORDER BY day",
                        (f"{start_date}T00:00:00", f"{end_date}T00:00:00"))
                results = cur.fetchall()
            finally:
                conn.commit()

        # Fill in counts
        for row in results:
            if row['day'] in data:
                data[row['day']] = row['count']

        # Convert to ordered lists
        labels = all_dates
        counts = [data[date] for date in all_dates]

        logger.debug("Daily detection counts calculated", extra={
            'days': len(labels),
            'total_detections': sum(counts)
        })

        return {'labels': labels, 'data': counts}

    def get_all_unique_species(self):
        """Get all unique bird species ever detected, sorted alphabetically.

        Each row also carries ``last_detected`` (the species' MAX timestamp)
        so the Species Catalog needs no per-species detail fetch.

        Distinct on the species key so the same species detected under
        different V2/V3 English variants surfaces as a single entry, while
        blank-sci legacy rows still differentiate by common_name.

        The rollup holds one row per scientific_name, so a bird the label set
        carries under two of them (a taxonomy genus split) would otherwise show
        up as two identical catalog cards that both open the one detail page
        that merges them. Those rows are folded together here, keeping the
        most-detected name as the entry the catalog displays.
        """
        query = """
        SELECT scientific_name, common_name, last_detected, detection_count
        FROM species
        ORDER BY common_name ASC
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            results = cur.fetchall()

        merged = {}
        for row in results:
            group = same_taxon_group(row['scientific_name'])
            # Legacy rows can carry a blank scientific_name; they key on their
            # own common_name, exactly as the rollup does.
            key = group[0] if group else (row['common_name'] or '')
            existing = merged.get(key)
            if existing is None:
                merged[key] = {
                    'common_name': row['common_name'],
                    'scientific_name': row['scientific_name'],
                    'last_detected': row['last_detected'],
                    '_count': row['detection_count'],
                }
                continue
            if row['last_detected'] > existing['last_detected']:
                existing['last_detected'] = row['last_detected']
            # Ties keep the first row, i.e. the alphabetically-first common
            # name, so the displayed entry is stable across requests.
            if row['detection_count'] > existing['_count']:
                existing['common_name'] = row['common_name']
                existing['scientific_name'] = row['scientific_name']
                existing['_count'] = row['detection_count']

        species = list(merged.values())
        for entry in species:
            del entry['_count']
        species.sort(key=lambda s: s['common_name'])
        return species

    def get_cleanup_protected_ids(self, keep_per_species=60, keep_recent_per_species=16):
        """Ids protected from storage cleanup, plus the total detection count.

        For each species, protects the union of two sets:
        - Top N by confidence (keep_per_species)
        - Most recent N by timestamp (keep_recent_per_species)
        A recording is a cleanup candidate only if it is outside both sets;
        candidate count = total - len(protected).

        Species are keyed like _SPECIES_KEY: by scientific name, so a Turdus
        merula history split between V2's "Eurasian Blackbird" and V3's
        "Common Blackbird" is protected once, with blank-sci legacy rows
        falling back to common_name. Each set is a short covering-index query
        (idx_detections_scientific_confidence / _timestamp) per species —
        the previous implementation ranked every species with window
        functions over the whole table (two full-table temp b-tree sorts,
        ~10s per call on a million-row table).

        Returns:
            tuple: (set of protected detection ids, total detection count)
        """
        protected = set()
        with self.get_db_connection() as conn:
            cur = conn.cursor()

            cur.execute("SELECT COUNT(*) FROM detections")
            total = cur.fetchone()[0]

            # Species discovery off the rollup instead of two DISTINCT
            # scans; species_where owns the key->filter shape (legacy
            # blank-sci species are keyed by common_name).
            cur.execute("SELECT species_key, scientific_name FROM species")
            groups = [
                db_species.species_where(row['scientific_name'],
                                         row['species_key'])
                for row in cur.fetchall()
            ]

            for where, params in groups:
                for order_by, keep in (('confidence DESC', keep_per_species),
                                       ('timestamp DESC', keep_recent_per_species)):
                    if keep <= 0:
                        continue
                    cur.execute(
                        f"SELECT id FROM detections WHERE {where} "
                        f"ORDER BY {order_by}, id DESC LIMIT ?",
                        params + [keep])
                    protected.update(row[0] for row in cur.fetchall())

        logger.debug("Cleanup protected set computed", extra={
            'keep_per_species': keep_per_species,
            'keep_recent_per_species': keep_recent_per_species,
            'protected_count': len(protected),
            'total_count': total,
        })

        return protected, total

    def get_cleanup_candidates_batch(self, after_timestamp=None, after_id=None,
                                     *, limit):
        """One oldest-first keyset batch of rows that still own files.

        Served by the live-media partial index (WHERE media_bytes > 0 must
        appear verbatim so the planner can use it), so the walk is bounded
        by rows-with-files — disk capacity — never by station age. Rows
        whose files are all removed drop out of the index, so restarted
        walks never revisit them.

        Returns:
            List of dicts with id, timestamp, media_bytes; fewer than
            ``limit`` rows signals the walk is (currently) exhausted.
        """
        keyset = ""
        params = []
        if after_id is not None:
            keyset = "AND (timestamp > ? OR (timestamp = ? AND id > ?))"
            params = [after_timestamp, after_timestamp, after_id]

        query = f"""
        SELECT id, timestamp, media_bytes
        FROM detections
        WHERE media_bytes > 0 {keyset}
        ORDER BY timestamp ASC, id ASC
        LIMIT ?
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params + [limit])
            return [dict(row) for row in cur.fetchall()]

    def get_media_accounting(self, protected_ids, older_than=None):
        """Exact deletable-media accounting for cleanup's achievability
        check and the policy dry-run previews.

        Returns a dict with deletable_bytes / deletable_rows (live media
        outside the protected set — exact recorded bytes, no size
        heuristic), total_bytes / live_rows (all live media, protected
        included — the budget policy's subject), and unresolved_rows
        (NULL media_bytes: history the frontier hasn't reached, whose
        deletable size is only estimable). ``older_than`` restricts every
        figure to rows before that timestamp (the retention policy's
        subject).
        """
        ids = list(protected_ids)
        age_filter = ""
        age_params = []
        if older_than is not None:
            age_filter = "AND timestamp < ?"
            age_params = [older_than]
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            # One scan for all three figures: the NULL count can't use the
            # partial index anyway, so a combined pass costs no more than
            # the NULL count alone did.
            cur.execute(
                f"SELECT COALESCE(SUM(CASE WHEN media_bytes > 0 "
                f"         THEN media_bytes END), 0), "
                f"       SUM(CASE WHEN media_bytes > 0 THEN 1 ELSE 0 END), "
                f"       SUM(CASE WHEN media_bytes IS NULL THEN 1 ELSE 0 END) "
                f"FROM detections WHERE 1=1 {age_filter}", age_params)
            total_bytes, live_rows, unresolved_rows = cur.fetchone()
            live_rows = live_rows or 0
            unresolved_rows = unresolved_rows or 0
            protected_bytes = 0
            protected_rows = 0
            protected_unresolved = 0
            # Chunked lookups: the protected set can exceed SQLite's bound
            # parameter limit on older builds. Protected UNRESOLVED rows
            # are subtracted from the estimate base too — a protected row
            # is never deletable no matter which side of the frontier it
            # is on (implementation review finding 5).
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                placeholders = ','.join('?' * len(chunk))
                cur.execute(
                    f"SELECT COALESCE(SUM(CASE WHEN media_bytes > 0 "
                    f"         THEN media_bytes END), 0), "
                    f"       SUM(CASE WHEN media_bytes > 0 THEN 1 ELSE 0 END), "
                    f"       SUM(CASE WHEN media_bytes IS NULL THEN 1 ELSE 0 END) "
                    f"FROM detections WHERE id IN ({placeholders}) {age_filter}",
                    chunk + age_params)
                chunk_bytes, chunk_rows, chunk_unresolved = cur.fetchone()
                protected_bytes += chunk_bytes
                protected_rows += chunk_rows or 0
                protected_unresolved += chunk_unresolved or 0
        return {
            'deletable_bytes': total_bytes - protected_bytes,
            'deletable_rows': live_rows - protected_rows,
            'total_bytes': total_bytes,
            'live_rows': live_rows,
            'unresolved_rows': unresolved_rows - protected_unresolved,
        }

    def remove_detection_media(self, filenames):
        """Drop ownership rows for unlinked files and restamp their owners
        in one transaction (cleanup's per-row commit)."""
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            affected = media_ownership.remove_media(cur, filenames)
            conn.commit()
        return affected

    def get_paginated_detections(self, page=1, per_page=25, start_date=None,
                                  end_date=None, species=None, sort='timestamp',
                                  order='desc', *, scientific_name=None,
                                  hour=None):
        """Get paginated detection records with optional filtering.

        Args:
            page: Page number (1-indexed)
            per_page: Results per page (max 100)
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            species: Filter by common_name (English fallback)
            sort: Sort field (timestamp, confidence, common_name)
            order: Sort order (asc, desc)
            scientific_name: Filter by scientific_name (preferred when known)
            hour: Filter by hour of day (integer 0-23)

        Returns:
            tuple: (list of detections with filenames, total_count)
        """
        # Validate and constrain per_page
        per_page = min(max(1, per_page), 100)
        page = max(1, page)
        offset = (page - 1) * per_page

        # Validate sort field to prevent SQL injection
        valid_sort_fields = {'timestamp', 'confidence', 'common_name'}
        if sort not in valid_sort_fields:
            sort = 'timestamp'

        # Validate order
        order = 'ASC' if order.lower() == 'asc' else 'DESC'

        # Build WHERE conditions
        where_clause, params = self._build_detection_filters(
            start_date, end_date, species, scientific_name=scientific_name,
            hour=hour,
        )

        count_query = _count_query(where_clause)

        # Get paginated results
        # Using safe string interpolation for sort/order (validated above)
        data_query = f"""
        SELECT
            id,
            timestamp,
            group_timestamp,
            scientific_name,
            common_name,
            confidence,
            latitude,
            longitude,
            cutoff,
            sensitivity,
            overlap,
            week,
            extra,
            audio_source,
            media_bytes
        FROM detections
        WHERE {where_clause}
        ORDER BY {sort} {order}
        LIMIT ? OFFSET ?
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()

            # Get total count
            cur.execute(count_query, params)
            total_count = cur.fetchone()['total']

            # Get paginated data
            cur.execute(data_query, params + [per_page, offset])
            rows = cur.fetchall()

        # Build detection list with filenames (batch media-name prefetch)
        detections = self._normalize_detections(rows, include_filenames=True)

        logger.debug("Paginated detections retrieved", extra={
            'page': page,
            'per_page': per_page,
            'total_count': total_count,
            'returned_count': len(detections),
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'species': species
            }
        })

        return detections, total_count

    def get_distinct_species_pairs(self):
        """Distinct scientific names across the table, as (scientific_name,
        common_name) pairs with one representative common_name each.

        Feeds the localized common_name sort: the API orders these few hundred
        names by localized display name and hands the order to
        get_paginated_detections_localized, so no query ever materializes the
        full table. Deliberately unfiltered — the page walk applies the
        filters, and species outside them just yield empty buckets — so the
        request's filters live in exactly one query.

        Reads the species rollup; the GROUP BY collapses legacy blank-sci
        rows (keyed by common_name there) into the single '' entry this
        consumer expects — its page walk buckets by scientific_name, so
        multiple '' pairs would fetch the same legacy bucket repeatedly.
        """
        query = """
        SELECT scientific_name,
               MIN(common_name) AS common_name
        FROM species
        GROUP BY scientific_name
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            return [(row['scientific_name'], row['common_name'])
                    for row in cur.fetchall()]

    def get_paginated_detections_localized(self, ordered_species, page=1,
                                            per_page=25, start_date=None,
                                            end_date=None, species=None, *,
                                            scientific_name=None, hour=None):
        """Paginated detections following a caller-supplied species order.

        ``ordered_species`` lists scientific_name values in final display
        order (localized name sort, asc/desc already applied by the API); it
        may be a superset of the species matching the filters — species
        without matching rows just yield empty buckets. The page is
        assembled species-bucket by species-bucket — newest first within a
        species — off idx_detections_scientific_timestamp: covering index
        counts to skip whole buckets before the requested offset, then
        index-served fetches for just the page rows. Nothing beyond the page
        is ever materialized, and no full-table sort runs.

        Returns:
            tuple: (list of detections with filenames, total_count)
        """
        per_page = min(max(1, per_page), 100)
        page = max(1, page)
        offset = (page - 1) * per_page

        where_clause, params = self._build_detection_filters(
            start_date, end_date, species, scientific_name=scientific_name,
            hour=hour,
        )

        count_query = _count_query(where_clause)

        bucket_count_query = f"""
        SELECT COUNT(*) as total
        FROM detections
        WHERE {where_clause} AND scientific_name = ?
        """

        bucket_page_query = f"""
        SELECT
            id,
            timestamp,
            group_timestamp,
            scientific_name,
            common_name,
            confidence,
            latitude,
            longitude,
            cutoff,
            sensitivity,
            overlap,
            week,
            extra,
            audio_source,
            media_bytes
        FROM detections
        WHERE {where_clause} AND scientific_name = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ? OFFSET ?
        """

        rows = []
        with self.get_db_connection() as conn:
            cur = conn.cursor()

            cur.execute(count_query, params)
            total_count = cur.fetchone()['total']

            remaining_offset = offset
            for sci in ordered_species:
                if len(rows) >= per_page:
                    break
                if remaining_offset:
                    # Cheap covering-index count to skip buckets that lie
                    # entirely before the requested offset without reading rows.
                    cur.execute(bucket_count_query, params + [sci])
                    bucket_total = cur.fetchone()['total']
                    if remaining_offset >= bucket_total:
                        remaining_offset -= bucket_total
                        continue
                cur.execute(bucket_page_query,
                            params + [sci, per_page - len(rows),
                                      remaining_offset])
                rows.extend(cur.fetchall())
                remaining_offset = 0

        detections = self._normalize_detections(rows, include_filenames=True)
        return detections, total_count

    def get_detections_for_export_batch(self, start_date=None, end_date=None,
                                         species=None, *, scientific_name=None,
                                         before_timestamp=None, before_id=None,
                                         limit):
        """One batch of raw detection rows for the streaming CSV export.

        Rows come back newest-first (timestamp DESC, id DESC) with ``extra``
        kept as its raw JSON string. Pass the last row's timestamp and id as
        ``before_timestamp``/``before_id`` to fetch the next batch: unlike
        LIMIT/OFFSET batching, the keyset walk never skips or duplicates
        pre-existing rows when detections are inserted mid-export — new rows
        sort ahead of the cursor and simply fall outside the walk.

        Args:
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            species: Filter by common_name (English fallback)
            scientific_name: Filter by scientific_name (preferred when known)
            before_timestamp: Keyset cursor — timestamp of the previous
                batch's last row (None for the first batch)
            before_id: Keyset cursor — id of the previous batch's last row
            limit: Maximum rows per batch

        Returns:
            list: Up to ``limit`` detection dicts; fewer signals the last batch
        """
        where_clause, params = self._build_detection_filters(
            start_date, end_date, species, scientific_name=scientific_name,
        )
        if before_id is not None:
            where_clause += " AND (timestamp < ? OR (timestamp = ? AND id < ?))"
            params += [before_timestamp, before_timestamp, before_id]

        query = f"""
        SELECT
            id,
            timestamp,
            group_timestamp,
            scientific_name,
            common_name,
            confidence,
            latitude,
            longitude,
            cutoff,
            sensitivity,
            overlap,
            week,
            extra,
            audio_source,
            media_bytes
        FROM detections
        WHERE {where_clause}
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params + [limit])
            return [dict(row) for row in cur.fetchall()]

    def get_detection_by_id(self, detection_id):
        """Get a single detection by ID.

        Args:
            detection_id: The detection ID

        Returns:
            dict: Detection record or None if not found
        """
        query = """
        SELECT
            id,
            timestamp,
            group_timestamp,
            scientific_name,
            common_name,
            confidence,
            latitude,
            longitude,
            cutoff,
            sensitivity,
            overlap,
            week,
            extra,
            audio_source,
            media_bytes
        FROM detections
        WHERE id = ?
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (detection_id,))
            row = cur.fetchone()

        if row:
            return self._normalize_detection(row, include_filenames=True)
        return None

    def get_group_detection_windows(self, detection):
        """Timestamp + confidence of every detection of the same species in
        the same source recording (group) and audio source as ``detection``.

        Powers the player's analysis-window bar: sibling rows mark which
        OTHER 3s analysis windows of the clip also crossed the threshold,
        not just the row being viewed. Species matches on the same key the
        display dedup partitions on — evaluated in SQL against the target
        row (not re-encoded in Python) so core.db_species stays the single
        owner of that expression. ``audio_source`` compares with IS so NULL
        (single-source) rows group together. The SELECT projects only the
        two fields the bar needs; the payload is public-safe by shape.
        """
        query = f"""
        SELECT timestamp, confidence FROM detections
        WHERE group_timestamp = ? AND audio_source IS ?
          AND {_SPECIES_KEY} = (SELECT {_SPECIES_KEY} FROM detections WHERE id = ?)
        ORDER BY timestamp
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (
                detection['group_timestamp'],
                detection.get('audio_source'),
                detection['id'],
            ))
            return [dict(row) for row in cur.fetchall()]

    def get_detection_media(self, detection_id):
        """Every file the row owns (all ranks), audio first."""
        return self.get_detection_media_batch([detection_id]).get(
            detection_id, [])

    def get_detection_media_batch(self, detection_ids):
        """{detection_id: owned files} for many rows in one query — the
        cleanup walk reads media for a whole candidate batch at once."""
        if not detection_ids:
            return {}
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            placeholders = ','.join('?' * len(detection_ids))
            cur.execute(
                f"SELECT detection_id, filename, kind, rank, bytes "
                f"FROM detection_media "
                f"WHERE detection_id IN ({placeholders}) "
                f"ORDER BY detection_id, kind, rank", list(detection_ids))
            grouped = {}
            for row in cur.fetchall():
                entry = dict(row)
                grouped.setdefault(entry.pop('detection_id'), []).append(entry)
            return grouped

    def rename_detection_media(self, old_name, new_name):
        """Follow an on-disk rename (lazy colon->dash migration) in the
        ownership record; a no-op for names no resolved row owns.

        Raises MaintenanceInProgressError while the index build holds the
        writer lock (the serving path treats the rename record as
        best-effort and just serves — reconciliation heals a missed one).
        """
        if maintenance_lease.index_build_active(self):
            raise maintenance_lease.MaintenanceInProgressError(
                'index build in progress')
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            changed = media_ownership.rename_media(cur, old_name, new_name)
            conn.commit()
        return changed

    def delete_detection(self, detection_id):
        """Delete a detection row and the media it owns.

        Unlink-before-delete (media-ownership design): files go first, DB
        rows second, so a crash between the two leaves a row claiming
        missing files — a state the next read of its media self-heals —
        rather than files no row can ever clean up (the old order's leak).
        Resolved rows unlink exactly their recorded files; unresolved
        legacy rows fall back to the pattern-candidates walk. A file that
        survives unlinking (rare OSError) becomes a nonce-named orphan the
        weekly reconciliation removes once the row is gone.

        Args:
            detection_id: The detection ID to delete

        Returns:
            dict: The deleted detection info with 'files_deleted' (the
            names actually removed, audio first), or None if not found

        Raises:
            maintenance_lease.MaintenanceInProgressError: BEFORE any file
            is unlinked, while the one-time index build holds the writer
            lock — the caller returns a retryable maintenance response
            with zero side effects (never a maintenance error after
            irreversible work).
        """
        if maintenance_lease.index_build_active(self):
            raise maintenance_lease.MaintenanceInProgressError(
                'index build in progress')

        # v6 interactive contract, held strictly (implementation re-review
        # R1 + second re-review S1): the writer lock comes BEFORE the
        # authoritative row read, its resolved/unresolved classification,
        # every filesystem side effect, and the row deletes. Nothing can
        # transition the row's ownership state — Stage 2 resolving a
        # legacy row, a creator recording media, a same-name
        # republication — between what this delete decides and what it
        # does. (A file recreated on DISK after our unlink but before our
        # commit cannot gain an ownership row — it becomes a nonce-named
        # orphan reconciliation removes once the row is gone.)
        with self.get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM detections WHERE id = ?",
                            (detection_id,))
                row = cur.fetchone()
                if row is None:
                    conn.rollback()
                    return None
                resolved = row['media_bytes'] is not None
                # include_filenames=False is LOAD-BEARING (implementation
                # third re-review T1): the filenames branch performs a
                # media lookup through a NESTED get_db_connection, whose
                # exit rolls back this very transaction — silently
                # dropping the writer lock for everything below. Nothing
                # in the delete path needs the derived filenames.
                detection = self._normalize_detection(row, include_filenames=False)
                if conn.in_transaction is False:
                    raise RuntimeError(
                        'delete_detection lost its write transaction — '
                        'a nested connection use rolled it back')
                if resolved:
                    cur.execute(
                        "SELECT filename, kind, rank, bytes FROM detection_media "
                        "WHERE detection_id = ?", (detection_id,))
                    owned = [dict(r) for r in cur.fetchall()]
                    removed = media_ownership.unlink_owned_files(owned)
                else:
                    removed = delete_detection_files(detection)['deleted_filenames']
                cur.execute("DELETE FROM detections WHERE id = ?", (detection_id,))
                rows_deleted = cur.rowcount
                if rows_deleted > 0:
                    cur.execute("DELETE FROM detection_media WHERE detection_id = ?",
                                (detection_id,))
                    db_species.apply_delete(cur, detection)
                    db_rollups.apply_delete(cur, detection)
                    db_rollups.bump_revision(cur)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        if rows_deleted > 0:
            logger.info("Detection deleted", extra={
                'detection_id': detection_id,
                'species': detection['common_name'],
                'timestamp': detection['timestamp'],
                'files_deleted': removed,
            })
            detection['files_deleted'] = removed
            return detection

        return None

    # -------------------------------------------------------------------------
    # Notification query helpers
    # -------------------------------------------------------------------------

    def get_today_detection_count(self, scientific_name, before_timestamp):
        """Count detections of a species today, up to (and including) the given timestamp.

        Args:
            scientific_name: Species scientific name
            before_timestamp: ISO timestamp string — upper bound for the query

        Returns:
            int: Number of detections today for this species
        """
        # Compute midnight of the detection's day
        day_start = before_timestamp[:10] + 'T00:00:00'
        query = """
        SELECT COUNT(*) as count FROM detections
        WHERE scientific_name = ? AND timestamp >= ? AND timestamp <= ?
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (scientific_name, day_start, before_timestamp))
            return cur.fetchone()['count']

    def get_species_total_count(self, scientific_name, before_timestamp):
        """Count detections of a species up to (and including) the given timestamp.

        Returns at most 2 — the caller only needs to know if the count is
        exactly 1 (new species) vs more, so we LIMIT 2 to avoid scanning
        all historical detections for common species.

        Args:
            scientific_name: Species scientific name
            before_timestamp: ISO timestamp string — upper bound for the query

        Returns:
            int: 0, 1, or 2
        """
        query = """
        SELECT COUNT(*) as count FROM (
            SELECT 1 FROM detections
            WHERE scientific_name = ? AND timestamp <= ?
            LIMIT 2
        )
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (scientific_name, before_timestamp))
            return cur.fetchone()['count']

    def get_recent_detection_count(self, scientific_name, days=7, before_timestamp=None):
        """Count detections of a species within a recent window.

        Args:
            scientific_name: Species scientific name
            days: Number of days to look back
            before_timestamp: ISO timestamp string — upper bound (defaults to now)

        Returns:
            int: Number of detections in the window for this species
        """
        if before_timestamp is None:
            before_timestamp = local_now().isoformat()
        cutoff = (datetime.fromisoformat(before_timestamp) - timedelta(days=days)).isoformat()
        query = """
        SELECT COUNT(*) as count FROM detections
        WHERE scientific_name = ? AND timestamp >= ? AND timestamp <= ?
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (scientific_name, cutoff, before_timestamp))
            return cur.fetchone()['count']

    # -------------------------------------------------------------------------
    # Query building helpers
    # -------------------------------------------------------------------------

    def _build_detection_filters(self, start_date=None, end_date=None,
                                  species=None, *, scientific_name=None,
                                  hour=None):
        """Build WHERE clause components for detection queries.

        ``scientific_name`` is preferred when known (the stable path that
        merges V2/V3 English variants); otherwise filter on ``species``
        which the API layer falls back to when the resolver couldn't map
        an input string.

        Args:
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            species: Filter by common_name (English fallback)
            scientific_name: Filter by scientific_name (preferred)
            hour: Filter by hour of day (integer 0-23)

        Returns:
            tuple: (where_clause, params) where where_clause is SQL string
                   and params is list of values for parameterized query
        """
        conditions = []
        params = []

        if start_date:
            start_date_iso = f"{start_date}T00:00:00"
            conditions.append("timestamp >= ?")
            params.append(start_date_iso)

        if end_date:
            end_date_iso = f"{end_date}T23:59:59"
            conditions.append("timestamp <= ?")
            params.append(end_date_iso)

        if hour is not None:
            # strftime('%H', ...) yields a zero-padded 2-digit hour string,
            # matching the hourly-activity queries elsewhere in this module.
            conditions.append("strftime('%H', timestamp) = ?")
            params.append(f"{int(hour):02d}")

        filter_col, filter_values = _resolve_filter_column(
            species, scientific_name=scientific_name,
        )
        if filter_col:
            species_clause, species_params = _species_where(filter_col, filter_values)
            conditions.append(species_clause)
            params.extend(species_params)

        where_clause = " AND ".join(conditions) if conditions else _NO_FILTERS
        return where_clause, params

    # -------------------------------------------------------------------------
    # Detection normalization helpers
    # -------------------------------------------------------------------------

    def _canonical_media_map(self, detection_ids):
        """{detection_id: {kind: filename}} for the rank-0 (canonical) media
        of the given rows — one indexed query per page, never per row."""
        ids = [i for i in detection_ids if i is not None]
        if not ids:
            return {}
        placeholders = ','.join('?' * len(ids))
        result = {}
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT detection_id, kind, filename FROM detection_media "
                f"WHERE detection_id IN ({placeholders}) AND rank = 0", ids)
            for row in cur.fetchall():
                result.setdefault(row['detection_id'], {})[row['kind']] = row['filename']
        return result

    def _normalize_detections(self, rows, include_filenames=True):
        """Normalize a page of rows, batch-prefetching recorded media names
        for resolved rows so lists don't pay a per-row lookup."""
        rows = [dict(r) for r in rows]
        media_names = None
        if include_filenames:
            resolved_ids = [r['id'] for r in rows
                            if r.get('media_bytes') is not None and 'id' in r]
            media_names = self._canonical_media_map(resolved_ids)
        return [self._normalize_detection(r, include_filenames, media_names=media_names)
                for r in rows]

    def _normalize_detection(self, row, include_filenames=True, media_names=None):
        """Convert a database row to a normalized detection dict.

        This centralizes the common pattern of:
        1. Converting sqlite3.Row to dict
        2. Parsing the extra JSON field
        3. Optionally attaching audio/spectrogram filenames

        Filename contract (media-ownership design): a row that has been
        resolved (``media_bytes`` not NULL) uses only its RECORDED canonical
        names — a resolved row that owns no file of a kind presents None,
        never a reconstructed name that may belong to another row. Unresolved
        rows (NULL — pre-migration history awaiting the frontier, or queries
        that didn't select media_bytes) keep the synthesized names.

        Args:
            row: sqlite3.Row object from query
            include_filenames: If True, attach audio/spectrogram filenames
            media_names: optional prefetched {id: {kind: filename}} map from
                _canonical_media_map (avoids a per-row query in list paths)

        Returns:
            dict: Normalized detection with parsed extra and optional filenames
        """
        detection = dict(row)
        # Strip private coordinates here so detection dicts are private-by-default
        # — an endpoint returning rows without the api-layer _localize_detection
        # guard (e.g. /api/observations/latest) still can't leak the location.
        for field in PRIVATE_DETECTION_FIELDS:
            detection.pop(field, None)
        # The nonce is the row's media identity, not payload data; media_bytes
        # is internal accounting. Read before popping.
        resolved = detection.pop('media_bytes', None) is not None
        detection.pop('media_nonce', None)
        detection['extra'] = self._parse_extra(detection.get('extra'))

        if include_filenames:
            if resolved:
                if media_names is not None:
                    recorded = media_names.get(detection.get('id'), {})
                else:
                    recorded = self._canonical_media_map(
                        [detection.get('id')]).get(detection.get('id'), {})
                detection['audio_filename'] = recorded.get(
                    media_ownership.KIND_AUDIO)
                detection['spectrogram_filename'] = recorded.get(
                    media_ownership.KIND_SPECTROGRAM)
            else:
                # Label from extra is frozen at detection time, so filenames
                # stay stable even if the source is renamed later
                source_label = detection.get('extra', {}).get('source_label')
                filenames = build_detection_filenames(
                    detection['common_name'],
                    detection['confidence'],
                    detection['timestamp'],
                    audio_extension='mp3',
                    audio_source=source_label or None
                )
                detection['audio_filename'] = filenames['audio_filename']
                detection['spectrogram_filename'] = filenames['spectrogram_filename']

        return detection

    # -------------------------------------------------------------------------
    # Extra field helpers
    # -------------------------------------------------------------------------

    def _parse_extra(self, extra_raw):
        """Parse the extra JSON field from a database value into a dict.

        Args:
            extra_raw: Raw value from database (string, None, or already dict)

        Returns:
            dict: Parsed JSON object, or empty dict if invalid/missing
        """
        if extra_raw is None:
            return {}
        if isinstance(extra_raw, dict):
            return extra_raw
        try:
            return json.loads(extra_raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_detections_with_original_filename(self):
        """Get detections that have original_file_name in extra JSON field.

        Used for BirdNET-Pi migration to match audio files.

        Returns:
            list: Detections with id, timestamp, common_name, confidence,
                  and original_file_name extracted from extra JSON
        """
        query = """
        SELECT
            id,
            timestamp,
            common_name,
            confidence,
            json_extract(extra, '$.original_file_name') as original_file_name
        FROM detections
        WHERE json_extract(extra, '$.original_file_name') IS NOT NULL
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            results = cur.fetchall()

        detections = [dict(row) for row in results]

        logger.debug("Retrieved detections with original_file_name", extra={
            'count': len(detections)
        })

        return detections
