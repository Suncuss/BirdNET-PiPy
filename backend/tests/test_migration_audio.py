"""
Unit tests for core/migration_audio.py helpers.
"""

from core.migration_audio import _build_spectrogram_title_from_audio_filename


class TestBuildSpectrogramTitleFromAudioFilename:
    """Tests for _build_spectrogram_title_from_audio_filename()"""

    def test_builds_title_from_standard_filename(self):
        title = _build_spectrogram_title_from_audio_filename(
            'American_Robin_85_2025-11-24-birdnet-10:30:45.mp3'
        )

        assert title == 'American Robin (0.85) - 2025-11-24T10:30:45'

    def test_formats_low_confidence(self):
        title = _build_spectrogram_title_from_audio_filename(
            'Test_Bird_5_2025-11-24-birdnet-10:30:45.mp3'
        )

        assert title == 'Test Bird (0.05) - 2025-11-24T10:30:45'

    def test_fallback_for_unexpected_format(self):
        title = _build_spectrogram_title_from_audio_filename('Weird_Name.mp3')

        assert title == 'Weird Name'
