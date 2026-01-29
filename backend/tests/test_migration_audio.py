"""
Unit tests for core/migration_audio.py helpers.
"""

from core.migration_audio import _build_spectrogram_title_from_audio_filename


class TestBuildSpectrogramTitleFromAudioFilename:
    """Tests for _build_spectrogram_title_from_audio_filename()"""

    def test_builds_title_from_colon_pattern_filename(self):
        """Test legacy colon-pattern filenames still work"""
        title = _build_spectrogram_title_from_audio_filename(
            'American_Robin_85_2025-11-24-birdnet-10:30:45.mp3'
        )

        assert title == 'American Robin (0.85) - 2025-11-24T10:30:45'

    def test_builds_title_from_dash_pattern_filename(self):
        """Test new dash-pattern filenames are handled correctly"""
        title = _build_spectrogram_title_from_audio_filename(
            'American_Robin_85_2025-11-24-birdnet-10-30-45.mp3'
        )

        # Title should use colons for human readability
        assert title == 'American Robin (0.85) - 2025-11-24T10:30:45'

    def test_formats_low_confidence_colon_pattern(self):
        """Test low confidence with colon pattern"""
        title = _build_spectrogram_title_from_audio_filename(
            'Test_Bird_5_2025-11-24-birdnet-10:30:45.mp3'
        )

        assert title == 'Test Bird (0.05) - 2025-11-24T10:30:45'

    def test_formats_low_confidence_dash_pattern(self):
        """Test low confidence with dash pattern"""
        title = _build_spectrogram_title_from_audio_filename(
            'Test_Bird_5_2025-11-24-birdnet-10-30-45.mp3'
        )

        # Title should use colons for human readability
        assert title == 'Test Bird (0.05) - 2025-11-24T10:30:45'

    def test_fallback_for_unexpected_format(self):
        title = _build_spectrogram_title_from_audio_filename('Weird_Name.mp3')

        assert title == 'Weird Name'

    def test_species_with_hyphen_colon_pattern(self):
        """Test species names with hyphens work with colon pattern"""
        title = _build_spectrogram_title_from_audio_filename(
            'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11:38:39.mp3'
        )

        assert title == 'Golden-crowned Kinglet (0.57) - 2025-11-25T11:38:39'

    def test_species_with_hyphen_dash_pattern(self):
        """Test species names with hyphens work with dash pattern"""
        title = _build_spectrogram_title_from_audio_filename(
            'Golden-crowned_Kinglet_57_2025-11-25-birdnet-11-38-39.mp3'
        )

        # Title should use colons for human readability
        assert title == 'Golden-crowned Kinglet (0.57) - 2025-11-25T11:38:39'
