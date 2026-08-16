"""Time-axis rollups: per-day species and hour aggregates.

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md (pillar 3).
Completes the pattern the ``species`` table proved along the identity axis:
writers maintain the rollups in the same transaction as the detection
write, drift triggers repair, and everything is rebuildable from the
event log. The whole-table dashboard aggregates then read O(rollup rows)
instead of O(detections in period) — measured ≥9.5s warm for the allTime
summary on a live 1.12M-row table, low milliseconds off these tables.

Convergent initial build: hooks are ALWAYS on, and the builder never adds
— it replaces whole day-buckets with recomputes from ``detections``
(DELETE first, acquiring SQLite's write lock before the aggregate reads
the source day). Whichever commits first, the bucket converges, so live
writes need no coordination with the build. Bypass writers (the bulk
importer, old-code rows the frontier resolves) record their dates in
``rollup_dirty_day`` durably in the same transaction as their rows; a
worker recomputes those buckets. Readiness is COMPUTED — initial build
complete and dirty queue empty — never stored, and every ready/dirty
transition bumps ``rollup_revision`` so response caches can validate
cross-process.
"""
import time

import core.db_species as db_species
from core.logging_config import get_logger

logger = get_logger(__name__)

_BUILD_CURSOR_KEY = 'rollup_build_cursor'
_BUILD_DONE = 'DONE'
_REVISION_KEY = 'rollup_revision'

# Days recomputed per builder transaction.
BUILD_DAYS_PER_BATCH = 7

_SPECIES_KEY = db_species.SPECIES_KEY


def _day_start(date):
    return f"{date}T00:00:00"


def _distinct_dates_after(cursor, after_date, limit):
    """The next ``limit`` distinct detection dates strictly after
    ``after_date`` ('' for the beginning). The ``T~`` bound sorts above
    every real timestamp of that date, making the keyset strict without a
    second comparison."""
    cursor.execute(
        "SELECT DISTINCT substr(timestamp, 1, 10) AS d FROM detections "
        "WHERE timestamp >= ? ORDER BY d LIMIT ?",
        (f"{after_date}T~" if after_date else '', limit))
    return [row[0] for row in cursor.fetchall()]


def bump_revision(cursor):
    """Advance the cache-validation revision; call in the same transaction
    as any ready/dirty state change."""
    cursor.execute(
        "INSERT INTO meta (key, value) VALUES (?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)",
        (_REVISION_KEY,))


def get_revision(cursor):
    cursor.execute("SELECT value FROM meta WHERE key = ?", (_REVISION_KEY,))
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def rollups_ready(cursor):
    """Initial build complete AND no dirty repair work pending. Evaluate
    inside the SAME read transaction as the rollup queries it gates."""
    cursor.execute("SELECT value FROM meta WHERE key = ?", (_BUILD_CURSOR_KEY,))
    row = cursor.fetchone()
    if row is None or row[0] != _BUILD_DONE:
        return False
    cursor.execute("SELECT 1 FROM rollup_dirty_day LIMIT 1")
    return cursor.fetchone() is None


def apply_insert(cursor, detection):
    """Fold one inserted detection into its day buckets (same transaction
    as the detections INSERT). Always on — the convergent builder makes
    concurrent initial builds safe."""
    species_key = db_species.species_key_of(
        detection.get('scientific_name'), detection['common_name'])
    timestamp = detection['timestamp']
    date = timestamp[:10]
    hour = int(timestamp[11:13])
    confidence = detection['confidence']
    cursor.execute(
        "INSERT INTO species_day (species_key, date, count, sum_confidence, "
        "  max_confidence, first_ts, last_ts) VALUES (?, ?, 1, ?, ?, ?, ?) "
        "ON CONFLICT(species_key, date) DO UPDATE SET "
        "  count = count + 1, sum_confidence = sum_confidence + excluded.sum_confidence, "
        "  max_confidence = MAX(max_confidence, excluded.max_confidence), "
        "  first_ts = MIN(first_ts, excluded.first_ts), "
        "  last_ts = MAX(last_ts, excluded.last_ts)",
        (species_key, date, confidence, confidence, timestamp, timestamp))
    cursor.execute(
        "INSERT INTO hour_day (date, hour, count) VALUES (?, ?, 1) "
        "ON CONFLICT(date, hour) DO UPDATE SET count = count + 1",
        (date, hour))


def apply_delete(cursor, detection):
    """Roll a deleted detection out of its day buckets (same transaction
    as the DELETE). Recomputes the affected buckets wholesale from the
    surviving rows: deletes are rare user actions, and a recompute is
    parity-correct by construction — no boundary-field logic to get wrong."""
    timestamp = detection['timestamp']
    _rebuild_species_day(cursor, db_species.species_key_of(
        detection.get('scientific_name'), detection['common_name']),
        timestamp[:10])
    _rebuild_hour_bucket(cursor, timestamp[:10], int(timestamp[11:13]))


