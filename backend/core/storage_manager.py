"""Storage manager for automatic cleanup of old detection files.

This module monitors disk usage and automatically cleans up old audio and
spectrogram files when disk usage exceeds a configurable threshold. Database
records are preserved - only the associated files are deleted.

Cleanup is a query-driven consumer of the media-ownership model (design:
internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md): candidates come
from the live-media partial index (bounded by files on disk, never station
age), deletions unlink exactly the files each row owns, and achievability
is exact arithmetic once the resolution frontier has stamped all history.
No directory snapshots, no full-table walks, nothing lost on restart.

Key features:
- Triggers cleanup when disk usage exceeds trigger_percent (default: 85%)
- Frees space until usage drops to target_percent (default: 80%)
- Protects the top N recordings per species by confidence (default: 60)
- Protects the latest N recordings per species by timestamp (default: 16)
- Deletes oldest files first; under pressure it drives the resolution
  frontier forward to surface more candidates from unresolved history
- Preserves all database records
"""

import json
import os
import shutil
import time
from datetime import timedelta

from config.settings import (
    BASE_DIR,
    DEFAULT_SETTINGS,
    EXTRACTED_AUDIO_DIR,
    SPECTROGRAM_DIR,
)
from core.db_maintenance import maybe_run_health_cycle
from core.logging_config import get_logger
from core.media_ownership import unlink_owned_files
from core.runtime_config import get_runtime_settings
from core.utils import build_detection_filenames, get_legacy_filename

logger = get_logger(__name__)

# Average: ~270KB audio + ~30KB spectrogram = ~300KB per detection.
# Only used to ESTIMATE the deletable size of rows the resolution frontier
# has not stamped yet; resolved rows use their exact recorded bytes.
ESTIMATED_SIZE_PER_DETECTION = 300 * 1024  # 300 KB

# Rows per keyset batch of the candidate walk (off the live-media partial
# index, so a batch only ever contains rows that still own files).
_CANDIDATE_BATCH_ROWS = 500

# Politeness pause between candidate batches: cleanup shares the disk and
# the GIL with the recording pipeline and has no latency requirement.
_BATCH_PAUSE_SECONDS = 0.05

def _deletable_estimate(accounting, exact):
    """Exact recorded bytes plus, while the frontier is incomplete, the
    labeled per-row estimate for unresolved history — the one place the
    exact-vs-estimated accounting rule is composed."""
    deletable = accounting['deletable_bytes']
    if not exact:
        deletable += accounting['unresolved_rows'] * ESTIMATED_SIZE_PER_DETECTION
    return deletable


def _get_storage_config() -> dict:
    """Load current storage settings, filling gaps from the shipped defaults.

    Fallbacks come from DEFAULT_SETTINGS rather than literals here so this
    module can't drift from config/settings.py (the check-interval fallback
    used to say 1440 against a shipped default of 30). Settings reads already
    merge defaults, so these only apply if a key is missing entirely.
    """
    storage = get_runtime_settings().get('storage', {})
    return {
        key: storage.get(key, default)
        for key, default in DEFAULT_SETTINGS['storage'].items()
    }


def get_disk_usage(path=None):
    """Get disk usage statistics for the data directory.

    Args:
        path: Path to check (defaults to /app/data)

    Returns:
        dict with total_bytes, used_bytes, free_bytes, percent_used
    """
    if path is None:
        path = os.path.join(BASE_DIR, 'data')

    usage = shutil.disk_usage(path)

    return {
        'total_bytes': usage.total,
        'used_bytes': usage.used,
        'free_bytes': usage.free,
        'percent_used': round((usage.used / usage.total) * 100, 1)
    }


