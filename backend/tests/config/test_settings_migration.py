"""Tests for one-time settings migrations in config.settings."""

import json
import os
import tempfile
from unittest.mock import patch

import config.settings as settings_module
from config.settings import DEFAULT_SETTINGS, load_user_settings


def _write_settings_file(path, data):
    with open(path, 'w') as f:
        json.dump(data, f)


class TestSpectrogramFloorMigration:
    """A persisted stale min_dbfs must be reset so the new default reaches users.

    min_dbfs has no UI, so the frontend re-saves whatever it loaded; the shallow
    per-section merge in load_user_settings would otherwise freeze an old default
    forever. The migration resets superseded values and persists the fix.
    """

    def _load_with_file(self, user_data):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, 'user_settings.json')
            _write_settings_file(path, user_data)
            with patch.object(settings_module, 'USER_SETTINGS_PATH', path):
                result = load_user_settings()
            with open(path) as f:
                on_disk = json.load(f)
        return result, on_disk

    def test_resets_legacy_120_floor_to_current_default(self):
        current = DEFAULT_SETTINGS['spectrogram']['min_dbfs']
        result, on_disk = self._load_with_file(
            {'spectrogram': {'min_dbfs': -120}, 'detection': {'cutoff': 0.4}}
        )
        assert result['spectrogram']['min_dbfs'] == current
        # Persisted so it runs once and the frontend gets the corrected value.
        assert on_disk['spectrogram']['min_dbfs'] == current
        # The user's other saved data is preserved...
        assert on_disk['detection']['cutoff'] == 0.4
        # ...and the write stays minimal (no full default set frozen in).
        assert 'storage' not in on_disk

    def test_resets_intermediate_90_floor(self):
        current = DEFAULT_SETTINGS['spectrogram']['min_dbfs']
        result, on_disk = self._load_with_file({'spectrogram': {'min_dbfs': -90}})
        assert result['spectrogram']['min_dbfs'] == current
        assert on_disk['spectrogram']['min_dbfs'] == current

    def test_leaves_current_default_untouched(self):
        current = DEFAULT_SETTINGS['spectrogram']['min_dbfs']
        original = {'spectrogram': {'min_dbfs': current}, 'detection': {'cutoff': 0.4}}
        result, on_disk = self._load_with_file(original)
        assert result['spectrogram']['min_dbfs'] == current
        # No migration write — the file is left exactly as it was.
        assert on_disk == original

    def test_missing_spectrogram_section_is_noop(self):
        current = DEFAULT_SETTINGS['spectrogram']['min_dbfs']
        result, on_disk = self._load_with_file({'detection': {'cutoff': 0.4}})
        # Falls back to the current default in memory; nothing is persisted/frozen.
        assert result['spectrogram']['min_dbfs'] == current
        assert 'spectrogram' not in on_disk