def _rebuild_species_day(cursor, species_key, date):
    start = _day_start(date)
    cursor.execute("DELETE FROM species_day WHERE species_key = ? AND date = ?",
                   (species_key, date))
    cursor.execute(
        f"INSERT INTO species_day (species_key, date, count, sum_confidence, "
        f"  max_confidence, first_ts, last_ts) "
        f"SELECT ?, ?, COUNT(*), SUM(confidence), MAX(confidence), "
        f"  MIN(timestamp), MAX(timestamp) FROM detections "
        f"WHERE {_SPECIES_KEY} = ? AND timestamp >= ? "
        f"  AND timestamp < datetime(?, '+1 day') HAVING COUNT(*) > 0",
        (species_key, date, species_key, start, start))


def _rebuild_hour_bucket(cursor, date, hour):
    cursor.execute("DELETE FROM hour_day WHERE date = ? AND hour = ?",
                   (date, hour))
    cursor.execute(
        "INSERT INTO hour_day (date, hour, count) "
        "SELECT ?, ?, COUNT(*) FROM detections "
        "WHERE timestamp >= printf('%sT%02d:00:00', ?, ?) "
        "  AND timestamp < printf('%sT%02d:59:59.9999', ?, ?) "
        "HAVING COUNT(*) > 0",
        (date, hour, date, hour, date, hour))


def rebuild_day(cursor, date):
    """Replace BOTH tables' buckets for one day with recomputes from the
    event log. DELETE first: the write lock is acquired before the
    aggregate reads the source day, which is what makes concurrent insert
    hooks convergent in either commit order."""
    start = _day_start(date)
    cursor.execute("DELETE FROM species_day WHERE date = ?", (date,))
    cursor.execute("DELETE FROM hour_day WHERE date = ?", (date,))
    cursor.execute(
        f"INSERT INTO species_day (species_key, date, count, sum_confidence, "
        f"  max_confidence, first_ts, last_ts) "
        f"SELECT {_SPECIES_KEY}, ?, COUNT(*), SUM(confidence), MAX(confidence), "
        f"  MIN(timestamp), MAX(timestamp) FROM detections "
        f"WHERE timestamp >= ? AND timestamp < datetime(?, '+1 day') "
        f"GROUP BY {_SPECIES_KEY}",
        (date, start, start))
    cursor.execute(
        "INSERT INTO hour_day (date, hour, count) "
        "SELECT ?, CAST(strftime('%H', timestamp) AS INTEGER), COUNT(*) "
        "FROM detections WHERE timestamp >= ? AND timestamp < datetime(?, '+1 day') "
        "GROUP BY 2",
        (date, start, start))


def enqueue_dirty_days(cursor, dates):
    """Durably mark days needing recompute (bypass writers call this in
    the same transaction as their rows) and bump the cache revision.

    The bump is unconditional: a second importer batch for an
    already-dirty date still changed the RAW data a cached fallback
    payload was built from, so the revision must move even when the queue
    does not (implementation review finding 4)."""
    dates = set(dates)
    for date in dates:
        cursor.execute(
            "INSERT INTO rollup_dirty_day (date) VALUES (?) "
            "ON CONFLICT(date) DO NOTHING", (date,))
    if dates:
        bump_revision(cursor)
    return bool(dates)


def consume_dirty_days(db_manager, max_days=BUILD_DAYS_PER_BATCH):
    """Recompute up to max_days dirty buckets; each day's recompute and its
    queue removal commit together. Returns days repaired."""
    repaired = 0
    with db_manager.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT date FROM rollup_dirty_day ORDER BY date LIMIT ?",
                    (max_days,))
        dates = [row[0] for row in cur.fetchall()]
        for date in dates:
            rebuild_day(cur, date)
            cur.execute("DELETE FROM rollup_dirty_day WHERE date = ?", (date,))
            repaired += 1
        if repaired:
            bump_revision(cur)
        conn.commit()
    return repaired


def advance_build(db_manager, max_days=BUILD_DAYS_PER_BATCH):
    """Advance the initial build by up to max_days distinct dates; the
    recomputed buckets and the moved cursor commit together. Returns True
    when the initial build is complete."""
    with db_manager.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM meta WHERE key = ?", (_BUILD_CURSOR_KEY,))
        row = cur.fetchone()
        cursor_date = row[0] if row else ''
        if cursor_date == _BUILD_DONE:
            return True
        dates = _distinct_dates_after(cur, cursor_date, max_days)
        for date in dates:
            rebuild_day(cur, date)
        done = len(dates) < max_days
        new_cursor = _BUILD_DONE if done else dates[-1]
        cur.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_BUILD_CURSOR_KEY, new_cursor))
        bump_revision(cur)
        conn.commit()
    if done:
        logger.info("Rollup initial build complete")
    return done


