import calendar
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from config.settings import DATABASE_PATH
from core import db_species
from core.db_schema import TIMESTAMP_FORMAT, ensure_schema
from core.logging_config import get_logger
from core.timezone_service import local_now
from core.utils import build_detection_filenames

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


def _resolve_filter_column(species_name=None, *, scientific_name=None):
    """Resolve a (column, value) pair for species-keyed WHERE clauses.

    Routes resolve their English input through the species table at ingress
    and pass ``scientific_name=`` when known. Legacy or unknown names fall
    back to ``common_name`` so migrated rows stay accessible. Returns
    ``(None, None)`` when no species filter was supplied.
    """
    if scientific_name:
        return 'scientific_name', scientific_name
    if species_name:
        return 'common_name', species_name
    return None, None


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
        'mostCommonBird': most_common or "N/A",
        'mostCommonBirdScientificName': most_sci or "",
        'rarestBird': rarest_common or "N/A",
        'rarestBirdScientificName': rarest_sci or "",
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
                                latitude, longitude, cutoff, sensitivity, overlap, extra, audio_source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                detection.get('audio_source')
            ))
            detection_id = cur.lastrowid
            # Same transaction: the species rollup can never disagree with
            # a committed detection.
            db_species.apply_insert(cur, detection, detection_id, extra_dict)
            conn.commit()
            return detection_id

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

        detections = []
        for row in rows:
            detection = self._normalize_detection(row, include_filenames=True)
            # Use legacy field names for backward compatibility with frontend
            detection['bird_song_file_name'] = detection.pop('audio_filename')
            detection['spectrogram_file_name'] = detection.pop('spectrogram_filename')
            detections.append(detection)

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
            audio_source
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

    def get_activity_overview_both(self, date=None, num_species=10):
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
        mostActiveHour, mostCommonBird, mostCommonBirdScientificName,
        rarestBird, rarestBirdScientificName.

        Species are grouped by the species key (scientific_name with a
        common_name fallback for legacy rows) so V2/V3 English drift
        collapses but unrelated blank-sci rows do not.

        The `WHERE c_<period> > 0` filters in the species and hour selects
        are load-bearing — without them a period with no detections would
        return the all-time top species/hour (since the per-period count
        would be 0 but the row still exists in species_counts/hourly_per_period).
        """
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

    def get_summary_stats_for_period(self, period_start, now=None):
        """Compute summary stats for one dashboard period.

        Dashboard only shows one summary tab at a time. This period-specific
        query lets the initial page load pay for the visible period instead
        of always scanning the all-time history for hidden tabs.
        """
        now = (now or local_now()).isoformat()
        params = {
            'period_start': period_start.isoformat(),
            'now': now,
        }

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            query = f"""
            WITH filtered_detections AS (
                SELECT scientific_name, common_name, timestamp
                FROM detections
                WHERE timestamp BETWEEN :period_start AND :now
            ),
            counts AS (
                SELECT
                    COUNT(*) AS total_observations,
                    COUNT(DISTINCT {_SPECIES_KEY}) AS unique_species
                FROM filtered_detections
            ),
            hourly_counts AS (
                SELECT strftime('%H', timestamp) AS hour,
                       COUNT(*) AS detection_count
                FROM filtered_detections
                GROUP BY hour
            ),
            species_counts AS (
                SELECT {_SPECIES_KEY} AS species_key,
                       COUNT(*) AS detection_count
                FROM filtered_detections
                GROUP BY species_key
            )
            SELECT
                (SELECT total_observations FROM counts) AS total_observations,
                (SELECT unique_species FROM counts) AS unique_species,
                (SELECT hour FROM hourly_counts
                 ORDER BY detection_count DESC, hour ASC LIMIT 1) AS most_active_hour,
                (SELECT species_key FROM species_counts
                 ORDER BY detection_count DESC, species_key ASC LIMIT 1) AS most_common_key,
                (SELECT species_key FROM species_counts
                 ORDER BY detection_count ASC, species_key ASC LIMIT 1) AS rarest_key
            """
            cur.execute(query, params)
            row = cur.fetchone()

            selected_species_names = {}
            if row is not None:
                selected_keys = {
                    row[key]
                    for key in ('most_common_key', 'rarest_key')
                    if row[key]
                }
                selected_species_names = {
                    species_key: self._get_species_display_name(
                        cur, species_key)
                    for species_key in selected_keys
                }

        if row is None:
            total_observations = 0
            unique_species = 0
            most_active_hour = None
            most_common_key = None
            rarest_key = None
        else:
            total_observations = row['total_observations'] or 0
            unique_species = row['unique_species'] or 0
            most_active_hour = row['most_active_hour']
            most_common_key = row['most_common_key']
            rarest_key = row['rarest_key']

        return _summary_stats_bucket(
            total_observations, unique_species, most_active_hour,
            most_common_key, rarest_key, selected_species_names,
        )

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
        into one detail record and is served off the species rollup.
        ``species_name`` keeps the legacy English filter (and its original
        full-scan query) for routes where the resolver couldn't map the
        input string.
        """
        if scientific_name:
            return self._get_bird_details_from_rollup(scientific_name)
        if not species_name:
            return None

        ebird = db_species.ebird_expr('d3.')
        query = f"""
        SELECT
            MIN(common_name) AS common_name,
            scientific_name,
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
        GROUP BY scientific_name
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (species_name,))
            result = cur.fetchone()
            return dict(result) if result else None

    def _get_bird_details_from_rollup(self, scientific_name):
        """Species detail card off the rollup: count, first/last, average
        confidence and ebird_code are a primary-key read; peak hour and
        seasonality are two bounded passes over the species' rows via the
        covering (scientific_name, timestamp) index. Replaces correlated
        subqueries that re-grouped — and json-parsed — the species' full
        history per call (429-558ms on the top species, now ~tens of ms).
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT common_name, scientific_name, ebird_code, "
                "detection_count, sum_confidence, first_detected, "
                "last_detected FROM species WHERE species_key = ?",
                (scientific_name,))
            row = cur.fetchone()
            if row is None:
                return None

            # One covering-index pass; at most 12x24 groups come back and
            # Python folds them into peak hour + distinct months. substr at
            # fixed offsets into db_schema.TIMESTAMP_FORMAT beats strftime
            # by ~30% here — no per-row datetime parsing.
            cur.execute("""
                SELECT substr(timestamp, 6, 2) AS month,
                       substr(timestamp, 12, 2) AS hour,
                       COUNT(*) AS count
                FROM detections
                WHERE scientific_name = ?
                GROUP BY month, hour
                """, (scientific_name,))
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

        return {
            'common_name': row['common_name'],
            'scientific_name': row['scientific_name'],
            'total_visits': row['detection_count'],
            'first_detected': row['first_detected'],
            'last_detected': row['last_detected'],
            'average_confidence': row['sum_confidence'] / row['detection_count'],
            'peak_activity_time': peak_time,
            'seasonality': seasonality,
            'ebird_code': row['ebird_code'],
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
        filter_col, filter_value = _resolve_filter_column(
            species_name, scientific_name=scientific_name,
        )
        if filter_col is None:
            return []

        # Order column is chosen from a fixed set (not interpolated user input);
        # the filter column is validated above. LIMIT uses -1 for unlimited.
        window_clause = "AND timestamp >= ?" if since else ""
        order_by = "confidence DESC" if sort == 'best' else "timestamp DESC"
        query = f"""
        SELECT id, timestamp, common_name, confidence, extra, audio_source
        FROM detections
        WHERE {filter_col} = ?
        {window_clause}
        ORDER BY {order_by}
        LIMIT ?
        """

        # Use -1 for unlimited (SQLite treats negative LIMIT as no limit)
        limit_param = limit if limit is not None else -1
        params = [filter_value]
        if since:
            params.append(since)
        params.append(limit_param)

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        recordings = [self._normalize_detection(row, include_filenames=True) for row in rows]

        logger.debug("Bird recordings retrieved", extra={
            'species': filter_value,
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
        filter_col, filter_value = _resolve_filter_column(
            species_name, scientific_name=scientific_name,
        )
        if filter_col is None:
            return {'labels': [], 'data': []}

        anchor = datetime.strptime(anchor_date_str, '%Y-%m-%d')
        labels, start, end, bucket_expr, to_index = _distribution_spec(
            view, anchor)

        logger.debug("Getting detection distribution", extra={
            'species': filter_value,
            'filter_col': filter_col,
            'view': view,
            'date': anchor_date_str
        })

        # filter_col is validated above; bucket_expr comes from the fixed
        # per-view table. The plain timestamp range (unlike the previous
        # per-row date()/strftime() predicates) keeps this a bounded index
        # search — 52-207ms/chart -> ~1ms on the top species of a 1M-row DB.
        query = f"""
        SELECT {bucket_expr} as bucket, COUNT(*) as count
        FROM detections
        WHERE {filter_col} = ? AND timestamp >= ? AND timestamp < ?
        GROUP BY bucket
        """

        data = [0] * len(labels)
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (filter_value, _iso_ts(start), _iso_ts(end)))
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

        # Query counts per day
        query = """
        SELECT
            date(timestamp) as day,
            COUNT(*) as count
        FROM detections
        WHERE date(timestamp) >= date(?)
        AND date(timestamp) <= date(?)
        GROUP BY day
        ORDER BY day
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (start_date, end_date))
            results = cur.fetchall()

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
        """
        query = """
        SELECT scientific_name, common_name, last_detected
        FROM species
        ORDER BY common_name ASC
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            results = cur.fetchall()

        return [
            {
                'common_name': row['common_name'],
                'scientific_name': row['scientific_name'],
                'last_detected': row['last_detected'],
            }
            for row in results
        ]

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

    def get_cleanup_scan_batch(self, after_timestamp=None, after_id=None,
                                *, limit):
        """One oldest-first keyset batch of the fields cleanup needs.

        Walks detections by (timestamp, id) ascending off
        idx_detections_timestamp; pass the last row's values back as
        after_timestamp/after_id for the next batch. The caller filters out
        protected ids and rows whose files are already gone — this stays a
        plain index walk with no window functions and never holds more than
        ``limit`` rows, where the previous implementation materialized every
        candidate row (~1M dicts on a large table) at once.

        Returns:
            List of dicts with id, common_name, confidence, timestamp,
            extra (raw JSON string); fewer than ``limit`` rows signals
            the end of the table.
        """
        where = _NO_FILTERS
        params = []
        if after_id is not None:
            where = "(timestamp > ? OR (timestamp = ? AND id > ?))"
            params = [after_timestamp, after_timestamp, after_id]

        query = f"""
        SELECT id, common_name, confidence, timestamp, extra
        FROM detections
        WHERE {where}
        ORDER BY timestamp ASC, id ASC
        LIMIT ?
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params + [limit])
            return [dict(row) for row in cur.fetchall()]

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
            audio_source
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

        # Build detection list with filenames
        detections = [self._normalize_detection(row, include_filenames=True) for row in rows]

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
            audio_source
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

        detections = [self._normalize_detection(row, include_filenames=True)
                      for row in rows]
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
            audio_source
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
            audio_source
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

    def delete_detection(self, detection_id):
        """Delete a detection record by ID.

        Args:
            detection_id: The detection ID to delete

        Returns:
            dict: The deleted detection info (for file cleanup) or None if not found
        """
        # First get the detection info for file cleanup
        detection = self.get_detection_by_id(detection_id)

        if not detection:
            return None

        # Delete the record and adjust the species rollup in one
        # transaction (the rollup's boundary recomputes read post-delete
        # state, so ordering matters).
        query = "DELETE FROM detections WHERE id = ?"
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (detection_id,))
            rows_deleted = cur.rowcount
            if rows_deleted > 0:
                db_species.apply_delete(cur, detection)
            conn.commit()

        if rows_deleted > 0:
            logger.info("Detection deleted", extra={
                'detection_id': detection_id,
                'species': detection['common_name'],
                'timestamp': detection['timestamp']
            })
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

        filter_col, filter_value = _resolve_filter_column(
            species, scientific_name=scientific_name,
        )
        if filter_col:
            conditions.append(f"{filter_col} = ?")
            params.append(filter_value)

        where_clause = " AND ".join(conditions) if conditions else _NO_FILTERS
        return where_clause, params

    # -------------------------------------------------------------------------
    # Detection normalization helpers
    # -------------------------------------------------------------------------

    def _normalize_detection(self, row, include_filenames=True):
        """Convert a database row to a normalized detection dict.

        This centralizes the common pattern of:
        1. Converting sqlite3.Row to dict
        2. Parsing the extra JSON field
        3. Optionally generating standardized filenames

        Args:
            row: sqlite3.Row object from query
            include_filenames: If True, generate and attach audio/spectrogram filenames

        Returns:
            dict: Normalized detection with parsed extra and optional filenames
        """
        detection = dict(row)
        # Strip private coordinates here so detection dicts are private-by-default
        # — an endpoint returning rows without the api-layer _localize_detection
        # guard (e.g. /api/observations/latest) still can't leak the location.
        for field in PRIVATE_DETECTION_FIELDS:
            detection.pop(field, None)
        detection['extra'] = self._parse_extra(detection.get('extra'))

        if include_filenames:
            # Label from extra is frozen at detection time, so filenames stay
            # stable even if the source is renamed later
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
