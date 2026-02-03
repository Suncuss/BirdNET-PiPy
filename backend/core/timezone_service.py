"""Timezone service - reads from TZ env var set by container entrypoint."""

import os
from zoneinfo import ZoneInfo

from core.logging_config import get_logger

logger = get_logger(__name__)


def get_timezone() -> ZoneInfo:
    """Get current timezone as ZoneInfo object."""
    tz_str = get_timezone_str()
    try:
        return ZoneInfo(tz_str)
    except Exception:
        logger.warning(f"Invalid timezone '{tz_str}', using UTC")
        return ZoneInfo("UTC")


def get_timezone_str() -> str:
    """Get timezone name from TZ env var, or 'UTC' if not set."""
    return os.environ.get('TZ') or 'UTC'
