"""Focused unit tests for core.main helpers."""

import os
import tempfile
from unittest.mock import patch


class TestCreateDetectionSpectrogram:
    """Tests for spectrogram title generation."""

    def test_create_detection_spectrogram_uses_spectrogram_safe_display_name(self):
        detection = {
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.95,
            'timestamp': '2025-11-26T10:30:00',
            'chunk_index': 1,
            'spectrogram_file_name': 'American_Robin_95_test.webp',
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch('core.main.SPECTROGRAM_DIR', tmpdir), \
             patch('core.main._get_analysis_chunk_length', return_value=3), \
             patch('core.main.get_spectrogram_common_name', return_value='American Robin') as mock_name, \
             patch('core.main.generate_spectrogram') as mock_generate:
            from core.main import create_detection_spectrogram

            result = create_detection_spectrogram(detection, '/tmp/input.wav')

        mock_name.assert_called_once_with('Turdus migratorius', 'American Robin')
        mock_generate.assert_called_once()
        assert mock_generate.call_args.args[2] == 'American Robin (0.95) - 2025-11-26T10:30:00'
        assert result == os.path.join(tmpdir, 'American_Robin_95_test.webp')


class TestExtractDetectionAudio:
    """Tests for clip extraction and the playback-normalize setting."""

    def _run(self, settings):
        detection = {
            'chunk_index': 1,
            'total_chunks': 3,
            'bird_song_file_name': 'American_Robin_90_test.wav',
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch('core.main.EXTRACTED_AUDIO_DIR', tmpdir), \
             patch('core.main._get_analysis_chunk_length', return_value=3), \
             patch('core.main.get_runtime_settings', return_value=settings), \
             patch('core.main.extract_audio_segment') as mock_extract:
            from core.main import extract_detection_audio
            result = extract_detection_audio(detection, '/tmp/input.wav')
        return mock_extract, result

    def test_passes_normalize_true_when_setting_enabled(self):
        mock_extract, _ = self._run({'playback': {'normalize': True}})
        assert mock_extract.call_args.kwargs.get('normalize') is True

    def test_defaults_to_no_normalize_when_setting_absent(self):
        mock_extract, _ = self._run({})
        assert mock_extract.call_args.kwargs.get('normalize') is False

    def test_extracts_from_source_straight_to_mp3(self):
        """The clip is cut from the source recording directly to MP3 — no
        intermediate WAV is written to EXTRACTED_AUDIO_DIR."""
        mock_extract, result = self._run({})

        mock_extract.assert_called_once()
        args = mock_extract.call_args.args
        assert args[0] == '/tmp/input.wav'
        assert args[1].endswith('American_Robin_90_test.mp3')
        # chunk_index=1 of 3, chunk length 3s -> context window is chunks 0-2
        assert args[2] == 0
        assert args[3] == 9
        assert result == args[1]
