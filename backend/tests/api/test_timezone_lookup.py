"""Tests for offline timezone lookup using tzfpy."""

from unittest.mock import patch


class TestOfflineTimezoneLookup:
    """Test the get_timezone_for_location function using tzfpy."""

    def test_new_york_coordinates(self):
        """Test timezone lookup for New York City."""
        from core.routes.settings import get_timezone_for_location
        result = get_timezone_for_location(40.7128, -74.0060)
        assert result == "America/New_York"

    def test_london_coordinates(self):
        """Test timezone lookup for London."""
        from core.routes.settings import get_timezone_for_location
        result = get_timezone_for_location(51.5074, -0.1278)
        assert result == "Europe/London"

    def test_tokyo_coordinates(self):
        """Test timezone lookup for Tokyo."""
        from core.routes.settings import get_timezone_for_location
        result = get_timezone_for_location(35.6762, 139.6503)
        assert result == "Asia/Tokyo"

    def test_sydney_coordinates(self):
        """Test timezone lookup for Sydney."""
        from core.routes.settings import get_timezone_for_location
        result = get_timezone_for_location(-33.8688, 151.2093)
        assert result == "Australia/Sydney"

    def test_los_angeles_coordinates(self):
        """Test timezone lookup for Los Angeles."""
        from core.routes.settings import get_timezone_for_location
        result = get_timezone_for_location(34.0522, -118.2437)
        assert result == "America/Los_Angeles"

    def test_returns_valid_iana_string_or_none(self):
        """Test that result is a valid IANA timezone string or None."""
        from core.routes.settings import get_timezone_for_location
        # Ocean coordinates - resolves to an Etc/GMT± ocean zone
        result = get_timezone_for_location(30.0, -40.0)
        # Either None or a valid IANA timezone string
        assert result is None or (isinstance(result, str) and '/' in result)

    def test_handles_exception_gracefully(self):
        """Test that exceptions are handled and return None."""
        with patch('tzfpy.get_tz', side_effect=Exception("Test error")):
            from core.routes.settings import get_timezone_for_location
            result = get_timezone_for_location(40.7128, -74.0060)
            assert result is None

    def test_logs_warning_for_no_timezone(self):
        """Test that a warning is logged when no timezone is found."""
        with patch('tzfpy.get_tz', return_value=''), \
             patch('core.routes.settings.logger') as mock_logger:
            from core.routes.settings import get_timezone_for_location
            result = get_timezone_for_location(30.0, -40.0)

            assert result is None
            mock_logger.warning.assert_called()

    def test_out_of_range_returns_none(self):
        """Nonsense coordinates must not raise; the caller expects None."""
        from core.routes.settings import get_timezone_for_location
        assert get_timezone_for_location(91.0, 0.0) is None
        assert get_timezone_for_location(-95.0, 400.0) is None


class TestBorderGapFallback:
    """tzfpy's simplified polygons leave rare hairline gaps at zone borders;
    the neighbor-nudge fallback must recover points sitting in one."""

    def test_polygon_gap_resolves_via_nudge(self):
        """(54.0, -90.0) sits in a known data gap in tzfpy 1.3.x (rural NW
        Ontario, surrounded by America/Winnipeg on all sides). A bare get_tz
        returns nothing there; the nudge must recover the surrounding zone.
        Still passes if a future tzfpy data update closes the gap."""
        from core.routes.settings import get_timezone_for_location
        result = get_timezone_for_location(54.0, -90.0)
        assert result == "America/Winnipeg"

    def test_exact_antimeridian_resolves_via_nudge(self):
        """Exactly ±180° longitude returns nothing from tzfpy; the nudge must
        land in one of the adjacent ocean zones instead of failing."""
        from core.routes.settings import get_timezone_for_location
        result = get_timezone_for_location(0.0, 180.0)
        assert result is not None and result.startswith("Etc/GMT")


class TestTzfpyLazyImport:
    """The tzfpy import must stay out of the API's startup path."""

    def test_importing_api_does_not_import_tzfpy(self):
        """core.api pulls tzfpy only when a location lookup actually runs,
        never at import."""
        import subprocess
        import sys

        code = (
            "import sys; import core.routes.settings; "
            "sys.exit(1 if 'tzfpy' in sys.modules else 0)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
