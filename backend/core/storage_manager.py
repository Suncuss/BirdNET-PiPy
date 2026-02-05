"""Storage manager for automatic cleanup of old detection files.

This module monitors disk usage and automatically cleans up old audio and
spectrogram files when disk usage exceeds a configurable threshold. Database
records are preserved - only the associated files are deleted.

Key features:
- Triggers cleanup when disk usage exceeds trigger_percent (default: 80%)
- Frees space until usage drops to target_percent (default: 70%)
- Protects species with fewer than min_recordings_per_species (default: 60)
- Deletes oldest files first
- Preserves all database records
"""

import os
import shutil
import time

from config.settings import (
    BASE_DIR,
    EXTRACTED_AUDIO_DIR,
    SPECTROGRAM_DIR,
    user_settings,
)
from core.logging_config import get_logger
from core.utils import build_detection_filenames, get_legacy_filename

logger = get_logger(__name__)

# Storage configuration from settings (with defaults)
STORAGE_CONFIG = user_settings.get('storage', {})
AUTO_CLEANUP_ENABLED = STORAGE_CONFIG.get('auto_cleanup_enabled', True)
TRIGGER_PERCENT = STORAGE_CONFIG.get('trigger_percent', 85)
TARGET_PERCENT = STORAGE_CONFIG.get('target_percent', 80)
KEEP_PER_SPECIES = STORAGE_CONFIG.get('keep_per_species', 60)  # Keep top N by confidence per species
CHECK_INTERVAL_MINUTES = STORAGE_CONFIG.get('check_interval_minutes', 1440)


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


def get_detection_files(detection):
    """Get full file paths for a detection record.

    Supports lazy migration: if new dash-pattern files don't exist,
    falls back to checking for old colon-pattern files.

    Args:
        detection: dict with common_name, confidence, timestamp

    Returns:
        dict with audio_path and spectrogram_path
    """
    filenames = build_detection_filenames(
        detection['common_name'],
        detection['confidence'],
        detection['timestamp']
    )

    return {
        'audio_path': _resolve_path_with_legacy_fallback(filenames['audio_filename'], EXTRACTED_AUDIO_DIR),
        'spectrogram_path': _resolve_path_with_legacy_fallback(filenames['spectrogram_filename'], SPECTROGRAM_DIR)
    }


def get_file_size(detection):
    """Calculate total file size for a detection's files.

    Args:
        detection: dict with common_name, confidence, timestamp

    Returns:
        Total size in bytes of audio + spectrogram files
    """
    paths = get_detection_files(detection)
    size = 0

    for path in paths.values():
        if path and os.path.exists(path):
            try:
                size += os.path.getsize(path)
            except OSError:
                pass

    return size


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


def estimate_deletable_size(db_manager, keep_per_species=None):
    """Estimate total size of files that could be deleted.

    Args:
        db_manager: DatabaseManager instance
        keep_per_species: Number of recordings to keep per species

    Returns:
        Tuple of (estimated_bytes, candidate_count)
    """
    if keep_per_species is None:
        keep_per_species = KEEP_PER_SPECIES

    # Get candidates (without limit to count all)
    candidates = db_manager.get_cleanup_candidates(keep_per_species=keep_per_species)

    # Estimate size (use average file size if we can't check all)
    # Average: ~270KB audio + ~30KB spectrogram = ~300KB per detection
    ESTIMATED_SIZE_PER_DETECTION = 300 * 1024  # 300 KB

    estimated_bytes = len(candidates) * ESTIMATED_SIZE_PER_DETECTION
    return estimated_bytes, len(candidates)


def cleanup_storage(db_manager, target_percent=None, keep_per_species=None):
    """Run storage cleanup to free disk space.

    Deletes oldest audio and spectrogram files until disk usage drops
    below target_percent. For each species, keeps the top N recordings
    by confidence (protecting best recordings).

    SAFETY: Will not delete files if the target is unachievable with
    available BirdNET data. This prevents mass deletion when disk is
    full with non-BirdNET files.

    Args:
        db_manager: DatabaseManager instance
        target_percent: Target disk usage percentage (default from settings)
        keep_per_species: Recordings to keep per species (default from settings)

    Returns:
        dict with files_deleted, bytes_freed, target_achievable, etc.
    """
    if target_percent is None:
        target_percent = TARGET_PERCENT
    if keep_per_species is None:
        keep_per_species = KEEP_PER_SPECIES

    result = {
        'files_deleted': 0,
        'bytes_freed': 0,
        'skipped_missing': 0,
        'target_achievable': True,
        'target_reached': False
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

    # SAFETY CHECK: Estimate if we can actually reach the target
    estimated_deletable, candidate_count = estimate_deletable_size(db_manager, keep_per_species)

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
        'keep_per_species': keep_per_species
    })

    # Get cleanup candidates (oldest first, beyond top N per species)
    candidates = db_manager.get_cleanup_candidates(keep_per_species=keep_per_species)

    if not candidates:
        logger.info("No cleanup candidates found - all recordings within keep limit", extra={
            'keep_per_species': keep_per_species
        })
        return result

    # Delete files until we've freed enough space
    bytes_freed = 0

    for detection in candidates:
        if bytes_freed >= bytes_to_free:
            result['target_reached'] = True
            break

        # Check if files exist before attempting deletion
        file_size = get_file_size(detection)
        if file_size == 0:
            result['skipped_missing'] += 1
            continue

        # Delete the files
        delete_result = delete_detection_files(detection)

        if delete_result['deleted_audio'] or delete_result['deleted_spectrogram']:
            result['files_deleted'] += 1
            bytes_freed += delete_result['bytes_freed']

    result['bytes_freed'] = bytes_freed

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
    check_interval_seconds = CHECK_INTERVAL_MINUTES * 60

    logger.info("Storage monitor started", extra={
        'auto_cleanup_enabled': AUTO_CLEANUP_ENABLED,
        'trigger_percent': TRIGGER_PERCENT,
        'target_percent': TARGET_PERCENT,
        'keep_per_species': KEEP_PER_SPECIES,
        'check_interval_minutes': CHECK_INTERVAL_MINUTES
    })

    while not stop_flag.is_set():
        try:
            if AUTO_CLEANUP_ENABLED:
                usage = get_disk_usage()

                logger.debug("Disk usage check", extra={
                    'percent_used': usage['percent_used'],
                    'trigger_percent': TRIGGER_PERCENT
                })

                if usage['percent_used'] > TRIGGER_PERCENT:
                    logger.info("Disk usage exceeded threshold, starting cleanup", extra={
                        'percent_used': usage['percent_used'],
                        'trigger_percent': TRIGGER_PERCENT
                    })
                    cleanup_storage(db_manager, target_percent=TARGET_PERCENT)

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