def _detection_filename_candidates(detection):
    """Build ordered dash-pattern filename candidates for a detection.

    Source labels are frozen into ``extra`` for current files. During the
    brief transition to multi-source recording, files instead used the raw
    ``audio_source`` id (for example, ``source_0``) and those rows have no
    saved label. Some imported legacy rows can still be unsuffixed despite
    carrying an audio source, so keep that as the final fallback.
    """
    extra = detection.get('extra', {})
    if isinstance(extra, str):
        # Only the source_label matters here, and most rows don't have one —
        # the substring check skips a JSON parse per row on million-row walks.
        if 'source_label' in extra:
            try:
                extra = json.loads(extra)
            except (json.JSONDecodeError, TypeError):
                extra = {}
        else:
            extra = {}
    source_label = extra.get('source_label')
    if source_label:
        source_suffixes = (source_label,)
    elif detection.get('audio_source'):
        source_suffixes = (detection['audio_source'], None)
    else:
        source_suffixes = (None,)

    return tuple(
        build_detection_filenames(
            detection['common_name'],
            detection['confidence'],
            detection['timestamp'],
            audio_source=source_suffix,
        )
        for source_suffix in source_suffixes
    )


def _existing_detection_paths(detection):
    """Every on-disk path holding the detection's media, audio paths first.

    Checks each filename candidate in both dash and legacy colon patterns
    and keeps all hits, not just the first: transition-era rows can own
    duplicate copies under different naming eras, and a copy that survived
    deletion would be orphaned forever (cleanup only ever revisits DB rows).
    """
    candidates = _detection_filename_candidates(detection)
    paths = []
    for key, directory in (('audio_filename', EXTRACTED_AUDIO_DIR),
                           ('spectrogram_filename', SPECTROGRAM_DIR)):
        for filenames in candidates:
            for name in (filenames[key], get_legacy_filename(filenames[key])):
                if name is None:
                    continue
                path = os.path.join(directory, name)
                if os.path.exists(path):
                    paths.append(path)
    return paths


def delete_detection_files(detection):
    """Delete every audio and spectrogram file a detection owns.

    Args:
        detection: dict with common_name, confidence, timestamp

    Returns:
        dict with deleted_filenames (the names actually removed, audio
        first) and bytes_freed
    """
    result = {'deleted_filenames': [], 'bytes_freed': 0}

    for path in _existing_detection_paths(detection):
        try:
            size = os.path.getsize(path)
            os.remove(path)
            result['deleted_filenames'].append(os.path.basename(path))
            result['bytes_freed'] += size
        except OSError as e:
            logger.warning("Failed to delete detection file", extra={
                'path': path,
                'error': str(e)
            })

    return result


def estimate_deletable_size(db_manager, keep_per_species=None, keep_recent_per_species=None):
    """Deletable media size: exact for frontier-resolved rows, estimated
    (ESTIMATED_SIZE_PER_DETECTION) for unresolved history.

    Returns:
        Tuple of (deletable_bytes, exact) — exact is True once the
        resolution frontier has stamped every row, at which point the
        number is real arithmetic rather than a per-row average.
    """
    from core.media_frontier import frontier_complete

    config = _get_storage_config()
    if keep_per_species is None:
        keep_per_species = config['keep_per_species']
    if keep_recent_per_species is None:
        keep_recent_per_species = config['keep_recent_per_species']

    protected, _total = db_manager.get_cleanup_protected_ids(
        keep_per_species=keep_per_species,
        keep_recent_per_species=keep_recent_per_species,
    )
    accounting = db_manager.get_media_accounting(protected)
    exact = frontier_complete(db_manager)
    return _deletable_estimate(accounting, exact), exact


