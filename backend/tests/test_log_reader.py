"""Tests for the log reader module."""

import json
import os
import sys
import tempfile

import pytest

# Ensure path is set before imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.log_reader import (
    _matches_filters,
    _parse_icecast_line,
    _parse_json_log_line,
    _read_tail_lines,
    get_logs,
)


class TestParseJsonLogLine:
    """Test JSON log line parsing."""

    def test_valid_line(self):
        line = json.dumps({
            'timestamp': '2026-03-14T12:00:00Z',
            'level': 'INFO',
            'service': 'main',
            'module': 'audio_manager',
            'function': 'record',
            'line': 42,
            'message': 'Audio recorded',
        })
        result = _parse_json_log_line(line)
        assert result is not None
        assert result['timestamp'] == '2026-03-14T12:00:00Z'
        assert result['level'] == 'INFO'
        assert result['service'] == 'main'
        assert result['message'] == 'Audio recorded'
        assert result['module'] == 'audio_manager'
        assert result['extra'] == {}

    def test_extra_fields(self):
        line = json.dumps({
            'timestamp': '2026-03-14T12:00:00Z',
            'level': 'INFO',
            'service': 'api',
            'message': 'Request handled',
            'request_id': 'abc123',
            'duration': 0.5,
        })
        result = _parse_json_log_line(line)
        assert result['extra'] == {'request_id': 'abc123', 'duration': 0.5}

    def test_malformed_json(self):
        assert _parse_json_log_line('not json at all') is None

    def test_empty_line(self):
        assert _parse_json_log_line('') is None
        assert _parse_json_log_line('   ') is None

    def test_missing_required_fields(self):
        # Missing message
        line = json.dumps({'timestamp': '2026-03-14T12:00:00Z', 'level': 'INFO'})
        assert _parse_json_log_line(line) is None

        # Missing timestamp
        line = json.dumps({'message': 'hello', 'level': 'INFO'})
        assert _parse_json_log_line(line) is None

    def test_defaults_for_optional_fields(self):
        line = json.dumps({
            'timestamp': '2026-03-14T12:00:00Z',
            'message': 'minimal',
        })
        result = _parse_json_log_line(line)
        assert result['level'] == 'INFO'
        assert result['service'] == 'unknown'
        assert result['module'] == ''


class TestParseIcecastLine:
    """Test icecast plain-text line parsing."""

    def test_standard_line(self):
        from unittest.mock import patch
        from zoneinfo import ZoneInfo

        import core.log_reader as lr_mod
        with patch.object(lr_mod, 'get_timezone', return_value=ZoneInfo('Asia/Tokyo')):
            result = lr_mod._parse_icecast_line('[2026-03-14T12:00:00+00:00] Icecast server started on port 8888')
        assert result is not None
        assert result['service'] == 'icecast'
        assert result['level'] == 'INFO'
        assert 'Icecast server started' in result['message']
        # 12:00 UTC → 21:00 JST
        assert result['timestamp'] == '2026-03-14T21:00:00'

    def test_error_keyword(self):
        result = _parse_icecast_line('[2026-03-14T12:00:00+00:00] ERROR: PulseAudio socket not available')
        assert result['level'] == 'ERROR'

    def test_warning_keyword(self):
        result = _parse_icecast_line('[2026-03-14T12:00:00+00:00] retrying in 2s...')
        assert result['level'] == 'WARNING'

    def test_line_without_timestamp(self):
        result = _parse_icecast_line('some random output')
        assert result is not None
        assert result['message'] == 'some random output'
        assert result['timestamp'] == ''

    def test_empty_line(self):
        assert _parse_icecast_line('') is None
        assert _parse_icecast_line('   ') is None


class TestMatchesFilters:
    """Test log entry filtering."""

    @pytest.fixture
    def sample_entries(self):
        return [
            {'timestamp': '2026-03-14T12:00:00Z', 'level': 'DEBUG', 'service': 'main', 'message': 'debug msg', 'module': '', 'extra': {}},
            {'timestamp': '2026-03-14T12:01:00Z', 'level': 'INFO', 'service': 'api', 'message': 'bird detected', 'module': '', 'extra': {}},
            {'timestamp': '2026-03-14T12:02:00Z', 'level': 'WARNING', 'service': 'main', 'message': 'disk space low', 'module': '', 'extra': {}},
            {'timestamp': '2026-03-14T12:03:00Z', 'level': 'ERROR', 'service': 'birdnet', 'message': 'model failed', 'module': '', 'extra': {}},
        ]

    def _filter(self, entries, service=None, search=None):
        """Helper to apply _matches_filters over a list."""
        search_lower = search.lower() if search else None
        return [e for e in entries if _matches_filters(e, service, search_lower)]

    def test_filter_by_service(self, sample_entries):
        result = self._filter(sample_entries, service='main')
        assert len(result) == 2
        assert all(e['service'] == 'main' for e in result)

    def test_filter_by_search(self, sample_entries):
        result = self._filter(sample_entries, search='bird')
        assert len(result) == 1
        assert result[0]['message'] == 'bird detected'

    def test_search_case_insensitive(self, sample_entries):
        result = self._filter(sample_entries, search='BIRD')
        assert len(result) == 1

    def test_combined_filters(self, sample_entries):
        result = self._filter(sample_entries, service='main', search='disk')
        assert len(result) == 1
        assert result[0]['message'] == 'disk space low'

    def test_no_filters(self, sample_entries):
        result = self._filter(sample_entries)
        assert len(result) == 4


