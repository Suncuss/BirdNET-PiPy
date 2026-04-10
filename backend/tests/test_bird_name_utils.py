"""Tests for localized bird-name helpers."""

import importlib

from model_service.label_utils import clear_species_cache


class TestSpectrogramBirdNames:
    """Tests for spectrogram-safe bird name helpers.

    These tests use the real species_table.csv which contains actual data.
    'Turdus migratorius' (American Robin) has German translation 'Wanderdrossel'.
    """

    def test_get_spectrogram_common_name_uses_localized_name_for_supported_scripts(self):
        bird_name_utils = importlib.import_module('core.bird_name_utils')

        clear_species_cache()
        try:
            display_name = bird_name_utils.get_spectrogram_common_name(
                'Turdus migratorius',
                'American Robin',
                settings={
                    'model': {'type': 'birdnet'},
                    'display': {'bird_name_language': 'de'},
                },
            )
            assert display_name == 'Wanderdrossel'
        finally:
            clear_species_cache()

    def test_get_spectrogram_common_name_falls_back_to_english_for_unsupported_scripts(self):
        bird_name_utils = importlib.import_module('core.bird_name_utils')

        clear_species_cache()
        try:
            display_name = bird_name_utils.get_spectrogram_common_name(
                'Turdus migratorius',
                'American Robin',
                settings={
                    'model': {'type': 'birdnet'},
                    'display': {'bird_name_language': 'ja'},
                },
            )
            english_name = bird_name_utils.get_spectrogram_common_name_from_english(
                'American Robin',
                settings={
                    'model': {'type': 'birdnet'},
                    'display': {'bird_name_language': 'ja'},
                },
            )

            assert display_name == 'American Robin'
            assert english_name == 'American Robin'
        finally:
            clear_species_cache()
