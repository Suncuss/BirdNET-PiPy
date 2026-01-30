"""Timezone service for inferring timezone from location.

This module provides a timezone with fallback chain:

1. **Cached timezone** - From user_settings.json (set by weather service)
2. **Host timezone** - From TZ env var or system config (via tzlocal)
3. **UTC** - Ultimate fallback if all else fails

The weather service automatically extracts timezone from the Open-Meteo API
response and updates the cache. This happens in the background without
blocking startup.

Typical behavior:
- Cold start with no cache: Uses host timezone immediately, updates to
  location-accurate timezone once weather API responds
- Warm start with cache: Uses cached (accurate) timezone immediately
- Offline with cache: Uses cached timezone (no API needed)
- Location change: Uses stale cache briefly, self-corrects on next weather fetch

Thread Safety:
- All functions are thread-safe via internal locking
- Cache updates are atomic (temp file + rename)
"""

import threading
from typing import Optional
from zoneinfo import ZoneInfo

from tzlocal import get_localzone

from config.settings import TIMEZONE
from core.logging_config import get_logger

logger = get_logger(__name__)

# In-memory cache for timezone (avoids repeated file reads)
_cached_timezone: Optional[str] = TIMEZONE
_cache_lock = threading.Lock()


def get_timezone() -> ZoneInfo:
    """Get the current timezone with fallback chain.

    Returns ZoneInfo object using this priority:
    1. Cached timezone from user_settings.json
    2. Host timezone (TZ env var or system config)
    3. UTC as ultimate fallback

    Returns:
        ZoneInfo object for the determined timezone
    """
    tz_str = get_timezone_str()
    try:
        return ZoneInfo(tz_str)
    except Exception:
        logger.warning(f"Invalid timezone '{tz_str}', falling back to UTC")
        return ZoneInfo("UTC")


def get_timezone_str() -> str:
    """Get the current timezone name string with fallback chain.

    Returns timezone name using this priority:
    1. Cached timezone from user_settings.json
    2. Host timezone (TZ env var or system config)
    3. UTC as ultimate fallback

    Returns:
        IANA timezone name string (e.g., "America/New_York")
    """
    # Try cached timezone first
    cached = _get_cached_timezone()
    if cached:
        return cached

    # Fall back to host timezone
    try:
        host_tz = get_localzone()
        tz_name = str(host_tz)
        logger.debug(f"Using host timezone: {tz_name}")
        return tz_name
    except Exception as e:
        logger.warning(f"Failed to get host timezone: {e}, falling back to UTC")
        return "UTC"


def _get_cached_timezone() -> Optional[str]:
    """Get cached timezone from in-memory cache.

    Returns:
        Timezone string if cached, None otherwise
    """
    with _cache_lock:
        return _cached_timezone


def update_cached_timezone(tz: str) -> None:
    """Update the in-memory timezone cache.

    Called by weather service when it extracts timezone from API response.
    Does NOT persist to disk - that's done by weather service to avoid
    circular imports.

    Args:
        tz: IANA timezone name string (e.g., "America/New_York")
    """
    global _cached_timezone
    with _cache_lock:
        if _cached_timezone != tz:
            logger.info(f"Timezone cache updated: {_cached_timezone} -> {tz}")
            _cached_timezone = tz


def clear_cache() -> None:
    """Clear the in-memory timezone cache. Useful for testing."""
    global _cached_timezone
    with _cache_lock:
        _cached_timezone = None
