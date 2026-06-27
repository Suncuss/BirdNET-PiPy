import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta

from config.settings import DATABASE_PATH, DATABASE_SCHEMA
from core.logging_config import get_logger
from core.timezone_service import local_now
from core.utils import build_detection_filenames


# Species grouping key used wherever aggregations would otherwise pin
# scientific_name. Falling back to common_name when sci is empty keeps two
# different legacy/migrated rows from collapsing into a single bogus row:
# migration.py defaults Sci_Name to '' when the source CSV omits it, and the
# detections schema only enforces NOT NULL (not non-empty). Within a real
# (non-empty) species, this reduces to scientific_name and still merges
# V2/V3 English-string drift as designed.
def _species_key(alias: str = "") -> str:
    """SQL expression for the stable species grouping key, optionally
    qualified with a table alias prefix (e.g. ``"d."``)."""
    return f"COALESCE(NULLIF({alias}scientific_name, ''), {alias}common_name)"


_SPECIES_KEY = _species_key()


# Detection fields that must never reach a public JSON payload. Exact
# coordinates pinpoint the user's station. _normalize_detection drops these so
# detection dicts are private-by-default; the api layer imports this same tuple
# for its endpoint-level guard, keeping a single source of truth. The
# authenticated CSV export builds rows from its own query
# (get_all_detections_for_export), not _normalize_detection, so it keeps coords.
PRIVATE_DETECTION_FIELDS = ('latitude', 'longitude')


# Width of the zero-padded id packed into a "latest key"; comfortably above
# the 19 digits of a max int64, so the id stays fixed-width and recoverable.
_LATEST_KEY_ID_WIDTH = 20


def _latest_key(alias: str = "") -> str:
    """SQL expression packing a detection's timestamp and id into one
    lexically sortable string, optionally qualified with a table alias.

    MAX() over it yields the newest row, with id breaking exact-timestamp
    ties. char(31) sorts below '.' and every digit, so a variable-width
    (microsecond) timestamp still orders chronologically.
    """
    return (f"{alias}timestamp || char(31) || "
            f"printf('%0{_LATEST_KEY_ID_WIDTH}d', {alias}id)")


