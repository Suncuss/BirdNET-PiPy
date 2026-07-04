"""Stateless signed share tokens for single-detection permalinks.

A share token lets the owner hand a non-user a link to ONE detection — its
DetectionDetails view plus that detection's two media files — without it becoming
an enumeration entry point. The detection id is a SIGNED claim inside the token,
so editing the URL to a different id invalidates the signature, and the token
grants access to nothing but that one detection. It works even when public access
is off (a private station can still share a single detection).

Stateless (itsdangerous, no DB): the token is self-contained and time-limited.
Mass revocation is by rotating the share secret (see auth.get_or_create_share_secret),
which invalidates every outstanding link at once. (Per-link revocation — a jti
allow/deny list — is a future addition; the jti is already in the payload.)
"""
import secrets

from itsdangerous import URLSafeTimedSerializer

from core.auth import get_or_create_share_secret
from core.logging_config import get_logger

logger = get_logger(__name__)

_SALT = 'birdnet.share.v1'
SHARE_TOKEN_TTL_SECONDS = 30 * 86400  # 30 days


def _serializer():
    # Built per call (not cached) so mass-revocation by rotating share_secret in
    # auth.json takes effect immediately, without restarting the API process.
    # Share verification is low-volume (only when a shared link is opened).
    return URLSafeTimedSerializer(get_or_create_share_secret(), salt=_SALT)


def mint_share_token(detection_id):
    """Create a signed token authorizing read of exactly one detection."""
    return _serializer().dumps({
        'v': 1,
        'sub': int(detection_id),
        'jti': secrets.token_hex(8),
    })


def _load(token):
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=SHARE_TOKEN_TTL_SECONDS)
    except Exception:  # noqa: BLE001 — bad/expired/tampered token = invalid
        return None


def verify_share_token(token, detection_id):
    """True iff token is valid, unexpired, and bound to exactly this detection.

    The path id must equal the signed ``sub`` so the URL id can't be mutated to
    another detection. Species coherence (id belongs to the route's species) is
    enforced separately by the endpoint's existing ``belongs`` check, so it isn't
    re-checked here.
    """
    data = _load(token)
    if not data:
        return False
    try:
        return int(data.get('sub')) == int(detection_id)
    except (TypeError, ValueError):
        return False


def share_token_subject(token):
    """Return the signed detection id for a valid token, else None.

    Used by the media endpoints to check that a token authorizes the specific
    file being requested (the token's detection's audio/spectrogram), without
    re-deriving species from the URL.
    """
    data = _load(token)
    if not data:
        return None
    try:
        return int(data.get('sub'))
    except (TypeError, ValueError):
        return None
