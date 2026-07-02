"""Shared-secret authentication for internal-only endpoints.

The main processing container and the API container are separate processes that
share the ``data/`` volume. ``require_internal`` used to trust only the request's
source IP, but nginx proxies *external* requests from a 172.x docker address, so
every proxied request looked "internal" and an external client could POST to
``/api/broadcast/*`` (injecting spoofed detections to all WebSocket clients).

A shared secret on a request header closes that hole: the secret is generated
once and persisted in a file that both processes read from the shared data
volume, so no environment/compose changes are needed. The IP check is kept as a
cheap secondary filter, but the secret is the real gate.
"""
import hmac
import os
import secrets

from config.settings import BASE_DIR
from core.logging_config import get_logger

logger = get_logger(__name__)

INTERNAL_SECRET_HEADER = 'X-Internal-Secret'

# Module-level so tests can redirect it into a tempdir.
_SECRET_FILE = os.path.join(BASE_DIR, 'data', 'config', 'internal_secret')

# Cached after first read so per-detection broadcasts don't re-open the file.
_cached_secret = None


def _read_secret_file():
    """Return the stored secret, or None if the file is absent/empty."""
    try:
        with open(_SECRET_FILE) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def get_or_create_internal_secret():
    """Return the shared internal secret, generating + persisting it if absent.

    Safe to call concurrently from the main and API processes at startup: the
    file is created with ``O_EXCL``, and a loser of the create race reads the
    winner's value instead of clobbering it.
    """
    global _cached_secret
    if _cached_secret:
        return _cached_secret

    existing = _read_secret_file()
    if existing:
        _cached_secret = existing
        return existing

    os.makedirs(os.path.dirname(_SECRET_FILE), exist_ok=True)
    candidate = secrets.token_hex(32)
    try:
        fd = os.open(_SECRET_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, candidate.encode())
        finally:
            os.close(fd)
        _cached_secret = candidate
        logger.info("Generated internal broadcast secret")
    except FileExistsError:
        # A concurrent process created it first — use theirs.
        _cached_secret = _read_secret_file()
    return _cached_secret


def verify_internal_secret(provided):
    """Constant-time check of a presented secret against the stored one."""
    if not provided:
        return False
    expected = get_or_create_internal_secret()
    if not expected:
        return False
    return hmac.compare_digest(provided, expected)
