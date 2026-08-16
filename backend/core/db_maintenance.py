"""Periodic database health: integrity checks and rotating backups.

The detections database is the user's entire observation history, usually
living on an SD card — the storage medium most likely to corrupt it. This
module gives the storage monitor loop two weekly tasks:

- ``PRAGMA quick_check``: catches page-level corruption early and loudly
  (CRITICAL log) instead of at some later random query failure.
- ``VACUUM INTO`` a rotated backup: an online, consistent, compacted
  snapshot next to the live file. This protects against corruption and
  app-level accidents, not against losing the disk itself.

Restore procedure: stop the services, replace ``data/db/birds.db`` with
the newest file from ``data/db/backups/``, delete ``birds.db-wal`` and
``birds.db-shm`` if present, start the services. Detections made after
the backup are lost; audio/spectrogram files are untouched.

Both tasks are stateless about scheduling: the last successful
quick_check is the mtime of a marker file, the last backup is the mtime
of the newest backup file. A failed quick_check does not touch the
marker, so it re-runs — and re-alerts — on the next monitor cycle.
"""
import os
import re
import shutil
import sqlite3
import time

from core.logging_config import get_logger

logger = get_logger(__name__)

HEALTH_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly, both tasks

BACKUPS_TO_KEEP = 2

# VACUUM INTO needs room for one compacted copy; require headroom beyond
# the current file size so a backup can never be what fills the disk.
FREE_SPACE_FACTOR = 1.2

_CHECK_MARKER = '.last-quick-check'
_BACKUP_SUFFIX = '.db'
_TMP_SUFFIX = '.tmp'

# Housekeeping (rotation, stale-tmp sweep) touches ONLY files this module
# generated — users park manual saves next to the backups, and deleting
# a file we didn't create is data loss.
_OWNED_FILE = re.compile(r'^birds-\d{8}-\d{6}\.db(\.tmp)?$')


def _backup_dir(db_path):
    return os.path.join(os.path.dirname(db_path), 'backups')


def _marker_path(db_path):
    return os.path.join(os.path.dirname(db_path), _CHECK_MARKER)


def _is_due(path, now):
    """True when ``path`` is missing or older than the health interval."""
    try:
        return now - os.path.getmtime(path) >= HEALTH_INTERVAL_SECONDS
    except OSError:
        return True


def _list_backups(backup_dir):
    """Generated backup files, oldest first (the timestamped names sort
    chronologically). Foreign files in the directory are not ours to touch."""
    try:
        names = [n for n in os.listdir(backup_dir)
                 if _OWNED_FILE.match(n) and n.endswith(_BACKUP_SUFFIX)]
    except OSError:
        return []
    return sorted(os.path.join(backup_dir, n) for n in names)


def run_quick_check(db_manager):
    """Run PRAGMA quick_check; log CRITICAL and return False on corruption.

    Reads through a fresh read-only connection (see
    open_readonly_connection): the check must observe the actual file, and
    a missing or foreign/empty file must FAIL — otherwise the backup
    rotation would happily replace both good backups with snapshots of
    nothing.
    """
    try:
        conn = db_manager.open_readonly_connection()
        try:
            rows = [row[0] for row in conn.execute("PRAGMA quick_check")]
            if rows == ['ok'] and conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='detections'").fetchone() is None:
                # Structurally sound but not our database (e.g. zero-length
                # after a truncating failure) — nothing worth backing up.
                rows = ['detections table missing']
        finally:
            conn.close()
    except sqlite3.Error as exc:
        # A missing file fails the read-only open; severe corruption can
        # make the check itself throw rather than return error rows —
        # same verdict either way.
        rows = [str(exc)]

    if rows == ['ok']:
        logger.info("Database integrity check passed")
        return True

    logger.critical(
        "DATABASE INTEGRITY CHECK FAILED — the detections database "
        "reports corruption. A backup, if one exists, is in the backups "
        "folder next to the database file. First errors: %s",
        '; '.join(rows[:5]),
    )
    return False


