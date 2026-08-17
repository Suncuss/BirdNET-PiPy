"""
Unit tests for core/migration_audio.py helpers.
"""

from unittest.mock import patch

import core.migration_audio as migration_audio


class TestBuildSpectrogramTitleFromAudioFilename:
    """Tests for _build_spectrogram_title_from_audio_filename()"""

    def test_builds_title_from_colon_pattern_filename(self):
        """Test legacy colon-pattern filenames still work"""
        title = migration_audio._build_spectrogram_title_from_audio_filename(
            'American_Robin_85_2025-11-24-birdnet-10:30:45.mp3'
        )

        assert title == 'American Robin (0.85) - 2025-11-24T10:30:45'

    def test_builds_title_from_dash_pattern_filename(self):
        """Test new dash-pattern filenames are handled correctly"""
        title = migration_audio._build_spectrogram_title_from_audio_filename(
            'American_Robin_85_2025-11-24-birdnet-10-30-45.mp3'
        )

        # Title should use colons for human readability
        assert title == 'American Robin (0.85) - 2025-11-24T10:30:45'

    def test_formats_low_confidence_colon_pattern(self):
        """Test low confidence with colon pattern"""
        title = migration_audio._build_spectrogram_title_from_audio_filename(
            'Test_Bird_5_2025-11-24-birdnet-10:30:45.mp3'
        )

        assert title == 'Test Bird (0.05) - 2025-11-24T10:30:45'

    def test_formats_low_confidence_dash_pattern(self):
        """Test low confidence with dash pattern"""
        title = migration_audio._build_spectrogram_title_from_audio_filename(
            'Test_Bird_5_2025-11-24-birdnet-10-30-45.mp3'
        )

        # Title should use colons for human readability
        assert title == 'Test Bird (0.05) - 2025-11-24T10:30:45'

    def test_fallback_for_unexpected_format(self):
        title = migration_audio._build_spectrogram_title_from_audio_filename('Weird_Name.mp3')

        assert title == 'Weird Name'

    def test_species_with_hyphen_colon_pattern(self):
        """Test species names with hyphens work with colon pattern"""
        title = migration_audio._build_spectrogram_title_from_audio_filename(
            'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.mp3'
        )

        assert title == 'Golden-crowned Kinglet (0.57) - 2025-11-25T11:38:39'

    def test_species_with_hyphen_dash_pattern(self):
        """Test species names with hyphens work with dash pattern"""
        title = migration_audio._build_spectrogram_title_from_audio_filename(
            'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11-38-39.mp3'
        )

        # Title should use colons for human readability
        assert title == 'Golden-crowned Kinglet (0.57) - 2025-11-25T11:38:39'

    def test_localizes_species_name_when_available(self):
        with patch.object(migration_audio, 'get_spectrogram_common_name_from_english', return_value='Amsel'):
            title = migration_audio._build_spectrogram_title_from_audio_filename(
                'American_Robin_85_2025-11-24-birdnet-10-30-45.mp3'
            )

        assert title == 'Amsel (0.85) - 2025-11-24T10:30:45'


class TestTitleParserWithOwnershipSuffix:

    def test_new_era_filename_titles_hide_the_identity_suffix(self):
        """Implementation review finding 7: id+nonce must not leak into
        spectrogram titles."""
        from core.migration_audio import _build_spectrogram_title_from_audio_filename
        nonce = 'ab' * 16
        title = _build_spectrogram_title_from_audio_filename(
            f'American_Robin_85_2024-01-15-birdnet-10-30-45_42-{nonce}.mp3')
        assert nonce not in title
        assert '42-' not in title
        assert 'American Robin' in title and '10:30:45' in title

    def test_source_labeled_identity_filename_still_parses(self):
        """Re-review R5: a multi-source name keeps its structured title
        after the identity suffix strip — the label is accepted and
        ignored, matching live spectrogram titles."""
        from core.migration_audio import _build_spectrogram_title_from_audio_filename
        nonce = 'cd' * 16
        title = _build_spectrogram_title_from_audio_filename(
            f'American_Robin_85_2024-01-15-birdnet-10-30-45_Backyard_Mic_42-{nonce}.mp3')
        assert title == 'American Robin (0.85) - 2024-01-15T10:30:45'
