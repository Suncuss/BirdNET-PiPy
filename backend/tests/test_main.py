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