def create_backup(db_manager, now=None):
    """Write a compacted snapshot via VACUUM INTO and rotate old ones.

    Returns the new backup's path, or None when skipped (low disk space)
    or failed. The copy lands under a .tmp name and is renamed only on
    success, so a crash mid-backup never leaves a plausible-looking but
    truncated backup in rotation. ``now`` stamps the filename (defaults
    to the current time).
    """
    db_path = db_manager.db_path
    backup_dir = _backup_dir(db_path)
    os.makedirs(backup_dir, exist_ok=True)

    # A leftover generated .tmp means a previous attempt died mid-copy
    for name in os.listdir(backup_dir):
        if _OWNED_FILE.match(name) and name.endswith(_TMP_SUFFIX):
            os.unlink(os.path.join(backup_dir, name))

    db_size = os.path.getsize(db_path)
    free = shutil.disk_usage(backup_dir).free
    needed = int(db_size * FREE_SPACE_FACTOR)
    if free < needed:
        logger.warning(
            "Skipping database backup: not enough free space "
            f"({free // 1024**2}MB free, need {needed // 1024**2}MB)")
        return None

    stamp = time.strftime('%Y%m%d-%H%M%S',
                          time.localtime(now if now is not None else time.time()))
    final_path = os.path.join(backup_dir, f'birds-{stamp}{_BACKUP_SUFFIX}')
    tmp_path = final_path + _TMP_SUFFIX

    started = time.monotonic()
    try:
        with db_manager.get_db_connection() as conn:
            conn.execute("VACUUM INTO ?", (tmp_path,))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    os.replace(tmp_path, final_path)

    backups = _list_backups(backup_dir)
    for stale in backups[:-BACKUPS_TO_KEEP]:
        os.unlink(stale)

    logger.info("Database backup written", extra={
        'backup_path': final_path,
        'size_mb': os.path.getsize(final_path) // 1024**2,
        'duration_s': round(time.monotonic() - started, 1),
        'backups_kept': min(len(backups), BACKUPS_TO_KEEP),
    })
    return final_path


def maybe_run_health_cycle(db_manager, now=None):
    """Run whichever weekly health tasks are due. Called by the storage
    monitor loop each iteration; cheap (two stat calls) when nothing is due.

    The backup is gated on the integrity check passing — a corrupt live
    file must never rotate a good backup out of existence.
    """
    now = now if now is not None else time.time()
    db_path = db_manager.db_path
    marker = _marker_path(db_path)

    check_due = _is_due(marker, now)
    backups = _list_backups(_backup_dir(db_path))
    backup_due = not backups or _is_due(backups[-1], now)

    if not check_due and not backup_due:
        return

    if not run_quick_check(db_manager):
        return  # marker untouched: re-check (and re-alert) next cycle
    with open(marker, 'w'):
        pass
    os.utime(marker, (now, now))

    # Weekly corrective rewind (media-ownership design, pillar 2): a NULL
    # row behind a caught-up frontier means an older release's importer
    # wrote historical rows the monotone cursor can't see — pull the
    # cursor back so the ordinary walk re-closes the gap. Function-local
    # import: media_frontier imports storage_manager, which imports here.
    from core.media_frontier import corrective_rewind
    corrective_rewind(db_manager)

    # Weekly media reconciliation: repair disk<->DB ownership drift in
    # both directions (recognizable states repaired, the rest reported).
    from core.media_reconciliation import run_reconciliation
    try:
        run_reconciliation(db_manager)
    except Exception:
        logger.error("Media reconciliation failed", exc_info=True)

    # Weekly rollup audit: complete-bucket comparison in both directions
    # (a count-only backstop can't see cross-day net-zero drift from
    # downgraded writers); mismatched days re-enter the dirty queue.
    from core.db_rollups import audit_rollups
    try:
        audit_rollups(db_manager)
    except Exception:
        logger.error("Rollup audit failed", exc_info=True)

    if backup_due:
        create_backup(db_manager, now=now)