def _latest_key_id(key_expr: str) -> str:
    """SQL expression recovering the integer id packed by _latest_key()."""
    return f"CAST(substr({key_expr}, -{_LATEST_KEY_ID_WIDTH}) AS INTEGER)"


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
        self.ensure_db_directory_exists()
        self.initialize_database()
        logger.info("DatabaseManager initialized", extra={
            'database_path': self.db_path
        })

    def ensure_db_directory_exists(self):
        db_directory = os.path.dirname(self.db_path)
        if not os.path.exists(db_directory):
            os.makedirs(db_directory)

    @contextmanager
    def get_db_connection(self):
        # busy_timeout: with WAL plus multiple connections (executor lane +
        # main pipeline), readers and writers can momentarily contend. Wait
        # up to 30s for the lock rather than failing fast with SQLITE_BUSY.
        # synchronous=NORMAL: skip fsync per transaction; sqlite still
        # syncs on WAL checkpoint. Cannot corrupt the DB, but a power loss
        # can drop the last few committed detections. Acceptable for this
        # app — detections are continuous and eventual-consistency-tolerant.
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row  # This line ensures we get dictionaries instead of tuples
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
        finally:
            conn.close()

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
            cursor.executescript(DATABASE_SCHEMA)

            # Auto-migrate: add 'extra' column if missing (for existing databases)
            cursor.execute("PRAGMA table_info(detections)")
            existing_columns = {row[1] for row in cursor.fetchall()}

            if 'extra' not in existing_columns:
                cursor.execute("ALTER TABLE detections ADD COLUMN extra TEXT DEFAULT '{}'")
                cursor.execute("UPDATE detections SET extra = '{}' WHERE extra IS NULL")
                logger.info("Migrated database: added 'extra' column to detections table")

            if 'audio_source' not in existing_columns:
                cursor.execute("ALTER TABLE detections ADD COLUMN audio_source TEXT")
                logger.info("Migrated database: added 'audio_source' column")

            conn.commit()

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
            extra = json.dumps(extra)

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
            conn.commit()
            return cur.lastrowid

    def get_latest_detections(self, limit=15, unique=False):
        if limit <= 0:
            return []

        # Use window function to deduplicate detections.
        # unique=False (default): highest confidence per (group_timestamp, species_key)
        # unique=True: most recent detection per species (one row per species_key)
        #
        # Partition on the species key (scientific_name, with common_name as a
        # fallback when sci is empty) so that V2/V3 model history for the same
        # species merges into one entry — V2 emits "Eurasian Blackbird" and V3
        # emits "Common Blackbird" for Turdus merula. The COALESCE fallback
        # prevents legacy migrated rows with blank sci from collapsing into a
        # single bogus group.
        if unique:
            partition = f"PARTITION BY {_SPECIES_KEY}"
            rank_order = "ORDER BY timestamp DESC, id DESC"
        else:
            partition = f"PARTITION BY group_timestamp, {_SPECIES_KEY}, audio_source"
            rank_order = "ORDER BY confidence DESC"

        # Pre-fetch recent rows so the window function scans ~hundreds
        # instead of the full table (376K+ rows → 1000ms down to ~1ms).
        pre_fetch = limit * 75 if unique else limit * 50

        rows = self._fetch_deduplicated(partition, rank_order, pre_fetch, limit)

        # For unique=True, a single noisy species can dominate the recent
        # prefetch window. Expand bounded windows before falling back to an
        # exact full-table grouping query; this keeps the common dashboard
        # path in the millisecond range without sacrificing correctness.
        if unique and len(rows) < limit:
            for _ in range(5):
                pre_fetch *= 2
                rows = self._fetch_deduplicated(
                    partition, rank_order, pre_fetch, limit,
                )
                if len(rows) >= limit:
                    break
            else:
                rows = self._fetch_latest_unique_by_species(limit)

        detections = []
        for row in rows:
            detection = self._normalize_detection(row, include_filenames=True)
            # Use legacy field names for backward compatibility with frontend
            detection['bird_song_file_name'] = detection.pop('audio_filename')
            detection['spectrogram_file_name'] = detection.pop('spectrogram_filename')
            detections.append(detection)

        return detections

    def _fetch_deduplicated(self, partition, rank_order, pre_fetch, limit):
        """Run the windowed dedup query, optionally bounded by pre_fetch."""
        if pre_fetch is not None:
            source = f"(SELECT * FROM detections ORDER BY timestamp DESC, id DESC LIMIT {pre_fetch})"
        else:
            source = "detections"

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
                    {partition}
                    {rank_order}
                ) as rn
                FROM {source}
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
        """Exact fallback for unique latest detections without a full window sort."""
        query = f"""
        WITH species_latest AS (
            SELECT {_SPECIES_KEY} AS species_key,
                   MAX({_latest_key()}) AS latest_key
            FROM detections
            GROUP BY species_key
        )
        SELECT
            d.id,
            d.timestamp,
            d.group_timestamp,
            d.scientific_name,
            d.common_name,
            d.confidence,
            d.latitude,
            d.longitude,
            d.cutoff,
            d.sensitivity,
            d.overlap,
            d.week,
            d.extra,
            d.audio_source
        FROM detections d
        JOIN species_latest sl
          ON ({_latest_key('d.')}) = sl.latest_key
        ORDER BY d.timestamp DESC, d.id DESC
        LIMIT ?
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

        query = """
        SELECT strftime('%H', timestamp) as hour, COUNT(*) as count
        FROM detections
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY hour
        ORDER BY hour
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (start_of_day, end_of_day))
            results = cur.fetchall()

        hourly_activity = {f"{hour:02d}": 0 for hour in range(24)}
        for row in results:
            hourly_activity[row['hour']] = row['count']

        return [{'hour': f"{hour}:00", 'count': count} for hour, count in hourly_activity.items()]

    def get_activity_overview(self, date=None, order='most'):
        if date:
            start_of_day = datetime.strptime(date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_of_day = local_now().replace(hour=0, minute=0, second=0, microsecond=0)

        end_of_day = start_of_day + timedelta(days=1)

        # Date range already logged in parent function

        # GROUP BY the species key so that mixed V2/V3 English variants of the
        # same species merge into one row. A representative common_name comes
        # along for display; the API layer resolves the localized name from
        # the stable scientific_name key. The MAX(scientific_name) gives the
        # row's representative sci_name — for non-legacy data this is the
        # constant non-empty value; for blank-sci legacy groups it's ''.
        query = f"""
        SELECT {_SPECIES_KEY} AS species_key,
               MAX(scientific_name) AS scientific_name,
               MIN(common_name) AS common_name,
               strftime('%H', timestamp) as hour,
               COUNT(*) as count
        FROM detections
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY species_key, hour
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (start_of_day, end_of_day))
            results = cur.fetchall()

        species_hourly_activity = {}
        for row in results:
            key = row['species_key']
            sci = row['scientific_name']
            common = row['common_name']
            hour = row['hour']
            count = row['count']

            entry = species_hourly_activity.get(key)
            if entry is None:
                entry = {
                    'scientific_name': sci or '',
                    'common_name': common,
                    'hourly': [0] * 24,
                }
                species_hourly_activity[key] = entry

            entry['hourly'][int(hour)] = count

        species_activity = [
            {
                'scientific_name': entry['scientific_name'],
                'species': entry['common_name'],
                'hourlyActivity': entry['hourly'],
                'totalObservations': sum(entry['hourly']),
            }
            for entry in species_hourly_activity.values()
        ]

        species_activity.sort(key=lambda x: x['totalObservations'], reverse=(order != 'least'))

        logger.debug("Activity overview generated", extra={
            'total_species': len(species_hourly_activity),
            'returned_species': len(species_activity)
        })

        return species_activity

    def get_activity_overview_both(self, date=None, num_species=10):
        if date:
            start_of_day = datetime.strptime(date, "%Y-%m-%d").replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_of_day = local_now().replace(hour=0, minute=0, second=0, microsecond=0)

        end_of_day = start_of_day + timedelta(days=1)

        # GROUP BY the species key — see get_activity_overview for rationale.
        query = f"""
        SELECT {_SPECIES_KEY} AS species_key,
               MAX(scientific_name) AS scientific_name,
               MIN(common_name) AS common_name,
               strftime('%H', timestamp) as hour,
               COUNT(*) as count
        FROM detections
        WHERE timestamp BETWEEN ? AND ?
        GROUP BY species_key, hour
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (start_of_day, end_of_day))
            results = cur.fetchall()

        species_hourly_activity = {}
        for row in results:
            key = row['species_key']
            sci = row['scientific_name']
            common = row['common_name']
            hour = row['hour']
            count = row['count']

            entry = species_hourly_activity.get(key)
            if entry is None:
                entry = {
                    'scientific_name': sci or '',
                    'common_name': common,
                    'hourly': [0] * 24,
                }
                species_hourly_activity[key] = entry

            entry['hourly'][int(hour)] = count

        species_activity = [
            {
                'scientific_name': entry['scientific_name'],
                'species': entry['common_name'],
                'hourlyActivity': entry['hourly'],
                'totalObservations': sum(entry['hourly']),
            }
            for entry in species_hourly_activity.values()
        ]

        most = sorted(species_activity, key=lambda x: x['totalObservations'], reverse=True)[:num_species]
        least = sorted(species_activity, key=lambda x: x['totalObservations'])[:num_species]

        logger.debug("Activity overview (both) generated", extra={
            'total_species': len(species_hourly_activity),
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
                    species_key: self._get_latest_species_name_for_key(
                        cur,
                        species_key,
                        all_time_start=params['all_time_start'],
                        now=params['now'],
                    )
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
            'all_time_start': datetime.min.isoformat(),
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
                    species_key: self._get_latest_species_name_for_key(
                        cur,
                        species_key,
                        all_time_start=params['all_time_start'],
                        now=params['now'],
                    )
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

    def _get_latest_species_name_for_key(self, cur, species_key, *, all_time_start, now):
        """Return the newest display name for a summary species key."""
        query = """
        SELECT common_name, scientific_name
        FROM detections
        WHERE timestamp BETWEEN :all_time_start AND :now
          AND (
              scientific_name = :species_key
              OR (
                  (scientific_name IS NULL OR scientific_name = '')
                  AND common_name = :species_key
              )
          )
        ORDER BY timestamp DESC, id DESC
        LIMIT 1
        """
        cur.execute(query, {
            'species_key': species_key,
            'all_time_start': all_time_start,
            'now': now,
        })
        row = cur.fetchone()
        if row is None:
            return "N/A", ""
        return row['common_name'] or "N/A", row['scientific_name'] or ""

    def get_species_sightings(self, limit=10, most_frequent=True):
        # Group by the species key so V2/V3 English drift for the same species
        # merges into one entry; blank-sci legacy rows fall back to common_name.
        # MAX(_latest_key) picks each species' newest detection by id, so the
        # join back to detections yields exactly one row per species.
        order = 'DESC' if most_frequent else 'ASC'
        query = f"""
        WITH species_stats AS (
            SELECT
                {_SPECIES_KEY} AS species_key,
                COUNT(*) AS detection_count,
                MAX({_latest_key()}) AS latest_key
            FROM detections
            GROUP BY species_key
        ),
        selected AS (
            SELECT
                detection_count,
                {_latest_key_id('latest_key')} AS latest_id
            FROM species_stats
            ORDER BY detection_count {order}, species_key ASC
            LIMIT ?
        )
        SELECT d.*
        FROM selected s
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
        into one detail record. ``species_name`` keeps the legacy English
        filter for routes where the resolver couldn't map the input string.
        """
        filter_col, filter_value = _resolve_filter_column(
            species_name, scientific_name=scientific_name,
        )
        if filter_col is None:
            return None

        # Inline the join column into the query — both options are validated
        # above so f-string interpolation is safe here.
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
            WHERE d2.{filter_col} = d1.{filter_col}
            GROUP BY strftime('%H', timestamp)
            ORDER BY COUNT(*) DESC
            LIMIT 1) as peak_activity_time,
            CASE
                WHEN COUNT(DISTINCT strftime('%m', timestamp)) = 12 THEN 'Year-round'
                WHEN COUNT(DISTINCT strftime('%m', timestamp)) >= 6 THEN 'Multi-season'
                ELSE 'Seasonal'
            END as seasonality,
            (SELECT json_extract(d3.extra, '$.ebird_code')
            FROM detections d3
            WHERE d3.{filter_col} = d1.{filter_col}
              AND json_extract(d3.extra, '$.ebird_code') IS NOT NULL
            LIMIT 1) as ebird_code
        FROM detections d1
        WHERE {filter_col} = ?
        GROUP BY scientific_name
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (filter_value,))
            result = cur.fetchone()
            return dict(result) if result else None


    def get_bird_recordings(self, species_name=None, sort='recent', limit=None,
                             *, scientific_name=None):
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

        Returns:
            List of recording dicts with id, timestamp, common_name, confidence,
            audio_filename, spectrogram_filename
        """
        filter_col, filter_value = _resolve_filter_column(
            species_name, scientific_name=scientific_name,
        )
        if filter_col is None:
            return []

        # Use separate queries based on sort order (safer than f-string interpolation
        # of the entire query). The filter column is validated above.
        # LIMIT is parameterized using -1 for unlimited (SQLite treats negative LIMIT as no limit).
        if sort == 'best':
            query = f"""
            SELECT id, timestamp, common_name, confidence, extra, audio_source
            FROM detections
            WHERE {filter_col} = ?
            ORDER BY confidence DESC
            LIMIT ?
            """
        else:  # default to 'recent'
            query = f"""
            SELECT id, timestamp, common_name, confidence, extra, audio_source
            FROM detections
            WHERE {filter_col} = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """

        # Use -1 for unlimited (SQLite treats negative LIMIT as no limit)
        limit_param = limit if limit is not None else -1

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (filter_value, limit_param))
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
        ``species_name`` English common_name.
        """
        import datetime
        filter_col, filter_value = _resolve_filter_column(
            species_name, scientific_name=scientific_name,
        )
        if filter_col is None:
            return {'labels': [], 'data': []}

        anchor_date = datetime.datetime.strptime(anchor_date_str, '%Y-%m-%d')
        logger.debug("Getting detection distribution", extra={
            'species': filter_value,
            'filter_col': filter_col,
            'view': view,
            'date': anchor_date_str
        })

        # Initialize labels and data based on view type. Each query inlines
        # the filter column (validated above) into safe f-string interpolation.
        if view == 'day':
            # 24 hours for the specific day
            labels = [f"{i:02d}:00" for i in range(24)]
            data = [0] * 24

            query = f"""
            SELECT
                strftime('%H', timestamp) as hour,
                COUNT(*) as count
            FROM detections
            WHERE {filter_col} = ?
            AND date(timestamp) = date(?)
            GROUP BY hour
            """

            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (filter_value, anchor_date_str))
                results = cur.fetchall()

            for row in results:
                hour_idx = int(row['hour'])
                data[hour_idx] = row['count']

        elif view == 'week':
            # 7 days for the week containing the anchor date
            # Use Sunday as week start (matching JavaScript's getDay() where Sunday=0)
            # Python's weekday() returns Monday=0, so we convert: Sunday=6 -> 0, Mon=0 -> 1, etc.
            days_since_sunday = (anchor_date.weekday() + 1) % 7
            week_start = anchor_date - datetime.timedelta(days=days_since_sunday)
            labels = []
            for i in range(7):
                day = week_start + datetime.timedelta(days=i)
                labels.append(day.strftime('%a %m/%d'))
            data = [0] * 7

            query = f"""
            SELECT
                date(timestamp) as day,
                COUNT(*) as count
            FROM detections
            WHERE {filter_col} = ?
            AND date(timestamp) >= date(?)
            AND date(timestamp) < date(?, '+7 days')
            GROUP BY day
            """

            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (filter_value, week_start.strftime('%Y-%m-%d'), week_start.strftime('%Y-%m-%d')))
                results = cur.fetchall()

            for row in results:
                day_date = datetime.datetime.strptime(row['day'], '%Y-%m-%d')
                day_idx = (day_date - week_start).days
                if 0 <= day_idx < 7:
                    data[day_idx] = row['count']

        elif view == 'month':
            # All days in the month
            import calendar
            year = anchor_date.year
            month = anchor_date.month
            num_days = calendar.monthrange(year, month)[1]
            labels = [str(i) for i in range(1, num_days + 1)]
            data = [0] * num_days

            query = f"""
            SELECT
                strftime('%d', timestamp) as day,
                COUNT(*) as count
            FROM detections
            WHERE {filter_col} = ?
            AND strftime('%Y-%m', timestamp) = ?
            GROUP BY day
            """

            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (filter_value, anchor_date.strftime('%Y-%m')))
                results = cur.fetchall()

            for row in results:
                day_idx = int(row['day']) - 1
                if 0 <= day_idx < num_days:
                    data[day_idx] = row['count']

        elif view == '6month':
            # 6 months based on anchor date
            start_month = 1 if anchor_date.month <= 6 else 7
            labels = []
            for i in range(6):
                month_date = datetime.datetime(anchor_date.year, start_month + i, 1)
                labels.append(month_date.strftime('%b'))
            data = [0] * 6

            query = f"""
            SELECT
                strftime('%m', timestamp) as month,
                COUNT(*) as count
            FROM detections
            WHERE {filter_col} = ?
            AND strftime('%Y', timestamp) = ?
            AND CAST(strftime('%m', timestamp) AS INTEGER) >= ?
            AND CAST(strftime('%m', timestamp) AS INTEGER) < ?
            GROUP BY month
            """

            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (filter_value, str(anchor_date.year), start_month, start_month + 6))
                results = cur.fetchall()

            for row in results:
                month_idx = int(row['month']) - start_month
                if 0 <= month_idx < 6:
                    data[month_idx] = row['count']

        elif view == 'year':
            # 12 months for the year
            labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            data = [0] * 12

            query = f"""
            SELECT
                strftime('%m', timestamp) as month,
                COUNT(*) as count
            FROM detections
            WHERE {filter_col} = ?
            AND strftime('%Y', timestamp) = ?
            GROUP BY month
            """

            with self.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(query, (filter_value, str(anchor_date.year)))
                results = cur.fetchall()

            for row in results:
                month_idx = int(row['month']) - 1
                if 0 <= month_idx < 12:
                    data[month_idx] = row['count']

        else:
            raise ValueError("Invalid view. Use 'day', 'week', 'month', '6month', or 'year'.")

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
        query = f"""
        SELECT MAX(scientific_name) AS scientific_name,
               MIN(common_name) AS common_name,
               MAX(timestamp) AS last_detected
        FROM detections
        GROUP BY {_SPECIES_KEY}
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

    def get_species_counts(self):
        """Get detection count for each species.

        Returns:
            dict: {common_name: count} for all species
        """
        query = """
        SELECT common_name, COUNT(*) as count
        FROM detections
        GROUP BY common_name
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query)
            results = cur.fetchall()

        return {row['common_name']: row['count'] for row in results}

    def get_cleanup_candidates(self, keep_per_species=60, keep_recent_per_species=16, limit=None):
        """Get detections eligible for cleanup, oldest first.

        For each species, protects the union of two sets:
        - Top N by confidence (keep_per_species)
        - Most recent N by timestamp (keep_recent_per_species)
        A recording is a candidate only if it falls outside both sets.

        Args:
            keep_per_species: Top recordings to keep per species by confidence
            keep_recent_per_species: Most recent recordings to keep per species
            limit: Optional max number of records to return

        Returns:
            List of dicts with: id, common_name, confidence, timestamp,
                audio_source, extra (raw JSON string)
            Ordered by timestamp ASC (oldest first)
        """
        # Partition on the species key so retention is per-species rather than
        # per-English-string: a Turdus merula history split between V2's
        # "Eurasian Blackbird" and V3's "Common Blackbird" is protected once
        # (top-N + recent-N total), not twice. Blank-sci legacy rows fall
        # back to common_name so two unrelated legacy birds remain distinct.
        query = f"""
        WITH RankedDetections AS (
            SELECT
                id,
                common_name,
                confidence,
                timestamp,
                audio_source,
                extra,
                ROW_NUMBER() OVER (
                    PARTITION BY {_SPECIES_KEY}
                    ORDER BY confidence DESC
                ) as confidence_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY {_SPECIES_KEY}
                    ORDER BY timestamp DESC
                ) as recency_rank
            FROM detections
        )
        SELECT id, common_name, confidence, timestamp, audio_source, extra
        FROM RankedDetections
        WHERE confidence_rank > ? AND recency_rank > ?
        ORDER BY timestamp ASC
        LIMIT ?
        """

        # Use -1 for unlimited (SQLite treats negative LIMIT as no limit)
        limit_param = limit if limit is not None else -1

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (keep_per_species, keep_recent_per_species, limit_param))
            results = cur.fetchall()

        candidates = [dict(row) for row in results]

        logger.debug("Cleanup candidates retrieved", extra={
            'keep_per_species': keep_per_species,
            'keep_recent_per_species': keep_recent_per_species,
            'candidates_count': len(candidates)
        })

        return candidates

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

        # Get total count
        count_query = f"""
        SELECT COUNT(*) as total
        FROM detections
        WHERE {where_clause}
        """

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

    def get_all_detections(self, start_date=None, end_date=None, species=None,
                            *, scientific_name=None, hour=None):
        """Get all matching detections with normalized fields and filenames.

        Used for in-memory localized sorting where database ordering no longer
        matches the names rendered in the UI. Filter by ``scientific_name``
        when known; falls back to ``species`` (English) for legacy callers.
        """
        where_clause, params = self._build_detection_filters(
            start_date, end_date, species, scientific_name=scientific_name,
            hour=hour,
        )

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
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        detections = [self._normalize_detection(row, include_filenames=True) for row in rows]

        logger.debug("All detections retrieved", extra={
            'count': len(detections),
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'species': species
            }
        })

        return detections

    def get_all_detections_for_export(self, start_date=None, end_date=None,
                                       species=None, *, scientific_name=None):
        """Get all detection records for CSV export.

        Fetches all matching rows in a single query. This is simpler and avoids
        consistency issues with batched LIMIT/OFFSET (where concurrent inserts
        can cause skipped or duplicate rows).

        For typical Raspberry Pi deployments with thousands of detections,
        this approach is efficient and the memory footprint is minimal.

        Args:
            start_date: Start date filter (YYYY-MM-DD)
            end_date: End date filter (YYYY-MM-DD)
            species: Filter by common_name (English fallback)
            scientific_name: Filter by scientific_name (preferred when known)

        Returns:
            list: All detection records matching the filters
        """
        # Build WHERE conditions
        where_clause, params = self._build_detection_filters(
            start_date, end_date, species, scientific_name=scientific_name,
        )

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
        """

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()

        # For export, keep extra as raw JSON string (not parsed)
        detections = [dict(row) for row in rows]

        logger.debug("Detections exported", extra={
            'count': len(detections),
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'species': species
            }
        })

        return detections

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

        # Delete the record
        query = "DELETE FROM detections WHERE id = ?"
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(query, (detection_id,))
            conn.commit()
            rows_deleted = cur.rowcount

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

        where_clause = " AND ".join(conditions) if conditions else "1=1"
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

    def get_extra_field(self, detection_id, field_name, default=None):
        """Get a specific field from a detection's extra JSON.

        Args:
            detection_id: The detection ID
            field_name: Key to retrieve from extra JSON
            default: Value to return if field doesn't exist

        Returns:
            The field value or default
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT extra FROM detections WHERE id = ?", (detection_id,))
            row = cur.fetchone()
            if row:
                extra = self._parse_extra(row['extra'])
                return extra.get(field_name, default)
            return default

    def update_extra_field(self, detection_id, field_name, value):
        """Update a specific field in a detection's extra JSON.

        Args:
            detection_id: The detection ID
            field_name: Key to update in extra JSON
            value: Value to set

        Returns:
            bool: True if updated, False if detection not found
        """
        with self.get_db_connection() as conn:
            cur = conn.cursor()

            # Get current extra
            cur.execute("SELECT extra FROM detections WHERE id = ?", (detection_id,))
            row = cur.fetchone()

            if not row:
                return False

            # Parse, update, and save
            extra = self._parse_extra(row['extra'])
            extra[field_name] = value

            cur.execute(
                "UPDATE detections SET extra = ? WHERE id = ?",
                (json.dumps(extra), detection_id)
            )
            conn.commit()
            return True

    def set_extra(self, detection_id, extra_dict):
        """Replace the entire extra JSON for a detection.

        Args:
            detection_id: The detection ID
            extra_dict: Dict to set as extra (replaces existing)

        Returns:
            bool: True if updated, False if detection not found
        """
        if not isinstance(extra_dict, dict):
            raise ValueError("extra_dict must be a dictionary")

        with self.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE detections SET extra = ? WHERE id = ?",
                (json.dumps(extra_dict), detection_id)
            )
            conn.commit()
            return cur.rowcount > 0

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