class TestReadTailLines:
    """Test reading tail lines from log files."""

    def test_reads_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            for i in range(10):
                f.write(f'line {i}\n')
            path = f.name

        try:
            lines = _read_tail_lines(path, 5)
            assert len(lines) == 5
            assert lines[-1].strip() == 'line 9'
        finally:
            os.unlink(path)

    def test_reads_rotated_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, 'test.log')
            # Write rotated file
            with open(base + '.1', 'w') as f:
                for i in range(3):
                    f.write(f'old line {i}\n')
            # Write current file
            with open(base, 'w') as f:
                for i in range(3):
                    f.write(f'new line {i}\n')

            lines = _read_tail_lines(base, 100)
            assert len(lines) == 6
            # Old lines first, then new
            assert lines[0].strip() == 'old line 0'
            assert lines[-1].strip() == 'new line 2'

    def test_missing_file_returns_empty(self):
        lines = _read_tail_lines('/nonexistent/path.log', 100)
        assert lines == []


class TestGetLogs:
    """Test the main get_logs function."""

    def test_returns_entries_from_json_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, 'main.log')
            with open(log_path, 'w') as f:
                f.write(json.dumps({
                    'timestamp': '2026-03-14T12:00:00Z',
                    'level': 'INFO',
                    'service': 'main',
                    'module': 'test',
                    'message': 'hello',
                }) + '\n')

            result = get_logs(logs_dir=tmpdir)

            assert len(result['entries']) == 1
            assert result['entries'][0]['message'] == 'hello'
            assert result['total'] == 1

    def test_returns_entries_from_icecast_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, 'icecast.log')
            with open(log_path, 'w') as f:
                f.write('[2026-03-14T12:00:00+00:00] Server started\n')

            result = get_logs(logs_dir=tmpdir)

            assert len(result['entries']) == 1
            assert result['entries'][0]['service'] == 'icecast'

    def test_merges_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # main.log
            with open(os.path.join(tmpdir, 'main.log'), 'w') as f:
                f.write(json.dumps({
                    'timestamp': '2026-03-14T12:00:00Z',
                    'level': 'INFO',
                    'service': 'main',
                    'message': 'from main',
                }) + '\n')
            # api.log
            with open(os.path.join(tmpdir, 'api.log'), 'w') as f:
                f.write(json.dumps({
                    'timestamp': '2026-03-14T12:01:00Z',
                    'level': 'INFO',
                    'service': 'api',
                    'message': 'from api',
                }) + '\n')

            result = get_logs(logs_dir=tmpdir)

            assert len(result['entries']) == 2
            # Newest first
            assert result['entries'][0]['service'] == 'api'
            assert result['entries'][1]['service'] == 'main'

    def test_missing_files_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_logs(logs_dir=tmpdir)

            assert result['entries'] == []
            assert result['total'] == 0

    def test_limit_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, 'main.log'), 'w') as f:
                for i in range(20):
                    f.write(json.dumps({
                        'timestamp': f'2026-03-14T12:{i:02d}:00Z',
                        'level': 'INFO',
                        'service': 'main',
                        'message': f'entry {i}',
                    }) + '\n')

            result = get_logs(limit=5, logs_dir=tmpdir)

            assert len(result['entries']) == 5
            assert result['total'] > 5

    def test_filter_params_passed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, 'main.log'), 'w') as f:
                f.write(json.dumps({
                    'timestamp': '2026-03-14T12:00:00Z',
                    'level': 'INFO',
                    'service': 'main',
                    'message': 'normal operation',
                }) + '\n')
                f.write(json.dumps({
                    'timestamp': '2026-03-14T12:01:00Z',
                    'level': 'ERROR',
                    'service': 'main',
                    'message': 'error here',
                }) + '\n')

            result = get_logs(search='error', logs_dir=tmpdir)

            assert len(result['entries']) == 1
            assert result['entries'][0]['message'] == 'error here'
