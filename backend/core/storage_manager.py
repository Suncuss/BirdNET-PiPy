"""Storage manager for automatic cleanup of old detection files.

This module monitors disk usage and automatically cleans up old audio and
spectrogram files when disk usage exceeds a configurable threshold. Database
records are preserved - only the associated files are deleted.

Key features:
- Triggers cleanup when disk usage exceeds trigger_percent (default: 85%)
- Frees space until usage drops to target_percent (default: 80%)
- Protects the top N recordings per species by confidence (default: 60)
- Protects the latest N recordings per species by timestamp (default: 16)
- Deletes oldest files first
- Preserves all database records
"""

import json
import os
import shutil
import time

from config.settings import (
    BASE_DIR,
    DEFAULT_SETTINGS,
    EXTRACTED_AUDIO_DIR,
    SPECTROGRAM_DIR,
)
from core.db_maintenance import maybe_run_health_cycle
from core.logging_config import get_logger
from core.runtime_config import get_runtime_settings
from core.utils import build_detection_filenames, get_legacy_filename

logger = get_logger(__name__)

# Average: ~270KB audio + ~30KB spectrogram = ~300KB per detection
ESTIMATED_SIZE_PER_DETECTION = 300 * 1024  # 300 KB

# Rows per keyset batch of the oldest-first cleanup walk: bounds cleanup
# memory to one batch of light dicts regardless of table size.
_SCAN_BATCH_ROWS = 1000

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


def _resolve_path_with_legacy_fallback(filename, directory):
    """Resolve file path, falling back to legacy colon-pattern if needed.

    Args:
        filename: Filename (dash-pattern)
        directory: Directory containing the file

    Returns:
        Full path to the file (dash or legacy pattern, whichever exists)
    """
    path = os.path.join(directory, filename)
    if os.path.exists(path):
        return path

    legacy_filename = get_legacy_filename(filename)
    if legacy_filename:
        legacy_path = os.path.join(directory, legacy_filename)
        if os.path.exists(legacy_path):
            return legacy_path

    return path  # Return original path even if it doesn't exist


def _detection_filenames(detection):
    """Build the dash-pattern filenames for a detection record."""
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
    return build_detection_filenames(
        detection['common_name'],
        detection['confidence'],
        detection['timestamp'],
        audio_source=source_label or None
    )


def get_detection_files(detection):
    """Get full file paths for a detection record.

    Supports lazy migration: if new dash-pattern files don't exist,
    falls back to checking for old colon-pattern files.

    Args:
        detection: dict with common_name, confidence, timestamp

    Returns:
        dict with audio_path and spectrogram_path
    """
    filenames = _detection_filenames(detection)

    return {
        'audio_path': _resolve_path_with_legacy_fallback(filenames['audio_filename'], EXTRACTED_AUDIO_DIR),
        'spectrogram_path': _resolve_path_with_legacy_fallback(filenames['spectrogram_filename'], SPECTROGRAM_DIR)
    }


def _disk_filename_sets():
    """Snapshot the filenames in the audio and spectrogram directories.

    One directory read apiece replaces per-candidate stat calls: DB rows are
    preserved after their files are deleted, so on an old station most rows
    the cleanup walk visits have no files left — stat-ing every one of them
    (millions of lookups per run) dominated cleanup cost.

    Legacy colon-pattern names are normalized to the dash pattern (the
    inverse of utils.get_legacy_filename — colons only ever appear in a
    legacy name's time portion), so membership checks need only the dash
    name instead of converting per row.
    """
    def scan(directory):
        try:
            with os.scandir(directory) as entries:
                return {entry.name.replace(':', '-') for entry in entries}
        except OSError:
            return set()

    return scan(EXTRACTED_AUDIO_DIR), scan(SPECTROGRAM_DIR)


def _has_files_on_disk(detection, audio_names, spectrogram_names):
    """Whether any of the detection's files (dash or legacy pattern) exist
    in the normalized directory snapshots from _disk_filename_sets()."""
    filenames = _detection_filenames(detection)
    return (filenames['audio_filename'] in audio_names
            or filenames['spectrogram_filename'] in spectrogram_names)


