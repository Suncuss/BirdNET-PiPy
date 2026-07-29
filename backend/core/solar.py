"""Solar position math for day/night classification.

NOAA's low-accuracy solar position formula (General Solar Position
Calculations, gml.noaa.gov/grad/solcalc): pure arithmetic, no network, no
tables, accurate to ~1-2 minutes at the horizon crossing — plenty for
choosing a day vs night weather icon.

Deliberately computes solar *elevation* rather than sunrise/sunset times:
elevation is always defined, so polar day and polar night fall out of a
single comparison instead of needing acos-domain special cases.
"""
import math
from datetime import UTC, datetime

# Sun's angular radius + standard atmospheric refraction — the elevation at
# which "official" sunrise/sunset occurs.
_SIN_HORIZON = math.sin(math.radians(-0.833))


def is_daylight(dt: datetime, lat: float, lon: float) -> bool:
    """Whether the sun is above the horizon at this instant and location.

    Args:
        dt: The moment to evaluate. Timezone-aware datetimes are converted
            to UTC; naive datetimes are assumed to already be UTC.
        lat: Latitude in degrees (-90 to 90).
        lon: Longitude in degrees (-180 to 180, east positive).
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)

    # Fractional year (radians): position in the orbit
    day_of_year = dt.timetuple().tm_yday
    frac_hour = dt.hour + dt.minute / 60 + dt.second / 3600
    g = 2 * math.pi / 365 * (day_of_year - 1 + (frac_hour - 12) / 24)

    # Solar declination (radians)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))

    # Equation of time (minutes): true solar time vs clock time
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g)
                       - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g)
                       - 0.040849 * math.sin(2 * g))

    # True solar time (minutes) -> hour angle (0 at solar noon). Cosine
    # periodicity makes wrapping tst into [0, 1440) unnecessary.
    tst = frac_hour * 60 + eqtime + 4 * lon
    ha = math.radians(tst / 4 - 180)

    lat_r = math.radians(lat)
    sin_elevation = (math.sin(lat_r) * math.sin(decl)
                     + math.cos(lat_r) * math.cos(decl) * math.cos(ha))
    return sin_elevation > _SIN_HORIZON
