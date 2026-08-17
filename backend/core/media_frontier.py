"""The resolution frontier: incremental backfill of media ownership for
rows that predate the ownership schema (or were written by older code).

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md (pillar 2).

One cursor ``(timestamp, id)`` in ``meta`` carries the invariant: every row
at or behind it is stamped (non-NULL ``media_bytes``). ``advance_frontier``
walks keyset batches past the cursor, skims already-stamped rows at no-op
speed, and resolves NULL rows through the existing multi-era filename
archaeology — normalizing legacy colon names on disk as it goes — recording
ownership, the rollup dirty-day, and the moved cursor in one transaction.

"Done" is computed (cursor at the live edge), never stored: after a
downgrade, rows written by old code re-open the gap and the same walk
closes it. The weekly corrective rewind covers the one case a monotone
cursor can't see — an old importer inserting historical NULL rows *behind*
a caught-up frontier.
"""
import json
import os
import time

from core import maintenance_lease
from core.db_schema import LIVE_MEDIA_INDEXES
from core.logging_config import get_logger
from core.media_ownership import KIND_AUDIO, KIND_DIRS, KIND_SPECTROGRAM
from core.storage_manager import _detection_filename_candidates
from core.utils import get_legacy_filename

logger = get_logger(__name__)

_CURSOR_KEY = 'media_frontier_cursor'

# Rows per transaction: bounds memory and the write-lock hold time.
BATCH_ROWS = 500


def _load_cursor(cursor):
    cursor.execute("SELECT value FROM meta WHERE key = ?", (_CURSOR_KEY,))
    row = cursor.fetchone()
    if row is None:
        return None
    # Read tolerantly: first/last are the (timestamp, id) that matter,
    # whatever the element count.
    values = json.loads(row[0])
    return (values[0], values[-1])


def _store_cursor(cursor, position):
    cursor.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        # The middle slot is dead here but load-bearing for rollback:
        # earlier builds unpack exactly three elements on read.
        (_CURSOR_KEY, json.dumps([position[0], None, position[1]])))


def frontier_complete(db_manager):
    """Whether every row at the live edge is behind the cursor. Computed
    fresh each call — never stored, so downgrade-era writes re-open it
    naturally."""
    with db_manager.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT timestamp, id FROM detections "
                    "ORDER BY timestamp DESC, id DESC LIMIT 1")
        edge = cur.fetchone()
        if edge is None:
            return True
        position = _load_cursor(cur)
        if position is None:
            return False
        return (position[0], position[1]) >= (edge[0], edge[1])


def _resolve_row_files(cursor, detection):
    """The on-disk files this unresolved row owns, via the multi-era
    candidate archaeology. Normalizes legacy colon names to the dash
    pattern on disk. Rank is per-kind discovery order (first found = 0 =
    canonical). Files another detection already owns are skipped —
    first owner wins, logged."""
    files = []
    kind_counts = {KIND_AUDIO: 0, KIND_SPECTROGRAM: 0}
    for candidate in _detection_filename_candidates(detection):
        for kind, key in ((KIND_AUDIO, 'audio_filename'),
                          (KIND_SPECTROGRAM, 'spectrogram_filename')):
            name = candidate[key]
            if name is None:
                continue
            directory = KIND_DIRS[kind]
            path = os.path.join(directory, name)
            if not os.path.exists(path):
                legacy = get_legacy_filename(name)
                if not legacy:
                    continue
                legacy_path = os.path.join(directory, legacy)
                if not os.path.exists(legacy_path):
                    continue
                try:
                    os.rename(legacy_path, path)
                except OSError:
                    logger.warning("Legacy name normalization failed", extra={
                        'legacy': legacy}, exc_info=True)
                    continue
            cursor.execute(
                "SELECT detection_id FROM detection_media WHERE filename = ?",
                (name,))
            owner = cursor.fetchone()
            if owner is not None:
                if owner[0] != detection['id']:
                    logger.info("Backfill filename collision - first owner wins",
                                extra={'media_filename': name,
                                       'owner': owner[0],
                                       'claimant': detection['id']})
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            files.append({'filename': name, 'kind': kind,
                          'rank': kind_counts[kind], 'bytes': size})
            kind_counts[kind] += 1
    return files


def advance_frontier(db_manager, batch_rows=BATCH_ROWS):
    """Resolve one keyset batch of rows past the cursor.

    Stamps, ownership rows, rollup dirty-days, and the moved cursor commit
    in ONE transaction — a crash loses at most one batch of progress and
    never the invariant. Returns a dict with rows_seen, rows_resolved,
    files_recorded, and 'complete' (True when the walk has caught the
    live edge and there is nothing left to do right now).
    """
    result = {'rows_seen': 0, 'rows_resolved': 0,
              'files_recorded': 0, 'complete': False}

    with db_manager.get_db_connection() as conn:
        cur = conn.cursor()
        position = _load_cursor(cur)
        where = ""
        params = []
        if position is not None:
            where = "WHERE (timestamp > ? OR (timestamp = ? AND id > ?))"
            params = [position[0], position[0], position[1]]
        cur.execute(
            f"SELECT id, common_name, confidence, timestamp, extra, "
            f"audio_source, media_bytes FROM detections {where} "
            f"ORDER BY timestamp ASC, id ASC LIMIT ?", params + [batch_rows])
        batch = [dict(row) for row in cur.fetchall()]

        if not batch:
            result['complete'] = True
            return result

        dirty_days = set()
        for detection in batch:
            result['rows_seen'] += 1
            if detection['media_bytes'] is not None:
                continue  # stamped by insert-time code or a previous pass
            files = _resolve_row_files(cur, detection)
            for f in files:
                cur.execute(
                    "INSERT INTO detection_media "
                    "(filename, detection_id, kind, rank, bytes) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (f['filename'], detection['id'], f['kind'],
                     f['rank'], f['bytes']))
            cur.execute(
                "UPDATE detections SET media_bytes = ? WHERE id = ?",
                (sum(f['bytes'] for f in files), detection['id']))
            # A NULL row behind the frontier means a bypass writer created
            # it, so its rollup day is stale too (design: v5 finding 3).
            dirty_days.add(detection['timestamp'][:10])
            result['rows_resolved'] += 1
            result['files_recorded'] += len(files)

        if dirty_days:
            import core.db_rollups as db_rollups
            db_rollups.enqueue_dirty_days(cur, dirty_days)

        last = batch[-1]
        _store_cursor(cur, (last['timestamp'], last['id']))
        conn.commit()

    result['complete'] = len(batch) < batch_rows
    return result