def delete_detection_files(detection):
    """Delete audio and spectrogram files for a detection.

    Args:
        detection: dict with common_name, confidence, timestamp

    Returns:
        dict with deleted_audio, deleted_spectrogram, bytes_freed
    """
    paths = get_detection_files(detection)
    result = {
        'deleted_audio': False,
        'deleted_spectrogram': False,
        'bytes_freed': 0
    }

    # Delete audio file
    audio_path = paths['audio_path']
    if audio_path and os.path.exists(audio_path):
        try:
            size = os.path.getsize(audio_path)
            os.remove(audio_path)
            result['deleted_audio'] = True
            result['bytes_freed'] += size
        except OSError as e:
            logger.warning("Failed to delete audio file", extra={
                'path': audio_path,
                'error': str(e)
            })

    # Delete spectrogram file
    spectrogram_path = paths['spectrogram_path']
    if spectrogram_path and os.path.exists(spectrogram_path):
        try:
            size = os.path.getsize(spectrogram_path)
            os.remove(spectrogram_path)
            result['deleted_spectrogram'] = True
            result['bytes_freed'] += size
        except OSError as e:
            logger.warning("Failed to delete spectrogram file", extra={
                'path': spectrogram_path,
                'error': str(e)
            })

    return result


def estimate_deletable_size(db_manager, keep_per_species=None, keep_recent_per_species=None):
    """Estimate total size of files that could be deleted.

    Args:
        db_manager: DatabaseManager instance
        keep_per_species: Top recordings to keep per species by confidence
        keep_recent_per_species: Most recent recordings to keep per species

    Returns:
        Tuple of (estimated_bytes, candidate_count)
    """
    config = _get_storage_config()
    if keep_per_species is None:
        keep_per_species = config['keep_per_species']
    if keep_recent_per_species is None:
        keep_recent_per_species = config['keep_recent_per_species']

    protected, total_count = db_manager.get_cleanup_protected_ids(
        keep_per_species=keep_per_species,
        keep_recent_per_species=keep_recent_per_species,
    )
    candidate_count = max(0, total_count - len(protected))

    return candidate_count * ESTIMATED_SIZE_PER_DETECTION, candidate_count


def _scan_detections(db_manager, start_cursor=None, stop_cursor=None):
    """Yield detections oldest-first, starting after start_cursor and
    stopping once past stop_cursor.

    Fetches keyset batches of _SCAN_BATCH_ROWS light rows off the timestamp
    index, so only one batch is ever held regardless of table size. Callers
    track their own position from the yielded rows' (timestamp, id).
    """
    cursor = start_cursor
    while True:
        after_timestamp, after_id = cursor if cursor else (None, None)
        batch = db_manager.get_cleanup_scan_batch(
            after_timestamp=after_timestamp, after_id=after_id,
            limit=_SCAN_BATCH_ROWS)
        for detection in batch:
            if (stop_cursor is not None
                    and (detection['timestamp'], detection['id']) > stop_cursor):
                return
            yield detection
        if len(batch) < _SCAN_BATCH_ROWS:
            return
        cursor = (batch[-1]['timestamp'], batch[-1]['id'])