def _delete_candidates(db_manager, protected, *, bytes_target=None,
                       cutoff_timestamp=None, drive_frontier=False,
                       frontier_done=None):
    """The shared deletion executor every cleanup policy runs through.

    Walks the live-media partial index oldest-first, skipping protected
    rows (composition rule: protections always win, for every policy),
    unlinking exactly the files each row owns. Stop conditions compose:
    ``bytes_target`` (disk-pressure / budget) and ``cutoff_timestamp``
    (retention — the walk is timestamp-ordered, so reaching the cutoff
    ends it). Only the disk-pressure caller sets ``drive_frontier``: when
    resolved candidates run out it advances the resolution frontier
    synchronously to surface more history.
    """
    from core.media_frontier import advance_frontier, frontier_complete

    if frontier_done is None:
        frontier_done = frontier_complete(db_manager)
    result = {'files_deleted': 0, 'bytes_freed': 0,
              'frontier_complete': frontier_done}

    def target_met():
        return bytes_target is not None and result['bytes_freed'] >= bytes_target

    cursor = None
    while not target_met():
        batch = db_manager.get_cleanup_candidates_batch(
            after_timestamp=cursor[0] if cursor else None,
            after_id=cursor[1] if cursor else None,
            limit=_CANDIDATE_BATCH_ROWS)

        if not batch:
            if not drive_frontier or frontier_done:
                break
            # Pressure-driven frontier advance: resolve more history to
            # surface its files as candidates, then restart the walk
            # (resolved rows can be older than the exhausted cursor;
            # already-deleted rows are gone from the index, protected
            # rows re-skim cheaply).
            advanced = advance_frontier(db_manager)
            frontier_done = advanced['complete']
            result['frontier_complete'] = frontier_done
            cursor = None
            if advanced['rows_resolved'] == 0 and frontier_done:
                break
            continue

        media_by_id = db_manager.get_detection_media_batch(
            [row['id'] for row in batch if row['id'] not in protected])
        past_cutoff = False
        for row in batch:
            if target_met():
                break
            if (cutoff_timestamp is not None
                    and row['timestamp'] >= cutoff_timestamp):
                past_cutoff = True
                break
            cursor = (row['timestamp'], row['id'])
            if row['id'] in protected:
                continue

            owned = media_by_id.get(row['id'], [])
            removed = unlink_owned_files(owned)
            if not removed:
                continue
            db_manager.remove_detection_media(removed)
            removed_set = set(removed)
            result['bytes_freed'] += sum(
                f['bytes'] for f in owned if f['filename'] in removed_set)
            result['files_deleted'] += 1

        if past_cutoff:
            break
        time.sleep(_BATCH_PAUSE_SECONDS)

    return result


_POLICIES_LAST_RUN_KEY = 'storage_policies_last_run'


def run_scheduled_policies(db_manager, today=None):
    """Run the daily cleanup policies (retention, media budget) once per
    local day. Both are off by default; protections always win; both act
    only on frontier-resolved rows (their previews say so until the
    frontier completes). Returns per-policy results, or None when nothing
    was due or enabled."""
    from core.media_frontier import live_media_index_exists
    from core.timezone_service import local_now

    config = _get_storage_config()
    retention_days = config.get('retention_days', 0) or 0
    budget_gb = config.get('media_budget_gb', 0) or 0
    if retention_days <= 0 and budget_gb <= 0:
        return None
    if not live_media_index_exists(db_manager):
        return None

    today = today if today is not None else local_now().strftime('%Y-%m-%d')
    with db_manager.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM meta WHERE key = ?",
                    (_POLICIES_LAST_RUN_KEY,))
        row = cur.fetchone()
        if row is not None and row[0] == today:
            return None
        cur.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_POLICIES_LAST_RUN_KEY, today))
        conn.commit()

    protected, _total = db_manager.get_cleanup_protected_ids(
        keep_per_species=config['keep_per_species'],
        keep_recent_per_species=config['keep_recent_per_species'],
    )

    results = {}
    if retention_days > 0:
        cutoff = (local_now() - timedelta(days=retention_days)).isoformat()
        results['retention'] = _delete_candidates(
            db_manager, protected, cutoff_timestamp=cutoff)
    if budget_gb > 0:
        accounting = db_manager.get_media_accounting(protected)
        overage = accounting['total_bytes'] - int(budget_gb * 1024**3)
        if overage > 0:
            results['budget'] = _delete_candidates(
                db_manager, protected, bytes_target=overage)

    if results:
        logger.info("Scheduled cleanup policies ran", extra={
            policy: {'files_deleted': r['files_deleted'],
                     'bytes_freed': r['bytes_freed']}
            for policy, r in results.items()})
    return results