def _indexes_exist(db_manager, names):
    with db_manager.get_db_connection() as conn:
        placeholders = ','.join('?' * len(names))
        count = conn.execute(
            f"SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
            f"AND name IN ({placeholders})", names).fetchone()[0]
    return count == len(names)


def live_media_indexes_exist(db_manager):
    """True only when every index in LIVE_MEDIA_INDEXES exists — a release
    that adds an entry re-triggers the coordinated build, which is
    idempotent per index (IF NOT EXISTS). This is the BUILD trigger; it
    must not gate any feature that needs only its own index (see
    cleanup_index_exists)."""
    return _indexes_exist(db_manager,
                          [name for name, _sql in LIVE_MEDIA_INDEXES])


def cleanup_index_exists(db_manager):
    """Whether cleanup's own index — the timestamp-ordered live-media
    walk — exists. Cleanup is the disk-full safety valve, so it gates on
    exactly this index and never on the whole LIVE_MEDIA_INDEXES set: a
    deferred build (a bulk import holding the maintenance lease) would
    otherwise disable cleanup precisely while that import is consuming
    disk."""
    return _indexes_exist(db_manager, ['idx_detections_live_media'])


def ensure_live_media_index(db_manager):
    """One-time coordinated build of the live-media partial index.

    Runs in the main container after migrations, BEFORE the processing
    threads start (no local writer can then hit busy_timeout against it),
    under the maintenance lease (the API container is already serving and
    its bulk importer is the sustained cross-process writer). The build is
    restartable, not resumable — an interrupted run simply reruns on the
    next start. Fresh databases get the index at creation and return here
    immediately. Returns True when the index exists on exit.
    """
    if live_media_indexes_exist(db_manager):
        return True
    owner = maintenance_lease.mint_owner_token()
    if not maintenance_lease.acquire(
            db_manager, 'index_build', owner,
            maintenance_lease.INDEX_BUILD_TTL_SECONDS):
        logger.warning(
            "Live-media index build deferred: maintenance lease held "
            "(bulk import in progress?) — cleanup stays gated until a "
            "later start builds it")
        return False
    try:
        logger.info("Building live-media partial index (one-time; holds "
                    "the DB writer lock for the duration)")
        started = time.monotonic()
        with db_manager.get_db_connection() as conn:
            for _name, index_sql in LIVE_MEDIA_INDEXES:
                conn.execute(index_sql)
            conn.commit()
        logger.info("Live-media partial indexes built", extra={
            'seconds': round(time.monotonic() - started, 2)})
        return True
    finally:
        maintenance_lease.release(db_manager, owner)


def corrective_rewind(db_manager):
    """Weekly probe: a NULL row at or behind the cursor means an older
    release wrote behind a caught-up frontier (its importer inserts
    historical timestamps without moving the live edge). Rewind to just
    before it — before ALL rows sharing that timestamp — and let the
    ordinary walk re-close the gap, skimming stamped rows at no-op speed.
    Returns True if a rewind happened."""
    with db_manager.get_db_connection() as conn:
        cur = conn.cursor()
        position = _load_cursor(cur)
        if position is None:
            return False
        cur.execute("SELECT MIN(timestamp) FROM detections "
                    "WHERE media_bytes IS NULL")
        min_null = cur.fetchone()[0]
        if min_null is None or (min_null, -1) >= position:
            return False
        _store_cursor(cur, (min_null, -1))
        conn.commit()
    logger.info("Frontier rewound behind unresolved rows", extra={
        'rewound_to': min_null, 'previous': position[0]})
    return True


def idle_backfill_slice(db_manager, stop_flag, max_wall_seconds=300,
                        duty_cycle=0.25):
    """Advance the frontier politely for up to max_wall_seconds.

    Works one batch, then sleeps long enough to keep roughly the given
    duty cycle, checking stop_flag between batches. Returns True once the
    frontier is complete (caller can skip future slices until the weekly
    rewind or a downgrade re-opens the gap).
    """
    deadline = time.monotonic() + max_wall_seconds
    while not stop_flag.is_set():
        started = time.monotonic()
        result = advance_frontier(db_manager)
        if result['complete']:
            return True
        work = time.monotonic() - started
        pause = work * (1.0 - duty_cycle) / duty_cycle
        if time.monotonic() + pause >= deadline:
            return False
        if stop_flag.wait(pause):
            return False  # shutdown wakes instantly instead of on a poll tick
    return False
