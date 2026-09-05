"""Tests for core.recording_schedule — recording gate, quiet hours, validation."""
from datetime import datetime

import pytest

from core.recording_schedule import (
    REASON_NO_SOURCES,
    REASON_QUIET_HOURS,
    enabled_sources,
    evaluate_recording_gate,
    evaluate_schedule,
    parse_hhmm,
    validate_quiet_hours,
    validate_schedule_settings,
)


def _settings(enabled=True, start='22:00', end='06:00', **extra):
    return {'schedule': {'quiet_hours': {
        'enabled': enabled, 'start': start, 'end': end, **extra,
    }}}


def _at(hour, minute, day=24):
    # Non-zero seconds: the window is minute-resolution and must ignore them.
    return datetime(2026, 8, day, hour, minute, 30)


class TestParseHhmm:
    @pytest.mark.parametrize('value,expected', [
        ('00:00', 0), ('06:00', 360), ('07:05', 425), ('23:59', 1439),
    ])
    def test_valid(self, value, expected):
        assert parse_hhmm(value) == expected

    @pytest.mark.parametrize('value', [
        '24:00', '7:05', '07:5', '07:60', '07:30:00', '', ' 07:30', '7h30',
        None, 730, 7.5, ['07:30'],
    ])
    def test_invalid(self, value):
        assert parse_hhmm(value) is None


class TestEvaluateSchedule:
    @pytest.mark.parametrize('settings', [
        {}, {'schedule': None}, {'schedule': {}}, {'schedule': {'quiet_hours': None}},
        {'schedule': {'quiet_hours': {'start': '22:00', 'end': '06:00'}}},  # no enabled
        {'schedule': {'quiet_hours': {'enabled': None}}},
    ])
    def test_absent_or_unset_schedule_is_off_without_error(self, settings):
        decision = evaluate_schedule(settings, _at(23, 0))
        assert decision.record is True
        assert decision.error is None

    def test_disabled_records_inside_window(self):
        decision = evaluate_schedule(_settings(enabled=False), _at(23, 0))
        assert decision.record is True
        assert decision.reason is None
        assert decision.error is None

    def test_same_day_window_is_half_open(self):
        settings = _settings(start='09:00', end='17:00')
        assert evaluate_schedule(settings, _at(8, 59)).record is True
        assert evaluate_schedule(settings, _at(9, 0)).record is False
        assert evaluate_schedule(settings, _at(16, 59)).record is False
        assert evaluate_schedule(settings, _at(17, 0)).record is True

    def test_same_day_window_resumes_at_end_today(self):
        decision = evaluate_schedule(_settings(start='09:00', end='17:00'), _at(12, 15))
        assert decision.record is False
        assert decision.reason == REASON_QUIET_HOURS
        assert decision.resumes_at == datetime(2026, 8, 24, 17, 0)

    def test_overnight_window_before_midnight(self):
        settings = _settings(start='22:00', end='06:00')
        assert evaluate_schedule(settings, _at(21, 59)).record is True
        decision = evaluate_schedule(settings, _at(22, 0))
        assert decision.record is False
        assert decision.resumes_at == datetime(2026, 8, 25, 6, 0)
        assert evaluate_schedule(settings, _at(23, 59)).record is False

    def test_overnight_window_after_midnight(self):
        settings = _settings(start='22:00', end='06:00')
        decision = evaluate_schedule(settings, _at(0, 0, day=25))
        assert decision.record is False
        assert decision.resumes_at == datetime(2026, 8, 25, 6, 0)
        assert evaluate_schedule(settings, _at(5, 59, day=25)).record is False
        assert evaluate_schedule(settings, _at(6, 0, day=25)).record is True
        assert evaluate_schedule(settings, _at(12, 0, day=25)).record is True

    def test_resumes_at_is_whole_minute(self):
        decision = evaluate_schedule(_settings(), datetime(2026, 8, 24, 23, 10, 45, 123456))
        assert decision.resumes_at == datetime(2026, 8, 25, 6, 0, 0, 0)

    def test_pausing_decision_carries_no_error(self):
        assert evaluate_schedule(_settings(), _at(23, 0)).error is None

    @pytest.mark.parametrize('start,end', [
        ('25:00', '06:00'), ('22:00', '6:00'), (None, '06:00'), ('22:00', 2200),
    ])
    def test_unusable_times_fail_open_with_error(self, start, end):
        decision = evaluate_schedule(_settings(start=start, end=end), _at(23, 0))
        assert decision.record is True
        assert decision.error

    def test_equal_times_fail_open_with_error(self):
        decision = evaluate_schedule(_settings(start='10:00', end='10:00'), _at(10, 0))
        assert decision.record is True
        assert decision.error

    @pytest.mark.parametrize('enabled', ['true', 'yes', 1, 0, [True]])
    def test_non_bool_enabled_fails_open_with_error(self, enabled):
        """A hand-edited "true" string must not enable the schedule — but it
        must be reported, not silently treated as off."""
        decision = evaluate_schedule(_settings(enabled=enabled), _at(23, 0))
        assert decision.record is True
        assert 'enabled' in decision.error

    @pytest.mark.parametrize('settings', [
        {'schedule': {'quiet_hours': '22:00-06:00'}},
        {'schedule': {'quiet_hours': ['22:00', '06:00']}},
        {'schedule': 'never'},
    ])
    def test_malformed_objects_fail_open_with_error(self, settings):
        decision = evaluate_schedule(settings, _at(23, 0))
        assert decision.record is True
        assert 'JSON object' in decision.error

    def test_unknown_keys_tolerated_when_evaluating(self):
        decision = evaluate_schedule(_settings(future_key=1), _at(23, 0))
        assert decision.record is False


