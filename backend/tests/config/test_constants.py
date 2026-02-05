"""Tests for configuration constants."""
from config.constants import (
    DEFAULT_RECORDING_MODE,
    OVERLAP_OPTIONS,
    RECORDING_LENGTH_OPTIONS,
    RECORDING_MODES,
    UPDATE_CHANNELS,
    VALID_RECORDING_MODES,
    RecordingMode,
)


class TestRecordingModes:
    def test_valid_modes_matches_dict_keys(self):
        assert set(VALID_RECORDING_MODES) == set(RECORDING_MODES.keys())

    def test_default_mode_is_valid(self):
        assert DEFAULT_RECORDING_MODE in VALID_RECORDING_MODES

    def test_recording_mode_class_values_in_dict(self):
        assert RecordingMode.PULSEAUDIO in RECORDING_MODES
        assert RecordingMode.HTTP_STREAM in RECORDING_MODES
        assert RecordingMode.RTSP in RECORDING_MODES

    def test_all_modes_have_labels(self):
        for mode in VALID_RECORDING_MODES:
            assert mode in RECORDING_MODES
            assert isinstance(RECORDING_MODES[mode], str)
            assert len(RECORDING_MODES[mode]) > 0


class TestRecordingLengths:
    def test_all_positive(self):
        assert all(length > 0 for length in RECORDING_LENGTH_OPTIONS)

    def test_sorted_ascending(self):
        assert list(RECORDING_LENGTH_OPTIONS) == sorted(RECORDING_LENGTH_OPTIONS)

    def test_contains_expected_values(self):
        assert 9 in RECORDING_LENGTH_OPTIONS
        assert 12 in RECORDING_LENGTH_OPTIONS
        assert 15 in RECORDING_LENGTH_OPTIONS


class TestOverlapOptions:
    def test_all_non_negative(self):
        assert all(overlap >= 0 for overlap in OVERLAP_OPTIONS)

    def test_first_option_is_zero(self):
        assert OVERLAP_OPTIONS[0] == 0.0

    def test_contains_expected_values(self):
        assert 0.0 in OVERLAP_OPTIONS
        assert 0.5 in OVERLAP_OPTIONS
        assert 1.0 in OVERLAP_OPTIONS
        assert 1.5 in OVERLAP_OPTIONS
        assert 2.0 in OVERLAP_OPTIONS
        assert 2.5 in OVERLAP_OPTIONS


class TestUpdateChannels:
    def test_contains_release(self):
        assert 'release' in UPDATE_CHANNELS

    def test_contains_latest(self):
        assert 'latest' in UPDATE_CHANNELS

    def test_is_tuple(self):
        assert isinstance(UPDATE_CHANNELS, tuple)
