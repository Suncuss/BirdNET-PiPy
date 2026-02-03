"""Tests for offline timezone lookup using timezonefinder."""

import pytest
from unittest.mock import patch, MagicMock


class TestOfflineTimezoneLookup:
    """Test the get_timezone_for_location function using timezonefinder."""

    def test_new_york_coordinates(self):
        """Test timezone lookup for New York City."""
        from core.api import get_timezone_for_location
        result = get_timezone_for_location(40.7128, -74.0060)
        assert result == "America/New_York"

    def test_london_coordinates(self):
        """Test timezone lookup for London."""
        from core.api import get_timezone_for_location
        result = get_timezone_for_location(51.5074, -0.1278)
        assert result == "Europe/London"

    def test_tokyo_coordinates(self):
        """Test timezone lookup for Tokyo."""
        from core.api import get_timezone_for_location
        result = get_timezone_for_location(35.6762, 139.6503)
        assert result == "Asia/Tokyo"

    def test_sydney_coordinates(self):
        """Test timezone lookup for Sydney."""
        from core.api import get_timezone_for_location
        result = get_timezone_for_location(-33.8688, 151.2093)
        assert result == "Australia/Sydney"

    def test_los_angeles_coordinates(self):
        """Test timezone lookup for Los Angeles."""
        from core.api import get_timezone_for_location
        result = get_timezone_for_location(34.0522, -118.2437)
        assert result == "America/Los_Angeles"

    def test_returns_valid_iana_string_or_none(self):
        """Test that result is a valid IANA timezone string or None."""
        from core.api import get_timezone_for_location
        # Ocean coordinates - may return None
        result = get_timezone_for_location(30.0, -40.0)
        # Either None or a valid IANA timezone string
        assert result is None or (isinstance(result, str) and '/' in result)

    def test_handles_exception_gracefully(self):
        """Test that exceptions are handled and return None."""
        with patch('core.api._get_timezone_finder') as mock_finder:
            mock_tf = MagicMock()
            mock_tf.timezone_at.side_effect = Exception("Test error")
            mock_finder.return_value = mock_tf

            from core.api import get_timezone_for_location
            result = get_timezone_for_location(40.7128, -74.0060)
            assert result is None

    def test_logs_warning_for_no_timezone(self):
        """Test that a warning is logged when no timezone is found."""
        with patch('core.api._get_timezone_finder') as mock_finder, \
             patch('core.api.logger') as mock_logger:
            mock_tf = MagicMock()
            mock_tf.timezone_at.return_value = None
            mock_finder.return_value = mock_tf

            from core.api import get_timezone_for_location
            result = get_timezone_for_location(30.0, -40.0)

            assert result is None
            mock_logger.warning.assert_called()


class TestTimezoneFinderSingleton:
    """Test the TimezoneFinder singleton pattern."""

    def test_singleton_reuses_instance(self):
        """Test that _get_timezone_finder returns same instance."""
        from core.api import _get_timezone_finder, _timezone_finder

        # First call creates instance
        tf1 = _get_timezone_finder()

        # Second call should return same instance
        tf2 = _get_timezone_finder()

        assert tf1 is tf2

    def test_thread_safe_singleton(self):
        """Test that singleton is thread-safe."""
        import threading

        instances = []
        errors = []

        def get_finder():
            try:
                from core.api import _get_timezone_finder
                tf = _get_timezone_finder()
                instances.append(tf)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_finder) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(instances) == 10
        # All should be the same instance
        assert all(i is instances[0] for i in instances)