class TestValidateQuietHours:
    def test_valid(self):
        assert validate_quiet_hours({'enabled': True, 'start': '22:00', 'end': '06:00'}) is None
        assert validate_quiet_hours({'enabled': False, 'start': '09:00', 'end': '17:00'}) is None

    def test_not_object(self):
        assert 'JSON object' in validate_quiet_hours('22:00-06:00')

    def test_unknown_field(self):
        error = validate_quiet_hours({'enabled': True, 'start': '22:00', 'end': '06:00', 'days': []})
        assert 'Unknown quiet_hours fields: days' == error

    def test_enabled_must_be_bool(self):
        assert 'enabled' in validate_quiet_hours({'enabled': 'yes', 'start': '22:00', 'end': '06:00'})
        assert 'enabled' in validate_quiet_hours({'start': '22:00', 'end': '06:00'})

    def test_times_must_be_hhmm(self):
        assert 'start' in validate_quiet_hours({'enabled': True, 'start': '22', 'end': '06:00'})
        assert 'end' in validate_quiet_hours({'enabled': True, 'start': '22:00', 'end': '6:00'})
        assert 'start' in validate_quiet_hours({'enabled': True, 'end': '06:00'})

    def test_times_must_differ(self):
        assert 'differ' in validate_quiet_hours({'enabled': True, 'start': '06:00', 'end': '06:00'})


class TestValidateScheduleSettings:
    def test_valid(self):
        assert validate_schedule_settings({}) is None
        assert validate_schedule_settings(_settings()['schedule']) is None

    def test_not_object(self):
        assert 'schedule must be a JSON object' == validate_schedule_settings([])

    def test_unknown_field(self):
        assert 'Unknown schedule fields: pause_until' == validate_schedule_settings({'pause_until': 'x'})

    def test_nested_error_propagates(self):
        assert 'differ' in validate_schedule_settings({'quiet_hours': {
            'enabled': True, 'start': '06:00', 'end': '06:00',
        }})


def _audio(*enabled_flags):
    return {'audio': {'sources': [
        {'id': f'source_{i}', 'type': 'rtsp', 'url': 'rtsp://x', 'enabled': flag}
        for i, flag in enumerate(enabled_flags)
    ]}}


class TestEnabledSources:
    def test_missing_flag_counts_as_enabled(self):
        # Sources saved before the toggle existed have no 'enabled' key.
        assert len(enabled_sources({'sources': [{'id': 'source_0'}]})) == 1

    def test_filters_disabled(self):
        audio = _audio(True, False)['audio']
        assert [s['id'] for s in enabled_sources(audio)] == ['source_0']

    @pytest.mark.parametrize('audio', [{}, {'sources': []}])
    def test_no_sources(self, audio):
        assert enabled_sources(audio) == []


class TestEvaluateRecordingGate:
    def test_records_with_an_active_source_and_no_schedule(self):
        decision = evaluate_recording_gate(_audio(True), _at(12, 0))
        assert decision.record is True
        assert decision.reason is None

    @pytest.mark.parametrize('settings', [_audio(False), _audio(False, False), {}])
    def test_no_active_source_pauses_without_a_resume_time(self, settings):
        decision = evaluate_recording_gate(settings, _at(12, 0))
        assert decision.record is False
        assert decision.reason == REASON_NO_SOURCES
        assert decision.resumes_at is None

    def test_one_active_source_is_enough(self):
        assert evaluate_recording_gate(_audio(False, True), _at(12, 0)).record is True

    def test_quiet_hours_still_apply_with_an_active_source(self):
        settings = {**_audio(True), **_settings()}
        decision = evaluate_recording_gate(settings, _at(23, 0))
        assert decision.reason == REASON_QUIET_HOURS
        assert decision.resumes_at is not None

    def test_no_sources_outranks_quiet_hours(self):
        settings = {**_audio(False), **_settings()}
        decision = evaluate_recording_gate(settings, _at(23, 0))
        assert decision.reason == REASON_NO_SOURCES
        assert decision.resumes_at is None

    def test_schedule_error_survives_a_no_source_pause(self):
        # Otherwise a malformed window would stop being reported (and would log
        # "valid again") for as long as every source is disabled.
        settings = {**_audio(False), **_settings(start='06:00', end='06:00')}
        decision = evaluate_recording_gate(settings, _at(23, 0))
        assert decision.reason == REASON_NO_SOURCES
        assert 'quiet hours ignored' in decision.error
