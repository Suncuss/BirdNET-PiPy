"""Tests for core.solar — NOAA solar-position day/night classification.

All reference cases keep a wide margin (≥25 minutes) from the actual horizon
crossing, so the ~1–2 minute accuracy of the NOAA low-accuracy formula can
never flip an assertion. Cross-checked against the NOAA Solar Calculator
(gml.noaa.gov/grad/solcalc).
"""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


class TestEquator:
    def test_noon_is_day(self):
        from core.solar import is_daylight
        assert is_daylight(_utc(2026, 3, 20, 12, 0), 0.0, 0.0) is True

    def test_midnight_is_night(self):
        from core.solar import is_daylight
        assert is_daylight(_utc(2026, 3, 20, 0, 0), 0.0, 0.0) is False

    def test_before_equinox_sunrise_is_night(self):
        # Equinox sunrise at (0, 0) is ~06:04 UTC (equation of time shifts
        # solar noon to ~12:07). 05:15 leaves a ~49 min margin.
        from core.solar import is_daylight
        assert is_daylight(_utc(2026, 3, 20, 5, 15), 0.0, 0.0) is False

    def test_after_equinox_sunrise_is_day(self):
        # ~41 min after the ~06:04 UTC sunrise.
        from core.solar import is_daylight
        assert is_daylight(_utc(2026, 3, 20, 6, 45), 0.0, 0.0) is True


class TestPolar:
    """Polar day/night must fall out of the elevation comparison with no
    special-casing — there is no sunrise/sunset to compute at all."""

    SVALBARD = (78.0, 15.0)

    def test_polar_night_noon_is_night(self):
        from core.solar import is_daylight
        assert is_daylight(_utc(2026, 12, 21, 12, 0), *self.SVALBARD) is False

    def test_midnight_sun_is_day(self):
        from core.solar import is_daylight
        assert is_daylight(_utc(2026, 6, 21, 0, 0), *self.SVALBARD) is True


class TestSeasons:
    """Same clock time, opposite answers by season — catches declination sign
    errors that equator/polar extremes can't."""

    ITHACA = (42.47, -76.45)  # the default station coordinates

    def test_winter_late_afternoon_is_night(self):
        # Dec 21, 17:30 EST (22:30 UTC): Ithaca sunset ~16:35 EST.
        from core.solar import is_daylight
        assert is_daylight(_utc(2026, 12, 21, 22, 30), *self.ITHACA) is False

    def test_summer_late_afternoon_is_day(self):
        # Jul 25, 17:30 EDT (21:30 UTC): Ithaca sunset ~20:30 EDT.
        from core.solar import is_daylight
        assert is_daylight(_utc(2026, 7, 25, 21, 30), *self.ITHACA) is True

    def test_discussion_64_repro_evening_detection_is_night(self):
        # The reported case: a clear-sky detection at 21:42 local in late July
        # showed a sun icon. 21:42 EDT = 01:42 UTC next day; sunset ~20:30 EDT.
        from core.solar import is_daylight
        assert is_daylight(_utc(2026, 7, 26, 1, 42), *self.ITHACA) is False


class TestTimezoneHandling:
    def test_aware_non_utc_datetime_is_converted(self):
        # 21:42 America/New_York in July is night at Ithaca. If the zone were
        # ignored (21:42 read as UTC = 17:42 EDT), the sun would still be up —
        # so this asserts the conversion actually happens.
        from core.solar import is_daylight
        dt = datetime(2026, 7, 25, 21, 42, tzinfo=ZoneInfo('America/New_York'))
        assert is_daylight(dt, 42.47, -76.45) is False

    def test_naive_datetime_treated_as_utc(self):
        from core.solar import is_daylight
        assert is_daylight(datetime(2026, 3, 20, 12, 0), 0.0, 0.0) is True
