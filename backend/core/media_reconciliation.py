"""Media reconciliation: scheduled repair of disk<->DB ownership drift.

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md (pillar 1,
"Reconciliation sweep"). Drift is a scheduled job, never a hot-path
obligation: the startup scan (boots are when crashes happened) and the
weekly sweep repair every RECOGNIZABLE state and only report the rest.

Repair-vs-report philosophy:
- An unowned final-name file whose parsed id+nonce EXACTLY matches its
  row's persisted media_nonce is reattached — the interrupted-creation
  crash window. The id alone is never sufficient: after an old-backup
  restore, sqlite_sequence regresses and ids (even with identical lossy
  filename fields) recur across histories; only the nonce separates them.
- A parseable file whose row is missing or whose nonce mismatches is
  removed after a grace period (deleted-row or restored-backup residue).
- ``.part`` temp files are garbage-collected by age; publication
  guarantees a final name always holds a complete file.
- Legacy-pattern files (no id+nonce) are the resolution frontier's
  territory: never auto-deleted here, only counted once the frontier is
  complete and they remain unowned.
"""
import os
import re
import time

from core.logging_config import get_logger
from core.media_ownership import (
    KIND_AUDIO,
    KIND_DIRS,
    KIND_SPECTROGRAM,
    PART_SUFFIX,
    DetectionMissingError,
    recompute_media_bytes,
    record_media,
    rename_media,
    with_media_suffix,
)

# Acyclic: storage_manager's own reference to this module is
# function-local, so a top-level import here cannot form a cycle.
from core.storage_manager import _detection_filename_candidates

logger = get_logger(__name__)

# id + 32-hex nonce before the media extension — the new-era name shape.
_IDENTITY_RE = re.compile(r'_(\d+)-([0-9a-f]{32})\.(mp3|webp)$')

_EXT_KIND = {'.mp3': KIND_AUDIO, '.webp': KIND_SPECTROGRAM}

# A .part older than this is an abandoned write, not one in progress.
PART_GRACE_SECONDS = 6 * 3600

# An unowned nonce-named file younger than this may still be mid-creation
# (published, record_media imminent); older, it is crash residue.
ORPHAN_GRACE_SECONDS = 24 * 3600

# Ownership rows audited per batch in the DB-direction pass.
_AUDIT_BATCH_ROWS = 500


def parse_media_identity(filename):
    """(detection_id, nonce) parsed from a new-era name, else None."""
    match = _IDENTITY_RE.search(filename)
    if not match:
        return None
    return int(match.group(1)), match.group(2)


def _file_age_seconds(path, now):
    try:
        return now - os.path.getmtime(path)
    except OSError:
        return 0


def _canonical_fields_match(cursor, detection_id, nonce, filename):
    """Sanity assertion behind the nonce match: the filename must be one
    the row's own fields would generate (candidate names + this row's
    id+nonce suffix). A nonce match with mismatched fields means something
    genuinely odd — report, never attach."""
    cursor.execute(
        "SELECT common_name, confidence, timestamp, extra, audio_source "
        "FROM detections WHERE id = ?", (detection_id,))
    row = cursor.fetchone()
    if row is None:
        return False
    detection = {'id': detection_id, 'common_name': row[0],
                 'confidence': row[1], 'timestamp': row[2],
                 'extra': row[3], 'audio_source': row[4]}
    expected = set()
    for candidate in _detection_filename_candidates(detection):
        for key in ('audio_filename', 'spectrogram_filename'):
            if candidate[key]:
                expected.add(
                    with_media_suffix(candidate[key], detection_id, nonce))
    return filename in expected


def _reattach(cursor, detection_id, filename, kind, size):
    """Record ownership of a repaired orphan via record_media — the ONE
    home of the ownership-transition contract (existence refusal, the
    NULL-to-resolved dirty-day handoff, media_bytes recompute). This
    wrapper only derives the rank (next free for the kind; the canonical
    partial unique index would reject a second rank 0) and maps a
    vanished owner to False: under the caller's writer lock, refusal is
    the only correct answer to a row a concurrent delete removed (with
    no FK an insert would succeed and orphan the ownership row).
    Returns True on reattachment."""
    cursor.execute(
        "SELECT COUNT(*) FROM detection_media "
        "WHERE detection_id = ? AND kind = ?", (detection_id, kind))
    rank = cursor.fetchone()[0]
    try:
        record_media(cursor, detection_id, [
            {'filename': filename, 'kind': kind, 'rank': rank, 'bytes': size}])
    except DetectionMissingError:
        return False
    return True


