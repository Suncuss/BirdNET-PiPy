"""Tests for logging formatter timezone handling."""

import json
import logging
from unittest.mock import patch
from zoneinfo import ZoneInfo

import core.logging_config as log_mod
from core.logging_config import HumanReadableFormatter, StructuredFormatter


def _make_record(timestamp_epoch):
    """Create a minimal LogRecord with a specific created time."""
    record = logging.LogRecord(
        name='test', level=logging.INFO, pathname='', lineno=0,
        msg='test message', args=(), exc_info=None,
    )
    record.created = timestamp_epoch
    return record


class TestHumanReadableFormatter:

    def test_uses_configured_timezone(self):
        """Timestamp should reflect get_timezone(), not TZ env var."""
        formatter = HumanReadableFormatter('test', use_color=False)
        # 2025-06-16 12:00:00 UTC
        epoch = 1750075200.0

        with patch.object(log_mod, 'get_timezone',
                          return_value=ZoneInfo('Asia/Tokyo')):  # UTC+9
            output = formatter.format(_make_record(epoch))

        # 12:00 UTC = 21:00 JST
        assert '21:00:00' in output


class TestStructuredFormatter:

    def test_uses_configured_timezone(self):
        """JSON timestamp should reflect get_timezone(), not TZ env var."""
        formatter = StructuredFormatter('test')
        epoch = 1750075200.0

        with patch.object(log_mod, 'get_timezone',
                          return_value=ZoneInfo('Asia/Tokyo')):
            output = formatter.format(_make_record(epoch))

        log_obj = json.loads(output)
        # 12:00 UTC = 21:00 JST → 2025-06-16T21:00:00
        assert log_obj['timestamp'] == '2025-06-16T21:00:00'
