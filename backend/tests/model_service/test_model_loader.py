"""Tests for BirdNetModel eBird code functionality."""

import json
import os
import tempfile
import pytest


class TestBirdNetModelEbirdCodes:
    """Test eBird code loading and lookup in BirdNetModel."""

    @pytest.fixture
    def temp_ebird_codes_file(self):
        """Create a temporary eBird codes JSON file for testing."""
        ebird_codes = {
            "Turdus migratorius": "amerob",
            "Cardinalis cardinalis": "norcar",
            "Cyanocitta cristata": "blujay",
            "Corvus brachyrhynchos": "amecro"
        }
        fd, path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as f:
            json.dump(ebird_codes, f)
        yield path
        os.unlink(path)

    @pytest.fixture
    def mock_birdnet_model(self, temp_ebird_codes_file):
        """Create a BirdNetModel with mocked model paths but real eBird codes."""
        from model_service.model_loader import BirdNetModel

        # Create minimal mock paths (won't actually load models)
        loader = BirdNetModel.__new__(BirdNetModel)
        loader.model_path = "/fake/model.tflite"
        loader.meta_model_path = "/fake/meta_model.tflite"
        loader.labels_path = "/fake/labels.txt"
        loader.ebird_codes_path = temp_ebird_codes_file
        loader._model = None
        loader._meta_model = None
        loader.input_layer_index = None
        loader.output_layer_index = None
        loader.meta_input_layer_index = None
        loader.meta_output_layer_index = None
        loader._labels = None
        loader._ebird_codes = None
        loader._meta_model_cache = {}
        loader._inference_lock = None
        return loader

    def test_model_loader_alias_exists(self):
        """Test that ModelLoader alias points to BirdNetModel for backwards compatibility."""
        from model_service.model_loader import ModelLoader, BirdNetModel
        assert ModelLoader is BirdNetModel

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
        # Homo sapiens is in BirdNET labels but not in eBird taxonomy
        assert mock_birdnet_model.get_ebird_code("Homo sapiens") is None

    def test_load_ebird_codes_success(self, mock_birdnet_model):
        """Test successful loading of eBird codes file."""
        codes = mock_birdnet_model.load_ebird_codes()
        assert len(codes) == 4
        assert codes["Turdus migratorius"] == "amerob"

    def test_load_ebird_codes_cached(self, mock_birdnet_model):
        """Test that eBird codes are cached after first load."""
        codes1 = mock_birdnet_model.load_ebird_codes()
        codes2 = mock_birdnet_model.load_ebird_codes()
        assert codes1 is codes2  # Same object, not reloaded

    def test_load_missing_ebird_file(self):
        """Test graceful handling of missing ebird_codes.json."""
        from model_service.model_loader import BirdNetModel

        loader = BirdNetModel.__new__(BirdNetModel)
        loader.ebird_codes_path = "/nonexistent/path/ebird_codes.json"
        loader._ebird_codes = None

        codes = loader.load_ebird_codes()
        assert codes == {}
        assert loader.get_ebird_code("Turdus migratorius") is None

    def test_load_no_ebird_path(self):
        """Test works without ebird_codes_path (backwards compatible)."""
        from model_service.model_loader import BirdNetModel

        loader = BirdNetModel.__new__(BirdNetModel)
        loader.ebird_codes_path = None
        loader._ebird_codes = None

        codes = loader.load_ebird_codes()
        assert codes == {}
        assert loader.get_ebird_code("Turdus migratorius") is None

    def test_load_invalid_json(self):
        """Test graceful handling of invalid JSON in ebird_codes.json."""
        from model_service.model_loader import BirdNetModel

        # Create a temporary file with invalid JSON
        fd, path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as f:
            f.write("not valid json {{{")

        try:
            loader = BirdNetModel.__new__(BirdNetModel)
            loader.ebird_codes_path = path
            loader._ebird_codes = None

            codes = loader.load_ebird_codes()
            assert codes == {}
        finally:
            os.unlink(path)

    def test_empty_scientific_name(self, mock_birdnet_model):
        """Test lookup with empty string returns None."""
        assert mock_birdnet_model.get_ebird_code("") is None

    def test_case_sensitive_lookup(self, mock_birdnet_model):
        """Test that lookup is case-sensitive (scientific names are case-sensitive)."""
        # Correct case
        assert mock_birdnet_model.get_ebird_code("Turdus migratorius") == "amerob"
        # Wrong case - should not match
        assert mock_birdnet_model.get_ebird_code("turdus migratorius") is None
        assert mock_birdnet_model.get_ebird_code("TURDUS MIGRATORIUS") is None


class TestBirdNetModelProperties:
    """Test BirdNetModel interface property implementations."""

    def test_model_name(self):
        """Test name property returns expected value."""
        from model_service.model_loader import BirdNetModel
        assert BirdNetModel.MODEL_NAME == "birdnet"

    def test_model_version(self):
        """Test version property returns expected value."""
        from model_service.model_loader import BirdNetModel
        assert BirdNetModel.MODEL_VERSION == "2.4"

    def test_sample_rate(self):
        """Test sample rate class constant."""
        from model_service.model_loader import BirdNetModel
        assert BirdNetModel.SAMPLE_RATE == 48000

    def test_chunk_length_seconds(self):
        """Test chunk length class constant."""
        from model_service.model_loader import BirdNetModel
        assert BirdNetModel.CHUNK_LENGTH_SECONDS == 3.0