def rollup_worker_slice(db_manager, stop_flag, max_wall_seconds=120):
    """One polite maintenance slice: repair dirty days first, then advance
    the initial build. Returns True when everything is caught up."""
    deadline = time.monotonic() + max_wall_seconds
    while not stop_flag.is_set() and time.monotonic() < deadline:
        if consume_dirty_days(db_manager) > 0:
            continue
        if not advance_build(db_manager):
            continue
        return True
    return False


def audit_rollups(db_manager, chunk_days=60):
    """Weekly complete-bucket comparison, both directions, chunked by date
    window to bound memory. Any missing, extra, or unequal bucket enqueues
    its date for recompute (readiness drops with the queue; the revision
    bump invalidates caches). A count-only check cannot see an
    hour-08→hour-09 move or a same-count boundary change — hence full
    tuples, with a small tolerance on the floating sum."""
    dirty = set()
    with db_manager.get_db_connection() as conn:
        cur = conn.cursor()
        # Cheap emptiness gate only — the chunk loop derives its own date
        # windows, and rollup-only dates (all source rows deleted) are
        # swept by the final pass regardless.
        cur.execute("SELECT 1 FROM detections LIMIT 1")
        has_detections = cur.fetchone() is not None
        cur.execute("SELECT 1 FROM species_day LIMIT 1")
        has_rollups = cur.fetchone() is not None
        if not has_rollups:
            cur.execute("SELECT 1 FROM hour_day LIMIT 1")
            has_rollups = cur.fetchone() is not None
    if not has_detections and not has_rollups:
        return set()

    def window_after(date):
        with db_manager.get_db_connection() as conn:
            return _distinct_dates_after(conn.cursor(), date, chunk_days)

    cursor_date = ''
    while True:
        dates = window_after(cursor_date)
        if not dates:
            break
        start, end = dates[0], dates[-1]
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            raw_hours = {}
            cur.execute(
                "SELECT substr(timestamp, 1, 10), "
                "  CAST(strftime('%H', timestamp) AS INTEGER), COUNT(*) "
                "FROM detections WHERE timestamp >= ? "
                "  AND timestamp < datetime(?, '+1 day') GROUP BY 1, 2",
                (f"{start}T00:00:00", f"{end}T00:00:00"))
            for d, h, c in cur.fetchall():
                raw_hours[(d, h)] = c
            cur.execute("SELECT date, hour, count FROM hour_day "
                        "WHERE date >= ? AND date <= ?", (start, end))
            rolled_hours = {(d, h): c for d, h, c in cur.fetchall()}
            for key in set(raw_hours) | set(rolled_hours):
                if raw_hours.get(key) != rolled_hours.get(key):
                    dirty.add(key[0])

            raw_species = {}
            cur.execute(
                f"SELECT substr(timestamp, 1, 10) AS d, {_SPECIES_KEY} AS sk, "
                f"  COUNT(*), SUM(confidence), MAX(confidence), "
                f"  MIN(timestamp), MAX(timestamp) "
                f"FROM detections WHERE timestamp >= ? "
                f"  AND timestamp < datetime(?, '+1 day') GROUP BY 1, 2",
                (f"{start}T00:00:00", f"{end}T00:00:00"))
            for d, sk, c, s, mx, f, la in cur.fetchall():
                raw_species[(d, sk)] = (c, s, mx, f, la)
            cur.execute(
                "SELECT date, species_key, count, sum_confidence, "
                "  max_confidence, first_ts, last_ts FROM species_day "
                "WHERE date >= ? AND date <= ?", (start, end))
            rolled_species = {(d, sk): (c, s, mx, f, la)
                              for d, sk, c, s, mx, f, la in cur.fetchall()}
            for key in set(raw_species) | set(rolled_species):
                raw = raw_species.get(key)
                rolled = rolled_species.get(key)
                if raw is None or rolled is None:
                    dirty.add(key[0])
                    continue
                if (raw[0] != rolled[0] or raw[2] != rolled[2]
                        or raw[3] != rolled[3] or raw[4] != rolled[4]
                        or abs((raw[1] or 0) - (rolled[1] or 0)) > 1e-6):
                    dirty.add(key[0])
        cursor_date = end
        if len(dates) < chunk_days:
            break

    # Rollup-only dates outside the detections range are drift too —
    # in either rollup table (a date can survive in hour_day alone).
    with db_manager.get_db_connection() as conn:
        cur = conn.cursor()
        for table in ('species_day', 'hour_day'):
            cur.execute(
                f"SELECT DISTINCT date FROM {table} WHERE NOT EXISTS ("
                "  SELECT 1 FROM detections WHERE timestamp >= date || 'T00:00:00' "
                "  AND timestamp < datetime(date || 'T00:00:00', '+1 day') LIMIT 1)")
            for (d,) in cur.fetchall():
                dirty.add(d)
        if dirty:
            enqueue_dirty_days(cur, dirty)
        conn.commit()

    if dirty:
        logger.warning("Rollup audit found drifted days", extra={
            'days': len(dirty)})
    return dirty
