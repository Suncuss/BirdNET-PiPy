"""Timezone service — single source of truth for application timezone.

Reads timezone from the user settings file (location.timezone), not the
TZ environment variable.  A lightweight mtime-keyed cache with a TTL
guard avoids the cost of get_runtime_settings() deep-copy and repeated
stat() syscalls on the hot path (logging formatters call this on every
log line).
"""

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import USER_SETTINGS_PATH
from core.runtime_config import _safe_mtime, get_runtime_settings

_UTC = ZoneInfo("UTC")

# Mtime-keyed cache with TTL — avoids deep-copy and stat() on the hot path.
_lock = threading.Lock()
_tz_mtime: float | None = None
_tz_str: str = "UTC"
_tz_obj: ZoneInfo = _UTC
_last_check: float = 0.0
_CHECK_INTERVAL: float = 1.0  # seconds between stat() calls


def _refresh_cache() -> None:
    """Re-read timezone from settings if the file has changed."""
    global _tz_mtime, _tz_str, _tz_obj, _last_check

    now = time.monotonic()
    if now - _last_check < _CHECK_INTERVAL:
        return

    with _lock:
        # Re-check under lock (another thread may have refreshed)
        if now - _last_check < _CHECK_INTERVAL:
            return
        _last_check = now

        mtime = _safe_mtime(USER_SETTINGS_PATH)
        if mtime is None or mtime == _tz_mtime:
            return

        _tz_mtime = mtime
        settings = get_runtime_settings()
        new_str = settings.get("location", {}).get("timezone") or "UTC"

        if new_str != _tz_str:
            _tz_str = new_str
            try:
                _tz_obj = ZoneInfo(new_str)
            except Exception:
                # Silent fallback — this function is called from logging
                # formatters, so logging here would cause infinite recursion.
                _tz_obj = _UTC
                _tz_str = "UTC"


def get_timezone_str() -> str:
    """Get timezone name from config file, or 'UTC' if not set."""
    _refresh_cache()
    return _tz_str


def get_timezone() -> ZoneInfo:
    """Get current timezone as ZoneInfo object.

    Returns UTC silently on invalid timezone — never logs, to avoid
    recursion when called from logging formatters.
    """
    _refresh_cache()
    return _tz_obj


def local_now() -> datetime:
    """Get current local time based on configured timezone.

    Returns a naive datetime in the user's local timezone.
    Uses UTC from the OS, then converts — no dependency on TZ env var.
    """
    return datetime.now(get_timezone()).replace(tzinfo=None)
