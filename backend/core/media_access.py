"""Signed capability URLs for detection media (audio + spectrogram).

When auth is enabled, the media file servers must not let an anonymous caller
fetch arbitrary filenames — filenames are deterministic and are listed in public
payloads, so without this an anonymous visitor could bulk-download every clip
(open-mic audio of the user's location). Instead, the bounded public payloads
carry a short-lived HMAC signature per file, and the file servers accept an
anonymous request only with a valid signature. So an anonymous visitor can fetch
exactly the clips a bounded list actually showed them, and the deterministic
filenames are useless on their own.

Owners (authenticated session) and auth-off installs bypass this entirely — the
file servers serve them by bare filename as before.

The signing key lives only in the single API process, so an in-memory cache plus
auth.json persistence is sufficient (no cross-process coordination needed).
"""
import hashlib
import hmac
import time

from core.auth import get_or_create_media_secret

_DAY = 86400
# exp is rounded up to a day boundary so the same file yields the same URL all
# day (browser/CDN cacheable); the lead of 2 days gives a 24-48h validity window.
_TTL_DAYS = 2

_cached_secret = None


def _media_secret():
    global _cached_secret
    if _cached_secret is None:
        _cached_secret = get_or_create_media_secret()
    return _cached_secret


def _current_exp(now=None):
    now = int(now if now is not None else time.time())
    return (now // _DAY + _TTL_DAYS) * _DAY


def _compute_sig(filename, exp):
    msg = f'{filename}:{exp}'.encode()
    return hmac.new(_media_secret().encode(), msg, hashlib.sha256).hexdigest()


def sign_media_query(filename):
    """Return the ``exp=..&sig=..`` query string authorizing this filename."""
    exp = _current_exp()
    return f'exp={exp}&sig={_compute_sig(filename, exp)}'


def verify_media_signature(filename, exp_raw, sig):
    """True iff ``sig`` is a valid, unexpired signature for ``filename``."""
    if not exp_raw or not sig:
        return False
    try:
        exp = int(exp_raw)
    except (TypeError, ValueError):
        return False
    if exp < int(time.time()):
        return False
    try:
        return hmac.compare_digest(sig, _compute_sig(filename, exp))
    except TypeError:
        # A non-ASCII sig query param makes compare_digest raise; treat any
        # malformed signature as a clean denial rather than a 500.
        return False
