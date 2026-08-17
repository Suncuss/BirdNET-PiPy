"""Media ownership: the single boundary through which detection media files
are published, recorded, renamed, and removed.

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md (pillar 1).

Every detection row records the media it owns in the ``detection_media``
table (filename PK = exclusive owner) plus a denormalized ``media_bytes``
sum on the row itself, so cleanup and accounting are indexed queries
instead of filesystem walks. Identity across crashes and restored DB
histories rests on ``media_nonce``: 128 random bits minted *before* the
row insert and persisted in it, then embedded in every filename the row's
media is published under. Integer ids repeat after an old-backup restore
(sqlite_sequence regresses) and the legacy filename fields are lossy, so
the nonce is the only safe discriminator when reattaching orphans.

All functions taking a ``cursor`` run inside the caller's transaction (the
db_species pattern): ownership rows, the media_bytes recompute, and
whatever detection write they accompany commit atomically together.
"""
import os
import secrets

from config.settings import EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR
from core.logging_config import get_logger

logger = get_logger(__name__)

# 128 bits — at restore scale each leftover file is compared against the one
# new row that reused its id, so collision odds are N/2^bits; 20 bits gave
# ~25% at 305K rows. token_hex(16) = 32 lowercase hex chars.
_NONCE_BYTES = 16

# Suffix appended to temp files during publication; never attachable and
# garbage-collected by age during reconciliation.
PART_SUFFIX = '.part'

KIND_AUDIO = 'audio'
KIND_SPECTROGRAM = 'spectrogram'

KIND_DIRS = {
    KIND_AUDIO: EXTRACTED_AUDIO_DIR,
    KIND_SPECTROGRAM: SPECTROGRAM_DIR,
}


class MediaOwnershipError(Exception):
    """Base for ownership-boundary failures."""


class MediaCollisionError(MediaOwnershipError):
    """A filename is already claimed — on disk or in detection_media —
    by someone other than the caller's detection."""


class DetectionMissingError(MediaOwnershipError):
    """The owning detection row does not exist (e.g. a delete won the race
    against a concurrent create). Callers must remove any files they just
    published and write no ownership rows."""


def mint_media_nonce():
    """A row's immutable media identity; persist it in the same INSERT that
    creates the detection row, before any file exists."""
    return secrets.token_hex(_NONCE_BYTES)


def media_name_suffix(detection_id, nonce):
    """Filename suffix binding a file to one row of one DB history."""
    return f"{detection_id}-{nonce}"


def with_media_suffix(filename, detection_id, nonce):
    """The filename with the ownership suffix inserted before its extension.

    'Blackbird_90_...-00-00-00.mp3' → 'Blackbird_90_...-00-00-00_7-ab….mp3'
    """
    base, ext = os.path.splitext(filename)
    return f"{base}_{media_name_suffix(detection_id, nonce)}{ext}"


def publish_media_file(part_path, final_path):
    """Atomically claim final_path with the completed temp file.

    link()+unlink() rather than rename(): POSIX rename silently replaces an
    existing destination, and an exists() pre-check would be a TOCTOU race.
    An existing final path means another history's file already owns the
    name — surfaced as MediaCollisionError, never overwritten.

    Returns the published file's size in bytes.
    """
    try:
        os.link(part_path, final_path)
    except FileExistsError as exc:
        raise MediaCollisionError(
            f"destination already exists: {final_path}") from exc
    os.unlink(part_path)
    return os.path.getsize(final_path)


def get_or_create_media_nonce(cursor, detection_id):
    """The row's nonce, lazily initializing legacy NULL rows.

    Atomic under the caller's transaction: the conditional UPDATE only wins
    when the nonce is still NULL, and the read-back returns the stored
    winner either way, so concurrent initializers converge. Raises
    DetectionMissingError before any file could be published against a
    deleted row. Once non-NULL the nonce is immutable.
    """
    cursor.execute(
        "UPDATE detections SET media_nonce = ? "
        "WHERE id = ? AND media_nonce IS NULL",
        (mint_media_nonce(), detection_id))
    cursor.execute(
        "SELECT media_nonce FROM detections WHERE id = ?", (detection_id,))
    row = cursor.fetchone()
    if row is None:
        raise DetectionMissingError(f"detection {detection_id} does not exist")
    return row[0]


def _demote_existing_canonical(cursor, detection_id, kind, new_filename):
    """Canonical replacement: an incoming rank-0 file for a kind demotes a
    different existing rank-0 to the next free rank in the same
    transaction — the partial unique index makes two canonicals impossible,
    and without this a legitimate replacement would just hit the
    constraint."""
    cursor.execute(
        "SELECT filename FROM detection_media "
        "WHERE detection_id = ? AND kind = ? AND rank = 0", (detection_id, kind))
    existing = cursor.fetchone()
    if existing is None or existing[0] == new_filename:
        return
    cursor.execute(
        "UPDATE detection_media SET rank = ("
        "  SELECT COALESCE(MAX(rank), 0) + 1 FROM detection_media"
        "  WHERE detection_id = ? AND kind = ?) "
        "WHERE filename = ?", (detection_id, kind, existing[0]))


