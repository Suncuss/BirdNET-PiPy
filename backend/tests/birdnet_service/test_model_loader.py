"""Tests for ModelLoader eBird code functionality."""

import json
import os
import tempfile
import pytest


class TestModelLoaderEbirdCodes:
    """Test eBird code loading and lookup in ModelLoader."""

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
    def mock_model_loader(self, temp_ebird_codes_file):
        """Create a ModelLoader with mocked model paths but real eBird codes."""
        # Import here to avoid import errors if TensorFlow isn't available
        from birdnet_service.model_loader import ModelLoader

        # Create minimal mock paths (won't actually load models)
        loader = ModelLoader.__new__(ModelLoader)
        loader.model_path = "/fake/model.tflite"
        loader.meta_model_path = "/fake/meta_model.tflite"
        loader.labels_path = "/fake/labels.txt"
        loader.ebird_codes_path = temp_ebird_codes_file
        loader.model = None
        loader.meta_model = None
        loader.input_layer_index = None
        loader.output_layer_index = None
        loader.meta_input_layer_index = None
        loader.meta_output_layer_index = None
        loader.labels = None
        loader.ebird_codes = None
        return loader

    def test_get_ebird_code_found(self, mock_model_loader):
        """Test lookup returns correct eBird code for known species."""
        assert mock_model_loader.get_ebird_code("Turdus migratorius") == "amerob"
        assert mock_model_loader.get_ebird_code("Cardinalis cardinalis") == "norcar"
        assert mock_model_loader.get_ebird_code("Cyanocitta cristata") == "blujay"

    def test_get_ebird_code_not_found(self, mock_model_loader):
        """Test lookup returns None for unknown species."""
        assert mock_model_loader.get_ebird_code("Unknown species") is None
        assert mock_model_loader.get_ebird_code("Fakeus birdus") is None

    def test_get_ebird_code_non_bird(self, mock_model_loader):
        """Test lookup returns None for non-bird species like Homo sapiens."""
        # Homo sapiens is in BirdNET labels but not in eBird taxonomy
        assert mock_model_loader.get_ebird_code("Homo sapiens") is None

    def test_load_ebird_codes_success(self, mock_model_loader):
        """Test successful loading of eBird codes file."""
        codes = mock_model_loader.load_ebird_codes()
        assert len(codes) == 4
        assert codes["Turdus migratorius"] == "amerob"

    def test_load_ebird_codes_cached(self, mock_model_loader):
        """Test that eBird codes are cached after first load."""
        codes1 = mock_model_loader.load_ebird_codes()
        codes2 = mock_model_loader.load_ebird_codes()
        assert codes1 is codes2  # Same object, not reloaded

    def test_load_missing_ebird_file(self):
        """Test graceful handling of missing ebird_codes.json."""
        from birdnet_service.model_loader import ModelLoader

        loader = ModelLoader.__new__(ModelLoader)
        loader.ebird_codes_path = "/nonexistent/path/ebird_codes.json"
        loader.ebird_codes = None

        codes = loader.load_ebird_codes()
        assert codes == {}
        assert loader.get_ebird_code("Turdus migratorius") is None

    def test_load_no_ebird_path(self):
        """Test works without ebird_codes_path (backwards compatible)."""
        from birdnet_service.model_loader import ModelLoader

        loader = ModelLoader.__new__(ModelLoader)
        loader.ebird_codes_path = None
        loader.ebird_codes = None

        codes = loader.load_ebird_codes()
        assert codes == {}
        assert loader.get_ebird_code("Turdus migratorius") is None

    def test_load_invalid_json(self):
        """Test graceful handling of invalid JSON in ebird_codes.json."""
        from birdnet_service.model_loader import ModelLoader

        # Create a temporary file with invalid JSON
        fd, path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as f:
            f.write("not valid json {{{")

        try:
            loader = ModelLoader.__new__(ModelLoader)
            loader.ebird_codes_path = path
            loader.ebird_codes = None

            codes = loader.load_ebird_codes()
            assert codes == {}
        finally:
            os.unlink(path)

    def test_empty_scientific_name(self, mock_model_loader):
        """Test lookup with empty string returns None."""
        assert mock_model_loader.get_ebird_code("") is None

    def test_case_sensitive_lookup(self, mock_model_loader):
        """Test that lookup is case-sensitive (scientific names are case-sensitive)."""
        # Correct case
        assert mock_model_loader.get_ebird_code("Turdus migratorius") == "amerob"
        # Wrong case - should not match
        assert mock_model_loader.get_ebird_code("turdus migratorius") is None
        assert mock_model_loader.get_ebird_code("TURDUS MIGRATORIUS") is None
