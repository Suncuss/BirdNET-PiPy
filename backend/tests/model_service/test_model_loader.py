"""Tests for BirdNetModel eBird code functionality."""

import threading
from collections import OrderedDict

import pytest


class TestBirdNetModelEbirdCodes:
    """Test eBird code lookup via species table in BirdNetModel."""

    @pytest.fixture
    def mock_birdnet_model(self):
        """Create a BirdNetModel with mocked model paths."""
        from model_service.birdnet_v2_model import BirdNetModel

        loader = BirdNetModel.__new__(BirdNetModel)
        loader.model_path = "/fake/model.tflite"
        loader.meta_model_path = "/fake/meta_model.tflite"
        loader.labels_path = "/fake/labels.txt"
        loader.ebird_codes_path = None
        loader._model = None
        loader._meta_model = None
        loader.input_layer_index = None
        loader.output_layer_index = None
        loader.meta_input_layer_index = None
        loader.meta_output_layer_index = None
        loader._labels = None
        loader._meta_probs_cache = OrderedDict()
        loader._meta_probs_cache_max_size = 128
        loader._inference_lock = threading.Lock()
        return loader

    def test_get_ebird_code_found(self, mock_birdnet_model):
        """Test lookup returns correct eBird code for known species."""
        assert mock_birdnet_model.get_ebird_code("Turdus migratorius") == "amerob"
        assert mock_birdnet_model.get_ebird_code("Cardinalis cardinalis") == "norcar"
        assert mock_birdnet_model.get_ebird_code("Cyanocitta cristata") == "blujay"

    def test_get_ebird_code_not_found(self, mock_birdnet_model):
        """Test lookup returns None for unknown species."""
        assert mock_birdnet_model.get_ebird_code("Unknown species") is None
        assert mock_birdnet_model.get_ebird_code("Fakeus birdus") is None

    def test_get_ebird_code_non_bird(self, mock_birdnet_model):
        """Test lookup returns None for non-bird species like Homo sapiens."""
        assert mock_birdnet_model.get_ebird_code("Homo sapiens") is None

    def test_empty_scientific_name(self, mock_birdnet_model):
        """Test lookup with empty string returns None."""
        assert mock_birdnet_model.get_ebird_code("") is None

    def test_case_sensitive_lookup(self, mock_birdnet_model):
        """Test that lookup is case-sensitive (scientific names are case-sensitive)."""
        assert mock_birdnet_model.get_ebird_code("Turdus migratorius") == "amerob"
        assert mock_birdnet_model.get_ebird_code("turdus migratorius") is None
        assert mock_birdnet_model.get_ebird_code("TURDUS MIGRATORIUS") is None


class TestBirdNetModelProperties:
    """Test BirdNetModel interface property implementations."""

    def test_model_name(self):
        """Test name property returns expected value."""
        from model_service.birdnet_v2_model import BirdNetModel
        assert BirdNetModel.MODEL_NAME == "birdnet"

    def test_model_version(self):
        """Test version property returns expected value."""
        from model_service.birdnet_v2_model import BirdNetModel
        assert BirdNetModel.MODEL_VERSION == "2.4"

    def test_sample_rate(self):
        """Test sample rate class constant."""
        from model_service.birdnet_v2_model import BirdNetModel
        assert BirdNetModel.SAMPLE_RATE == 48000

    def test_chunk_length_seconds(self):
        """Test chunk length class constant."""
        from model_service.birdnet_v2_model import BirdNetModel
        assert BirdNetModel.CHUNK_LENGTH_SECONDS == 3.0
