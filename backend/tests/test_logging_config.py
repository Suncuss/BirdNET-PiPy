"""Tests for logging formatters, handler levels, and the API request decorator."""

import json
import logging
import logging.handlers
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

import core.logging_config as log_mod
from core.logging_config import (
    HumanReadableFormatter,
    StructuredFormatter,
    _response_status,
    log_api_request,
    setup_logging,
)


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


@pytest.fixture
def clean_root_logger():
    """Snapshot and restore root logger state around setup_logging calls."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    if hasattr(root, '_birdnet_configured'):
        del root._birdnet_configured
    yield root
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    if hasattr(root, '_birdnet_configured'):
        del root._birdnet_configured


def _console_handler(logger):
    return next(h for h in logger.handlers if type(h) is logging.StreamHandler)


class TestConsoleLogLevel:

    def test_stdout_stays_verbose_by_default_with_file_handler(
            self, clean_root_logger, tmp_path, monkeypatch):
        # Default must stay verbose: in some deployments stdout is the only
        # log a user sees (HA add-on Log tab, a dev terminal). Compose opts
        # into quiet container logs via CONSOLE_LOG_LEVEL=WARNING.
        import config.settings as settings
        monkeypatch.setattr(settings, 'LOGS_DIR', str(tmp_path))
        monkeypatch.delenv('CONSOLE_LOG_LEVEL', raising=False)

        logger = setup_logging('api')

        assert _console_handler(logger).level == logging.NOTSET
        file_handler = next(
            h for h in logger.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler))
        # File handler inherits the root level, keeping full INFO detail
        assert file_handler.level == logging.NOTSET
        assert logger.level == logging.INFO

    def test_console_log_level_env_demotes_stdout(
            self, clean_root_logger, tmp_path, monkeypatch):
        import config.settings as settings
        monkeypatch.setattr(settings, 'LOGS_DIR', str(tmp_path))
        monkeypatch.setenv('CONSOLE_LOG_LEVEL', 'WARNING')

        logger = setup_logging('api')

        assert _console_handler(logger).level == logging.WARNING

    def test_stdout_stays_verbose_without_file_handler(self, clean_root_logger):
        # Unknown service → no file handler → stdout must remain the full sink
        logger = setup_logging('not-a-known-service')

        assert _console_handler(logger).level == logging.NOTSET


class TestResponseStatus:

    def test_tuple_with_status_code(self):
        assert _response_status(({'error': 'nope'}, 404)) == 404

    def test_response_object(self):
        resp = Flask(__name__).response_class(status=204)
        assert _response_status(resp) == 204

    def test_plain_body_defaults_to_200(self):
        assert _response_status({'ok': True}) == 200


class TestLogApiRequest:

    @pytest.fixture
    def app(self):
        return Flask(__name__)

    def test_logs_single_info_line_with_status_and_duration(self, app, caplog):
        @log_api_request
        def view():
            return {'ok': True}, 201

        with app.test_request_context('/api/test', method='GET'):
            with caplog.at_level(logging.INFO):
                view()

        records = [r for r in caplog.records
                   if r.getMessage().startswith('API ')]
        assert len(records) == 1
        record = records[0]
        assert record.status == 201
        assert record.method == 'GET'
        assert record.path == '/api/test'
        assert record.duration_ms >= 0

    def test_exception_logs_single_error_line(self, app, caplog):
        @log_api_request
        def view():
            raise ValueError('boom')

        with app.test_request_context('/api/test', method='POST'):
            with caplog.at_level(logging.INFO), pytest.raises(ValueError):
                view()

        assert not [r for r in caplog.records if r.levelno == logging.INFO]
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert errors[0].error == 'boom'
        assert errors[0].path == '/api/test'