def recompute_media_bytes(cursor, detection_id):
    """Re-derive the denormalized media_bytes sum from detection_media —
    THE one statement defining that invariant; every restamp goes through
    here."""
    cursor.execute(
        "UPDATE detections SET media_bytes = ("
        "  SELECT COALESCE(SUM(bytes), 0) FROM detection_media"
        "  WHERE detection_id = ?) "
        "WHERE id = ?",
        (detection_id, detection_id))


def record_media(cursor, detection_id, files):
    """Record ownership of published files for one detection.

    Args:
        cursor: caller's transaction cursor
        detection_id: owning row id
        files: iterable of dicts with filename, kind, rank, bytes

    Verifies the detection still exists first (a delete racing the creator
    must produce no ownership residue — the caller removes its just-published
    files on DetectionMissingError). Idempotent per file: an identical claim
    by the same owner is a retry no-op; a claim on a name another detection
    owns raises MediaCollisionError before any row is written.
    """
    cursor.execute("SELECT media_bytes, timestamp FROM detections WHERE id = ?",
                   (detection_id,))
    row = cursor.fetchone()
    if row is None:
        raise DetectionMissingError(f"detection {detection_id} does not exist")
    was_unresolved = row[0] is None
    row_date = row[1][:10]

    to_insert = []
    for f in files:
        cursor.execute(
            "SELECT detection_id FROM detection_media WHERE filename = ?",
            (f['filename'],))
        existing = cursor.fetchone()
        if existing is None:
            to_insert.append(f)
        elif existing[0] != detection_id:
            raise MediaCollisionError(
                f"{f['filename']} already owned by detection {existing[0]}")
        # else: retry of our own claim — no-op

    for f in to_insert:
        if f.get('rank') == 0:
            _demote_existing_canonical(cursor, detection_id, f['kind'],
                                       f['filename'])
        cursor.execute(
            "INSERT INTO detection_media (filename, detection_id, kind, rank, bytes) "
            "VALUES (?, ?, ?, ?, ?)",
            (f['filename'], detection_id, f['kind'], f['rank'], f['bytes']))

    recompute_media_bytes(cursor, detection_id)
    if was_unresolved:
        # Resolving a row the frontier never saw (old-code history reached
        # through Stage 2/3 or repair): its rollup day is stale exactly
        # like a frontier resolution — same dirty-day handoff, same
        # transaction (implementation review finding 3).
        import core.db_rollups as db_rollups
        db_rollups.enqueue_dirty_days(cursor, [row_date])


def remove_media(cursor, filenames):
    """Drop ownership rows for unlinked files and restamp their owners.

    Called with the names that were actually unlinked — partial-unlink
    survivors keep their rows (a row is never stamped to zero while it
    still owns a file). Returns the affected detection ids.
    """
    affected = set()
    for name in filenames:
        cursor.execute(
            "SELECT detection_id FROM detection_media WHERE filename = ?",
            (name,))
        row = cursor.fetchone()
        if row is None:
            continue
        affected.add(row[0])
        cursor.execute(
            "DELETE FROM detection_media WHERE filename = ?", (name,))
    for detection_id in affected:
        recompute_media_bytes(cursor, detection_id)
    return affected


def unlink_owned_files(owned):
    """Unlink a row's recorded files; returns the names whose goal state
    ("file gone") now holds — including already-missing files, whose
    ownership rows must go too. Other OSErrors keep the name owned so a
    later run retries (a row is never stamped down while it still owns a
    file it couldn't remove).

    Args:
        owned: iterable of dicts with filename and kind
    """
    removed = []
    for f in owned:
        path = os.path.join(KIND_DIRS[f['kind']], f['filename'])
        try:
            os.remove(path)
            removed.append(f['filename'])
        except FileNotFoundError:
            removed.append(f['filename'])
        except OSError as e:
            logger.warning("Failed to unlink owned media file", extra={
                'path': path, 'error': str(e)})
    return removed


def rename_media(cursor, old_name, new_name):
    """Follow an on-disk rename (lazy colon→dash migration) in the record.

    A missing old_name is fine — the file may predate resolution or belong
    to an unresolved row; the frontier records the normalized name later.
    """
    cursor.execute(
        "UPDATE detection_media SET filename = ? WHERE filename = ?",
        (new_name, old_name))
    return cursor.rowcount > 0