def cleanup_storage(db_manager, target_percent=None, keep_per_species=None,
                    keep_recent_per_species=None, resume_cursor=None):
    """Run storage cleanup to free disk space.

    Deletes oldest audio and spectrogram files until disk usage drops
    below target_percent. For each species, protects the union of the
    top N by confidence and the latest N by timestamp.

    SAFETY: Will not delete files if the target is unachievable with
    available BirdNET data. This prevents mass deletion when disk is
    full with non-BirdNET files.

    Args:
        db_manager: DatabaseManager instance
        target_percent: Target disk usage percentage (default from settings)
        keep_per_species: Top recordings per species by confidence (default from settings)
        keep_recent_per_species: Latest recordings per species (default from settings)
        resume_cursor: ``result['resume_cursor']`` from the previous run, or
            None for a full walk. Rows at or before it were deleted, already
            file-less, or protected when last seen — DB rows are kept forever
            while their files age out, so resuming spares each run an
            ever-growing prefix of long-dead rows. When the resumed walk
            can't reach the target, the prefix is re-checked once (catching
            rows that lost protection or regained files).

    Returns:
        dict with files_deleted, bytes_freed, resume_cursor,
        target_achievable, etc.
    """
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
        'skipped_missing': 0,
        'target_achievable': True,
        'target_reached': False,
        'resume_cursor': resume_cursor
    }

    # Get current disk usage
    usage = get_disk_usage()
    current_percent = usage['percent_used']

    if current_percent <= target_percent:
        logger.info("Disk usage already below target", extra={
            'current_percent': current_percent,
            'target_percent': target_percent
        })
        result['target_reached'] = True
        return result

    # Calculate how much we need to free
    bytes_to_free = usage['used_bytes'] - (usage['total_bytes'] * target_percent / 100)

    protected, total_count = db_manager.get_cleanup_protected_ids(
        keep_per_species=keep_per_species,
        keep_recent_per_species=keep_recent_per_species,
    )
    candidate_count = max(0, total_count - len(protected))

    # SAFETY CHECK: Estimate if we can actually reach the target
    estimated_deletable = candidate_count * ESTIMATED_SIZE_PER_DETECTION

    if estimated_deletable < bytes_to_free:
        logger.warning("Target unachievable - BirdNET data insufficient", extra={
            'current_percent': current_percent,
            'target_percent': target_percent,
            'bytes_to_free_gb': round(bytes_to_free / (1024**3), 2),
            'estimated_deletable_gb': round(estimated_deletable / (1024**3), 2),
            'candidate_count': candidate_count
        })
        result['target_achievable'] = False
        # Still proceed but will stop when candidates exhausted
        # This allows partial cleanup even when target can't be fully reached

    logger.info("Starting storage cleanup", extra={
        'current_percent': current_percent,
        'target_percent': target_percent,
        'bytes_to_free_gb': round(bytes_to_free / (1024**3), 2),
        'candidate_count': candidate_count,
        'keep_per_species': keep_per_species,
        'keep_recent_per_species': keep_recent_per_species
    })

    if candidate_count == 0:
        logger.info("No cleanup candidates found - all recordings within keep limits", extra={
            'keep_per_species': keep_per_species,
            'keep_recent_per_species': keep_recent_per_species
        })
        return result

    audio_names, spectrogram_names = _disk_filename_sets()

    def delete_pass(start_cursor, stop_cursor=None):
        """Delete unprotected rows' files along one walk segment; returns
        the (timestamp, id) of the last row it looked at."""
        cursor = start_cursor
        for detection in _scan_detections(db_manager, start_cursor, stop_cursor):
            if result['bytes_freed'] >= bytes_to_free:
                break  # leave the cursor before the unprocessed rows
            cursor = (detection['timestamp'], detection['id'])

            if detection['id'] in protected:
                continue
            if not _has_files_on_disk(detection, audio_names, spectrogram_names):
                result['skipped_missing'] += 1
                continue

            delete_result = delete_detection_files(detection)
            if delete_result['deleted_audio'] or delete_result['deleted_spectrogram']:
                result['files_deleted'] += 1
                result['bytes_freed'] += delete_result['bytes_freed']
        return cursor

    result['resume_cursor'] = delete_pass(resume_cursor)
    if result['bytes_freed'] < bytes_to_free and resume_cursor is not None:
        # The resumed tail is exhausted without reaching the target — walk
        # the prefix behind the cursor once to catch rows that lost
        # protection or regained files since it advanced. The tail cursor
        # from the first pass stays the resume point.
        logger.info("Resumed cleanup walk exhausted, re-checking rows behind the cursor")
        delete_pass(None, stop_cursor=resume_cursor)

    if result['bytes_freed'] >= bytes_to_free:
        result['target_reached'] = True

    # Log summary
    log_extra = {
        'files_deleted': result['files_deleted'],
        'bytes_freed_gb': round(result['bytes_freed'] / (1024**3), 2),
        'skipped_missing': result['skipped_missing'],
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
    last_logged_config = None
    # Carried between cleanup runs so each run resumes the oldest-first walk
    # past rows already handled; in-memory only — a restart just means the
    # next cleanup does one full walk.
    resume_cursor = None

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
                    cleanup_result = cleanup_storage(
                        db_manager,
                        target_percent=config['target_percent'],
                        keep_per_species=config['keep_per_species'],
                        keep_recent_per_species=config['keep_recent_per_species'],
                        resume_cursor=resume_cursor
                    )
                    resume_cursor = cleanup_result['resume_cursor']

            # After cleanup, so a nearly-full disk is freed before the
            # backup's free-space check asks for headroom.
            maybe_run_health_cycle(db_manager)

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
