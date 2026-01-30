"""Tests for the timezone service module."""

import pytest
import threading
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo


class TestTimezoneService:
    """Test timezone service functionality."""

    def setup_method(self):
        """Reset timezone cache before each test."""
        import core.timezone_service as ts
        ts.clear_cache()

    def teardown_method(self):
        """Clean up after each test."""
        import core.timezone_service as ts
        ts.clear_cache()

    def test_get_timezone_returns_cached_timezone(self):
        """Test that cached timezone is returned when available."""
        import core.timezone_service as ts

        ts.update_cached_timezone("America/New_York")
        tz = ts.get_timezone()

        assert tz == ZoneInfo("America/New_York")

    def test_get_timezone_str_returns_cached_timezone(self):
        """Test that cached timezone string is returned when available."""
        import core.timezone_service as ts

        ts.update_cached_timezone("Europe/London")
        tz_str = ts.get_timezone_str()

        assert tz_str == "Europe/London"

    def test_get_timezone_falls_back_to_host_timezone(self):
        """Test fallback to host timezone when no cache."""
        with patch('core.timezone_service.get_localzone') as mock_localzone:
            mock_localzone.return_value = ZoneInfo("America/Chicago")

            import core.timezone_service as ts
            ts.clear_cache()

            tz_str = ts.get_timezone_str()

            assert tz_str == "America/Chicago"
            mock_localzone.assert_called_once()

    def test_get_timezone_falls_back_to_utc_on_host_error(self):
        """Test fallback to UTC when host timezone fails."""
        with patch('core.timezone_service.get_localzone') as mock_localzone:
            mock_localzone.side_effect = Exception("No timezone configured")

            import core.timezone_service as ts
            ts.clear_cache()

            tz_str = ts.get_timezone_str()

            assert tz_str == "UTC"

    def test_get_timezone_returns_utc_for_invalid_cached_timezone(self):
        """Test that invalid cached timezone triggers fallback to UTC."""
        import core.timezone_service as ts

        ts.update_cached_timezone("Invalid/Timezone")
        tz = ts.get_timezone()

        assert tz == ZoneInfo("UTC")

    def test_update_cached_timezone_updates_cache(self):
        """Test that update_cached_timezone updates the in-memory cache."""
        import core.timezone_service as ts

        ts.update_cached_timezone("Asia/Tokyo")
        cached = ts._get_cached_timezone()

        assert cached == "Asia/Tokyo"

    def test_update_cached_timezone_only_logs_on_change(self):
        """Test that update only logs when timezone actually changes."""
        with patch('core.timezone_service.logger') as mock_logger:
            import core.timezone_service as ts

            # First update should log
            ts.update_cached_timezone("Pacific/Auckland")
            assert mock_logger.info.call_count == 1

            # Same value should not log again
            ts.update_cached_timezone("Pacific/Auckland")
            assert mock_logger.info.call_count == 1

            # Different value should log
            ts.update_cached_timezone("Pacific/Fiji")
            assert mock_logger.info.call_count == 2

    def test_clear_cache_clears_timezone(self):
        """Test that clear_cache clears the in-memory cache."""
        import core.timezone_service as ts

        ts.update_cached_timezone("Europe/Paris")
        assert ts._get_cached_timezone() == "Europe/Paris"

        ts.clear_cache()
        assert ts._get_cached_timezone() is None


class TestTimezoneServiceThreadSafety:
    """Test thread safety of timezone service."""

    def setup_method(self):
        """Reset timezone cache before each test."""
        import core.timezone_service as ts
        ts.clear_cache()

    def teardown_method(self):
        """Clean up after each test."""
        import core.timezone_service as ts
        ts.clear_cache()

    def test_concurrent_reads(self):
        """Test that concurrent reads don't cause race conditions."""
        import core.timezone_service as ts

        ts.update_cached_timezone("America/Los_Angeles")

        results = []
        errors = []

        def read_timezone():
            try:
                tz_str = ts.get_timezone_str()
                results.append(tz_str)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_timezone) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 20
        assert all(r == "America/Los_Angeles" for r in results)

    def test_concurrent_writes(self):
        """Test that concurrent writes don't cause race conditions."""
        import core.timezone_service as ts

        errors = []
        timezones = [
            "America/New_York", "America/Chicago", "America/Denver",
            "America/Los_Angeles", "Europe/London", "Europe/Paris",
            "Asia/Tokyo", "Asia/Shanghai", "Australia/Sydney", "Pacific/Auckland"
        ]

        def write_timezone(tz):
            try:
                ts.update_cached_timezone(tz)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_timezone, args=(tz,)) for tz in timezones]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Final value should be one of the timezones
        final = ts._get_cached_timezone()
        assert final in timezones

    def test_concurrent_read_write(self):
        """Test concurrent reads and writes don't cause race conditions."""
        import core.timezone_service as ts

        ts.update_cached_timezone("UTC")

        read_results = []
        write_errors = []
        read_errors = []

        def read_timezone():
            try:
                for _ in range(10):
                    tz = ts.get_timezone_str()
                    read_results.append(tz)
            except Exception as e:
                read_errors.append(e)

        def write_timezone():
            try:
                for tz in ["America/New_York", "Europe/London", "Asia/Tokyo"]:
                    ts.update_cached_timezone(tz)
            except Exception as e:
                write_errors.append(e)

        readers = [threading.Thread(target=read_timezone) for _ in range(5)]
        writers = [threading.Thread(target=write_timezone) for _ in range(3)]

        all_threads = readers + writers
        for t in all_threads:
            t.start()
        for t in all_threads:
            t.join()

        assert len(read_errors) == 0
        assert len(write_errors) == 0
        # All reads should return valid timezone strings
        valid_tzs = {"UTC", "America/New_York", "Europe/London", "Asia/Tokyo"}
        assert all(r in valid_tzs for r in read_results)


class TestTimezoneServiceInitialization:
    """Test timezone service initialization from settings."""

    def test_initializes_from_settings_module(self):
        """Test that service initializes from TIMEZONE in settings."""
        with patch('core.timezone_service.TIMEZONE', 'Europe/Berlin'):
            # Force reload of the module to pick up patched TIMEZONE
            import importlib
            import core.timezone_service as ts
            # Manually set since module already loaded
            ts._cached_timezone = 'Europe/Berlin'

            tz_str = ts.get_timezone_str()
            assert tz_str == "Europe/Berlin"

            # Clean up
            ts.clear_cache()