def preview_policy(db_manager, policy):
    """Dry-run for the settings UI: what would this policy delete?

    Exact recorded bytes for frontier-resolved rows; while unresolved
    history remains the figure carries the per-row estimate and
    ``exact: False`` so the UI labels it partial.
    """
    from core.media_frontier import frontier_complete
    from core.timezone_service import local_now

    config = _get_storage_config()

    if policy == 'pressure':
        # estimate_deletable_size computes its own protected set and
        # exactness — don't pay for them twice on this branch.
        deletable, exact = estimate_deletable_size(db_manager)
        return {'policy': policy, 'enabled': config['auto_cleanup_enabled'],
                'bytes': deletable, 'rows': None, 'exact': exact}

    protected, _total = db_manager.get_cleanup_protected_ids(
        keep_per_species=config['keep_per_species'],
        keep_recent_per_species=config['keep_recent_per_species'],
    )
    exact = frontier_complete(db_manager)

    if policy == 'retention':
        days = config.get('retention_days', 0) or 0
        if days <= 0:
            return {'policy': policy, 'enabled': False,
                    'bytes': 0, 'rows': 0, 'exact': exact}
        cutoff = (local_now() - timedelta(days=days)).isoformat()
        accounting = db_manager.get_media_accounting(protected, older_than=cutoff)
        rows = accounting['deletable_rows']
        if not exact:
            rows += accounting['unresolved_rows']
        return {'policy': policy, 'enabled': True,
                'bytes': _deletable_estimate(accounting, exact),
                'rows': rows, 'exact': exact}

    if policy == 'budget':
        budget_gb = config.get('media_budget_gb', 0) or 0
        if budget_gb <= 0:
            return {'policy': policy, 'enabled': False,
                    'bytes': 0, 'rows': 0, 'exact': exact}
        accounting = db_manager.get_media_accounting(protected)
        overage = max(0, accounting['total_bytes'] - int(budget_gb * 1024**3))
        overage = min(overage, accounting['deletable_bytes'])
        return {'policy': policy, 'enabled': True,
                'bytes': overage, 'rows': None, 'exact': exact}

    raise ValueError(f'unknown policy: {policy}')


