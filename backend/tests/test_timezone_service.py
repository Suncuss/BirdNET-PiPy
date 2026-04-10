"""Tests for the timezone service module."""

import logging
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

import core.timezone_service as tz_mod
from core.timezone_service import get_timezone, get_timezone_str, local_now


def _make_settings(timezone=None):
    """Build a minimal settings dict with the given timezone."""
    return {'location': {'timezone': timezone}}


@pytest.fixture(autouse=True)
def _isolate_tz_cache():
    """Reset timezone cache and mock file stat for every test.

    Without this, a real settings file (or its absence) in the test
    container would leak state between tests.
    """
    tz_mod._tz_mtime = None
    tz_mod._tz_str = 'UTC'
    tz_mod._tz_obj = tz_mod._UTC
    tz_mod._last_check = 0.0
    yield
    tz_mod._tz_mtime = None
    tz_mod._tz_str = 'UTC'
    tz_mod._tz_obj = tz_mod._UTC
    tz_mod._last_check = 0.0


class TestGetTimezoneStr:

    def test_reads_from_config(self):
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings('Europe/Berlin')):
            assert get_timezone_str() == 'Europe/Berlin'

    def test_returns_utc_when_timezone_is_none(self):
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings(None)):
            assert get_timezone_str() == 'UTC'

    def test_returns_utc_when_timezone_is_empty(self):
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings('')):
            assert get_timezone_str() == 'UTC'

    def test_returns_utc_when_location_missing(self):
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings', return_value={}):
            assert get_timezone_str() == 'UTC'

    def test_returns_cached_when_file_missing(self):
        """If settings file doesn't exist, return cached default."""
        with patch.object(tz_mod, '_safe_mtime', return_value=None):
            assert get_timezone_str() == 'UTC'


class TestGetTimezone:

    def test_returns_zoneinfo(self):
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings('America/New_York')):
            assert get_timezone() == ZoneInfo('America/New_York')

    def test_returns_utc_for_invalid_timezone(self):
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings('Invalid/Timezone')):
            assert get_timezone() == ZoneInfo('UTC')

    def test_does_not_log_on_invalid_timezone(self, caplog):
        """Invalid timezone must not log — prevents recursion from formatters."""
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings('Invalid/Timezone')):
            with caplog.at_level(logging.DEBUG, logger='core.timezone_service'):
                get_timezone()
            assert caplog.records == []


class TestLocalNow:

    def test_returns_naive_datetime(self):
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings('UTC')):
            result = local_now()
            assert isinstance(result, datetime)
            assert result.tzinfo is None

    def test_respects_configured_timezone(self):
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings('Pacific/Auckland')):
            nz_now = local_now()

        # Reset and get UTC time
        tz_mod._tz_mtime = None
        tz_mod._tz_str = 'UTC'
        tz_mod._tz_obj = tz_mod._UTC
        tz_mod._last_check = 0.0

        with patch.object(tz_mod, '_safe_mtime', return_value=2000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings('UTC')):
            utc_now = local_now()

        # Auckland is UTC+12 or UTC+13 (DST).
        diff_hours = abs((nz_now - utc_now).total_seconds()) / 3600
        assert diff_hours >= 11


class TestMtimeCache:

    def test_does_not_reload_when_mtime_unchanged(self):
        """get_runtime_settings should only be called once for same mtime."""
        with patch.object(tz_mod, '_safe_mtime', return_value=1000.0), \
             patch.object(tz_mod, 'get_runtime_settings',
                          return_value=_make_settings('America/New_York')) as mock_get:
            get_timezone_str()
            get_timezone_str()
            assert mock_get.call_count == 1

    def test_reloads_when_mtime_changes(self):
        from unittest.mock import MagicMock
        mock_mtime = MagicMock(return_value=1000.0)
        mock_settings = MagicMock(return_value=_make_settings('America/New_York'))

        with patch.object(tz_mod, '_safe_mtime', mock_mtime), \
             patch.object(tz_mod, 'get_runtime_settings', mock_settings):
            assert get_timezone_str() == 'America/New_York'

            mock_mtime.return_value = 2000.0
            mock_settings.return_value = _make_settings('Europe/London')
            tz_mod._last_check = 0.0  # expire TTL so _refresh_cache re-checks
            assert get_timezone_str() == 'Europe/London'
