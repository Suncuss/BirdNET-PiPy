"""Tests for the timezone service module."""

import os
import pytest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from core.timezone_service import get_timezone, get_timezone_str


class TestTimezoneService:
    """Test timezone service functionality."""

    def test_returns_tz_from_env_var(self):
        """Test that timezone is returned from TZ env var."""
        with patch.dict(os.environ, {'TZ': 'Europe/Berlin'}):
            assert get_timezone_str() == "Europe/Berlin"

    def test_returns_utc_when_tz_not_set(self):
        """Test that UTC is returned when TZ env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop('TZ', None)
            assert get_timezone_str() == "UTC"

    def test_returns_utc_when_tz_empty(self):
        """Test that UTC is returned when TZ env var is empty."""
        with patch.dict(os.environ, {'TZ': ''}):
            assert get_timezone_str() == "UTC"

    def test_get_timezone_returns_zoneinfo(self):
        """Test that get_timezone returns a ZoneInfo object."""
        with patch.dict(os.environ, {'TZ': 'America/New_York'}):
            tz = get_timezone()
            assert tz == ZoneInfo("America/New_York")

    def test_get_timezone_returns_utc_for_invalid_tz(self):
        """Test that invalid timezone triggers fallback to UTC."""
        with patch.dict(os.environ, {'TZ': 'Invalid/Timezone'}):
            tz = get_timezone()
            assert tz == ZoneInfo("UTC")
