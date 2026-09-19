"""Offline coordinates-to-timezone lookup.

Kept free of core/config imports: the settings loader calls it while
config.settings may still be initializing (an invalid saved timezone is
repaired from the coordinates), so nothing here may import the runtime.
"""
import logging

logger = logging.getLogger(__name__)


def get_timezone_for_location(lat: float, lon: float) -> str | None:
    """Offline timezone lookup. Returns IANA timezone or None on failure.

    tzfpy's simplified polygons leave rare hairline gaps at zone borders
    (and at exactly ±180° longitude) where lookup returns nothing; retrying
    a few km to each side recovers a point sitting in such a gap. The import
    stays deferred so only the location-save path ever pays for it.
    """
    try:
        from tzfpy import get_tz
        for dlat, dlon in ((0, 0), (0.1, 0), (-0.1, 0), (0, 0.1), (0, -0.1)):
            timezone = get_tz(lon + dlon, lat + dlat)  # tzfpy takes lng first
            if timezone:
                logger.info(f"Resolved timezone: {timezone}")
                return timezone
        logger.warning(f"No timezone found for ({lat}, {lon})")
        return None
    except Exception as e:
        logger.error(f"Timezone lookup failed: {e}")
        return None