def cleanup_storage(db_manager, target_percent=None, keep_per_species=None,
                    keep_recent_per_species=None):
    """Run storage cleanup to free disk space.

    Walks the live-media partial index oldest-first, unlinking exactly the
    files each unprotected row owns, until disk usage drops below
    target_percent. Per-run cost is O(files actually deleted): candidate
    rows are only ever rows that still own files, deleted rows drop out of
    the index, and nothing is lost on restart (no cursor to carry).

    Under pressure, when resolved candidates run out while unresolved
    history remains, cleanup drives the resolution frontier forward
    synchronously — backfill and pressure-cleanup are the same walk at two
    urgencies, so there is no disabled window and no legacy fallback path.

    SAFETY: achievability is exact arithmetic over recorded bytes once the
    frontier is complete (plus a labeled per-row estimate for unresolved
    history before that), so a disk full of non-BirdNET data is reported —
    once, without the old every-cycle full-table re-walk — rather than
    chased. UNACHIEVABLE is only declared definitively when the frontier
    is complete and every candidate is exhausted.

    Args:
        db_manager: DatabaseManager instance
        target_percent: Target disk usage percentage (default from settings)
        keep_per_species: Top recordings per species by confidence (default from settings)
        keep_recent_per_species: Latest recordings per species (default from settings)

    Returns:
        dict with files_deleted (rows whose media was removed), bytes_freed,
        target_achievable, target_reached, frontier_complete
    """
    from core.media_frontier import (
        frontier_complete,
        live_media_index_exists,
    )

    config = _get_storage_config()
    if target_percent is None:
        target_percent = config['target_percent']
    if keep_per_species is None:
        keep_per_species = config['keep_per_species']
    if keep_recent_per_species is None:
        keep_recent_per_species = config['keep_recent_per_species']

    result = {
        'files_deleted': 0,
        'bytes_freed': 0,
        'target_achievable': True,
        'target_reached': False,
        'frontier_complete': False,
    }

    usage = get_disk_usage()
    current_percent = usage['percent_used']

    if current_percent <= target_percent:
        logger.info("Disk usage already below target", extra={
            'current_percent': current_percent,
            'target_percent': target_percent
        })
        result['target_reached'] = True
        return result

    if not live_media_index_exists(db_manager):
        # The one-time coordinated build hasn't happened yet (deferred
        # behind a bulk import, or first boot after upgrade) — cleanup
        # stays gated rather than falling back to a full-table walk.
        logger.warning("Cleanup gated: live-media index not built yet")
        return result

    bytes_to_free = usage['used_bytes'] - (usage['total_bytes'] * target_percent / 100)

    protected, _total = db_manager.get_cleanup_protected_ids(
        keep_per_species=keep_per_species,
        keep_recent_per_species=keep_recent_per_species,
    )
    accounting = db_manager.get_media_accounting(protected)
    frontier_done = frontier_complete(db_manager)

    estimated_deletable = _deletable_estimate(accounting, frontier_done)

    if estimated_deletable < bytes_to_free:
        # Informational only at this point — the ESTIMATE can undershoot
        # (unresolved files bigger than the per-row average), so the
        # definitive UNACHIEVABLE verdict is decided after the walk, from
        # what actually happened (implementation review finding 5).
        logger.warning("Target may be unachievable - estimate below need", extra={
            'current_percent': current_percent,
            'target_percent': target_percent,
            'bytes_to_free_gb': round(bytes_to_free / (1024**3), 2),
            'deletable_gb': round(estimated_deletable / (1024**3), 2),
            'exact': frontier_done,
        })
        # Still proceed: partial cleanup frees what it can, and the
        # candidate walk below is O(rows with files) — the stuck state
        # costs one cheap pass per cycle, never a full-table re-walk.

    logger.info("Starting storage cleanup", extra={
        'current_percent': current_percent,
        'target_percent': target_percent,
        'bytes_to_free_gb': round(bytes_to_free / (1024**3), 2),
        'deletable_bytes': accounting['deletable_bytes'],
        'unresolved_rows': accounting['unresolved_rows'],
        'keep_per_species': keep_per_species,
        'keep_recent_per_species': keep_recent_per_species
    })

    walk = _delete_candidates(db_manager, protected,
                              bytes_target=bytes_to_free,
                              drive_frontier=True,
                              frontier_done=frontier_done)
    result['bytes_freed'] = walk['bytes_freed']
    result['files_deleted'] = walk['files_deleted']
    result['frontier_complete'] = walk['frontier_complete']
    if result['bytes_freed'] >= bytes_to_free:
        result['target_reached'] = True
    else:
        # Definitive only now: the frontier is complete (the walk drives
        # it) and every candidate was exhausted without reaching the
        # target — never from the pre-walk estimate, which can contradict
        # the outcome in both directions.
        result['target_achievable'] = False

    log_extra = {
        'files_deleted': result['files_deleted'],
        'bytes_freed_gb': round(result['bytes_freed'] / (1024**3), 2),
        'target_reached': result['target_reached']
    }
    if result['target_reached']:
        logger.info("Storage cleanup completed - target reached", extra=log_extra)
    elif not result['target_achievable']:
        logger.warning("Storage cleanup completed - target NOT reached (disk full with non-BirdNET data)", extra=log_extra)
    else:
        logger.info("Storage cleanup completed - candidates exhausted", extra=log_extra)

    return result


