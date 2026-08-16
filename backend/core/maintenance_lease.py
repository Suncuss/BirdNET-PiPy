"""Cross-process maintenance lease over the shared SQLite database.

Design: internal_docs/MEDIA_OWNERSHIP_AND_ROLLUPS_2026-08-15.md (pillar 2,
index-build coordination). The one-time live-media index build holds
SQLite's writer lock for its whole duration; the API container is already
serving (compose starts main after api is healthy) and its bulk importer
is a sustained writer. This lease keeps those two long-running writers
out of each other's way.

One row in ``meta`` (key ``maintenance_lease``) holds {role, owner,
expires}. Acquisition is a check-and-set under ``BEGIN IMMEDIATE`` —
SQLite's writer lock makes the read-check-write atomic, so two contenders
cannot both see "absent" (two independently checked flags would be a
TOCTOU race). The owner token makes renewal and release owner-checked; a
crashed holder simply expires. The importer renews between batches (it
can run for hours — a fixed timeout must never expire a live import); the
index build cannot renew mid-CREATE INDEX, so its TTL is sized to the
worst-case build with margin.
"""
import json
import secrets
import time

from core.logging_config import get_logger

logger = get_logger(__name__)

_LEASE_KEY = 'maintenance_lease'

# The build can't heartbeat mid-statement; worst cold-SD build measured in
# tens of seconds — 15 minutes is margin, and a crashed builder only
# delays the next importer by the remainder.
INDEX_BUILD_TTL_SECONDS = 15 * 60

# Importers renew every batch, so a short TTL bounds crash recovery.
IMPORT_TTL_SECONDS = 2 * 60


def mint_owner_token():
    return secrets.token_hex(8)


def _read_lease(cursor):
    cursor.execute("SELECT value FROM meta WHERE key = ?", (_LEASE_KEY,))
    row = cursor.fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def acquire(db_manager, role, owner, ttl_seconds, now=None):
    """Try to take the lease. Returns True on success; False while another
    live holder (any role, different owner) has it. Re-acquiring with the
    same owner refreshes the expiry (idempotent retry)."""
    now = now if now is not None else time.time()
    with db_manager.get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        lease = _read_lease(cur)
        if lease and lease['owner'] != owner and lease['expires'] > now:
            conn.rollback()
            return False
        cur.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_LEASE_KEY, json.dumps({
                'role': role, 'owner': owner,
                'expires': now + ttl_seconds})))
        conn.commit()
    logger.info("Maintenance lease acquired", extra={
        'role': role, 'ttl_seconds': ttl_seconds})
    return True


def renew(db_manager, owner, ttl_seconds, now=None):
    """Extend the lease iff we still own it. Returns False if lost (expired
    and taken, or released) — the holder must stop its maintenance work."""
    now = now if now is not None else time.time()
    with db_manager.get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        lease = _read_lease(cur)
        if not lease or lease['owner'] != owner:
            conn.rollback()
            return False
        lease['expires'] = now + ttl_seconds
        cur.execute("UPDATE meta SET value = ? WHERE key = ?",
                    (json.dumps(lease), _LEASE_KEY))
        conn.commit()
    return True


def release(db_manager, owner):
    """Owner-checked release; a stranger's release attempt is a no-op."""
    with db_manager.get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        lease = _read_lease(cur)
        if not lease or lease['owner'] != owner:
            conn.rollback()
            return False
        cur.execute("DELETE FROM meta WHERE key = ?", (_LEASE_KEY,))
        conn.commit()
    return True


class MaintenanceInProgressError(Exception):
    """Raised when a short interactive mutation would contend with the
    one-time index build. Raised BEFORE any filesystem side effect, so
    callers can return a retryable maintenance response having touched
    nothing (design: never a maintenance error after irreversible work)."""


def index_build_active(db_manager, now=None):
    """Whether the live-media index build currently holds the lease.

    Only the build blocks short interactive mutations — a running import
    holds the lease for hours but its batch writes interleave fine with a
    user's delete; the build holds SQLite's writer lock for its entire
    statement, which is what would strand a mutation mid-operation."""
    now = now if now is not None else time.time()
    with db_manager.get_db_connection() as conn:
        lease = _read_lease(conn.cursor())
    return bool(lease and lease['role'] == 'index_build'
                and lease['expires'] > now)


def acquire_with_wait(db_manager, role, owner, ttl_seconds,
                      deadline_seconds=INDEX_BUILD_TTL_SECONDS,
                      on_wait=None, yield_control=None, poll_seconds=2):
    """Acquire the lease, politely waiting out a live holder.

    on_wait fires once, on first contention only — the happy path stays
    silent. Raises MaintenanceInProgressError past the deadline (the
    holder's own TTL bounds how long that can be)."""
    deadline = time.time() + deadline_seconds
    waited = False
    while not acquire(db_manager, role, owner, ttl_seconds):
        if not waited:
            if on_wait:
                on_wait()
            waited = True
        if time.time() > deadline:
            raise MaintenanceInProgressError(
                f'maintenance lease unavailable for {role}')
        if yield_control:
            yield_control()
        time.sleep(poll_seconds)