_SCAN_CHUNK_FILES = 500


def _chunked(iterator, size):
    chunk = []
    for item in iterator:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _classify_unowned(conn, cur, name, path, now, stats):
    """Repair or classify one unowned file (scan_disk's per-file arm)."""
    identity = parse_media_identity(name)
    if identity is None:
        ext = os.path.splitext(name)[1]
        if ext in _EXT_KIND:
            stats['legacy_unowned'] += 1  # frontier territory
        else:
            stats['unrecognized'] += 1
        return

    detection_id, nonce = identity
    cur.execute(
        "SELECT media_nonce FROM detections WHERE id = ?",
        (detection_id,))
    row = cur.fetchone()
    if row is not None and row[0] == nonce:
        # Repair happens under the writer lock, with every
        # check REVALIDATED inside it — a delete committing
        # after the reads above must turn this into a
        # refusal, never a ghost ownership row
        # (implementation re-review R2).
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur.execute(
                "SELECT media_nonce FROM detections "
                "WHERE id = ?", (detection_id,))
            locked_row = cur.fetchone()
            cur.execute(
                "SELECT 1 FROM detection_media "
                "WHERE filename = ?", (name,))
            still_unowned = cur.fetchone() is None
            if (locked_row is None
                    or locked_row[0] != nonce
                    or not still_unowned
                    or not _canonical_fields_match(
                        cur, detection_id, nonce, name)):
                conn.rollback()
                if locked_row is not None and still_unowned:
                    logger.warning(
                        "Orphan nonce matches but fields do "
                        "not - reporting, not attaching",
                        extra={'orphan': name})
                    stats['unrecognized'] += 1
                return
            try:
                size = os.path.getsize(path)
            except OSError:
                conn.rollback()
                return
            # Interrupted creation: publication guarantees
            # the file is complete; the nonce proves the row.
            if _reattach(cur, detection_id, name,
                         _EXT_KIND[os.path.splitext(name)[1]],
                         size):
                conn.commit()
                stats['reattached'] += 1
            else:
                conn.rollback()
        except Exception:
            conn.rollback()
            raise
    elif _file_age_seconds(path, now) > ORPHAN_GRACE_SECONDS:
        # Deleted row, or another history's residue — the
        # nonce mismatch is the refusal; never attach.
        try:
            os.remove(path)
            stats['residue_removed'] += 1
        except OSError:
            pass
    else:
        stats['pending_grace'] += 1


def scan_disk(db_manager, now=None):
    """Disk-direction pass: repair or classify every file, streaming (no
    directory snapshot is ever held). Returns a counters dict."""
    now = now if now is not None else time.time()
    stats = {'reattached': 0, 'residue_removed': 0, 'parts_removed': 0,
             'pending_grace': 0, 'legacy_unowned': 0, 'unrecognized': 0}

    for directory in KIND_DIRS.values():
        try:
            entries = os.scandir(directory)
        except OSError:
            continue
        with entries:
            for chunk in _chunked(entries, _SCAN_CHUNK_FILES):
                candidates = []
                for entry in chunk:
                    name = entry.name
                    path = entry.path
                    if name.endswith(PART_SUFFIX):
                        if _file_age_seconds(path, now) > PART_GRACE_SECONDS:
                            try:
                                os.remove(path)
                                stats['parts_removed'] += 1
                            except OSError:
                                pass
                        continue
                    candidates.append((name, path))
                if not candidates:
                    continue

                with db_manager.get_db_connection() as conn:
                    cur = conn.cursor()
                    # One membership probe per chunk instead of one query
                    # per file: on a healthy station nearly every file is
                    # owned, so this is the boot-time hot path (a million
                    # files would otherwise mean a million round trips).
                    # Advisory only — the repair path revalidates ownership
                    # under the writer lock.
                    placeholders = ','.join('?' * len(candidates))
                    cur.execute(
                        f"SELECT filename FROM detection_media "
                        f"WHERE filename IN ({placeholders})",
                        [name for name, _ in candidates])
                    owned = {row[0] for row in cur.fetchall()}
                    for name, path in candidates:
                        if name in owned:
                            continue  # size drift handled DB-direction
                        _classify_unowned(conn, cur, name, path, now, stats)

    if any(stats.values()):
        logger.info("Media disk scan completed", extra=stats)
    return stats