def storage_monitor_loop(stop_flag, db_manager):
    """Background thread function that monitors disk usage and triggers cleanup.

    Args:
        stop_flag: threading.Event to signal shutdown
        db_manager: DatabaseManager instance
    """
    # Function-local import: media_frontier imports this module for the
    # filename-candidate archaeology it reuses.
    from core.db_rollups import rollup_worker_slice
    from core.media_frontier import (
        ensure_live_media_index,
        frontier_complete,
        idle_backfill_slice,
    )
    from core.media_reconciliation import scan_disk

    # Startup orphan scan (boots are when crashes happened): repair
    # recognizable creation orphans in the background before monitoring.
    try:
        scan_disk(db_manager)
    except Exception:
        logger.error("Startup media scan failed", exc_info=True)

    last_logged_config = None
    # Cheap-to-recheck beliefs, never load-bearing: re-verified each
    # cycle so downgrade-era rows, a corrective rewind, or new dirty days
    # re-open the respective walks automatically.
    frontier_done = False
    rollups_caught_up = False
    index_ready = False

    while not stop_flag.is_set():
        try:
            config = _get_storage_config()
            check_interval_seconds = max(1, int(config['check_interval_minutes'] * 60))

            if config != last_logged_config:
                logger.info("Storage monitor configuration loaded", extra=config)
                last_logged_config = config

            if config['auto_cleanup_enabled']:
                usage = get_disk_usage()

                logger.debug("Disk usage check", extra={
                    'percent_used': usage['percent_used'],
                    'trigger_percent': config['trigger_percent']
                })

                if usage['percent_used'] > config['trigger_percent']:
                    logger.info("Disk usage exceeded threshold, starting cleanup", extra={
                        'percent_used': usage['percent_used'],
                        'trigger_percent': config['trigger_percent']
                    })
                    cleanup_storage(
                        db_manager,
                        target_percent=config['target_percent'],
                        keep_per_species=config['keep_per_species'],
                        keep_recent_per_species=config['keep_recent_per_species'],
                    )

            # Daily scheduled policies (retention / media budget) — off by
            # default, durable once-a-day gate in meta, protections win.
            run_scheduled_policies(db_manager)

            # After cleanup, so a nearly-full disk is freed before the
            # backup's free-space check asks for headroom.
            maybe_run_health_cycle(db_manager)

            # Idle resolution-frontier backfill: politely stamp legacy rows
            # (25% duty cycle, bounded per monitor iteration) until the
            # walk catches the live edge.
            # A build deferred at startup (lease held by an import, or a
            # crashed holder's unexpired lease) retries here once the
            # lease clears — cleanup must not stay gated until the next
            # restart (implementation review finding 6).
            if not index_ready:
                index_ready = ensure_live_media_index(db_manager)

            if frontier_done:
                frontier_done = frontier_complete(db_manager)
            if not frontier_done:
                frontier_done = idle_backfill_slice(
                    db_manager, stop_flag,
                    max_wall_seconds=min(300, check_interval_seconds / 2))
                if frontier_done:
                    logger.info("Media resolution frontier reached the live edge")

            # Time-rollup maintenance: repair dirty days, then advance the
            # initial build (convergent with live hooks; see db_rollups).
            if not rollups_caught_up:
                rollups_caught_up = rollup_worker_slice(
                    db_manager, stop_flag,
                    max_wall_seconds=min(120, check_interval_seconds / 4))
                if rollups_caught_up:
                    logger.info("Time rollups caught up (ready)")
            else:
                with db_manager.get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT 1 FROM rollup_dirty_day LIMIT 1")
                    rollups_caught_up = cur.fetchone() is None

        except Exception as e:
            logger.error("Error in storage monitor", extra={
                'error': str(e)
            }, exc_info=True)

        # Sleep in small increments for responsive shutdown
        for _ in range(check_interval_seconds):
            if stop_flag.is_set():
                break
            time.sleep(1)

    logger.info("Storage monitor stopped")