def audit_ownership(db_manager):
    """DB-direction pass over detection_media: vanished files lose their
    rows, deleted owners lose their files, sizes restat, and the
    denormalized media_bytes sums are re-derived. Batched keyset walk.
    Returns a counters dict."""
    stats = {'vanished_rows_removed': 0, 'deleted_owner_files': 0,
             'sizes_updated': 0, 'sums_fixed': 0, 'renames_followed': 0}
    last_filename = ''
    while True:
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT m.filename, m.detection_id, m.kind, m.bytes, "
                "       d.id AS owner_id "
                "FROM detection_media m LEFT JOIN detections d "
                "  ON d.id = m.detection_id "
                "WHERE m.filename > ? ORDER BY m.filename LIMIT ?",
                (last_filename, _AUDIT_BATCH_ROWS))
            batch = cur.fetchall()
            if not batch:
                break
            touched_owners = set()
            for row in batch:
                last_filename = row['filename']
                path = os.path.join(KIND_DIRS[row['kind']], row['filename'])
                if row['owner_id'] is None:
                    # Old-code delete left the ownership row behind (no FK
                    # by design): finish the job.
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    cur.execute("DELETE FROM detection_media WHERE filename = ?",
                                (row['filename'],))
                    stats['deleted_owner_files'] += 1
                    continue
                if not os.path.exists(path):
                    # Defensive: a rename by downgraded code left the
                    # record behind the disk — follow a normalized sibling
                    # before declaring the file gone.
                    normalized = row['filename'].replace(':', '-')
                    normalized_path = os.path.join(
                        KIND_DIRS[row['kind']], normalized)
                    if normalized != row['filename'] and os.path.exists(normalized_path):
                        rename_media(cur, row['filename'], normalized)
                        stats['renames_followed'] += 1
                        continue
                    cur.execute("DELETE FROM detection_media WHERE filename = ?",
                                (row['filename'],))
                    touched_owners.add(row['detection_id'])
                    stats['vanished_rows_removed'] += 1
                    continue
                size = os.path.getsize(path)
                if size != row['bytes']:
                    cur.execute(
                        "UPDATE detection_media SET bytes = ? WHERE filename = ?",
                        (size, row['filename']))
                    touched_owners.add(row['detection_id'])
                    stats['sizes_updated'] += 1
            for owner in touched_owners:
                recompute_media_bytes(cur, owner)
            conn.commit()

    # Denormalization drift from any other cause: re-derive rows whose sum
    # disagrees (batched; resolved rows only — NULL stays the frontier's).
    last_id = 0
    while True:
        with db_manager.get_db_connection() as conn:
            cur = conn.cursor()
            # Keyset on id: fixed rows stop matching either way, but without
            # the cursor each batch would restart the correlated scan from
            # the top of the table — quadratic exactly when drift is worst.
            cur.execute(
                "SELECT d.id FROM detections d WHERE d.id > ? "
                "AND d.media_bytes IS NOT NULL "
                "AND d.media_bytes != (SELECT COALESCE(SUM(bytes), 0) "
                "  FROM detection_media WHERE detection_id = d.id) "
                "ORDER BY d.id LIMIT ?",
                (last_id, _AUDIT_BATCH_ROWS))
            drifted = [row[0] for row in cur.fetchall()]
            if drifted:
                last_id = drifted[-1]
            for detection_id in drifted:
                recompute_media_bytes(cur, detection_id)
            conn.commit()
        stats['sums_fixed'] += len(drifted)
        if len(drifted) < _AUDIT_BATCH_ROWS:
            break

    if any(stats.values()):
        logger.info("Media ownership audit completed", extra=stats)
    return stats


def run_reconciliation(db_manager):
    """The full weekly sweep: disk direction then DB direction."""
    disk_stats = scan_disk(db_manager)
    audit_stats = audit_ownership(db_manager)
    return {**disk_stats, **audit_stats}
