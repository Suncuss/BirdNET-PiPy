"""Tests for API contract regression - ensuring response format stability."""

import datetime
from unittest.mock import MagicMock

import pytest


class TestBuildDetectionResult:
    """Test build_detection_result() maintains expected API contract."""

    @pytest.fixture
    def mock_model(self):
        """Create a mock model that implements BirdDetectionModel interface."""
        model = MagicMock()
        model.name = "birdnet"
        model.version = "2.4"
        model.chunk_length_seconds = 3.0
        model.get_ebird_code.return_value = "amerob"
        return model

    @pytest.fixture
    def sample_species(self):
        """Sample species detection tuple from model output."""
        return ("Turdus migratorius_American Robin", 0.85)

    @pytest.fixture
    def sample_params(self):
        """Sample parameters for build_detection_result."""
        return {
            "chunk_index": 1,
            "total_chunks": 3,
            "step_seconds": 3.0,
            "file_timestamp": datetime.datetime(2024, 6, 15, 10, 30, 0),
            "source_file_name": "20240615_103000.wav",
            "lat": 42.47,
            "lon": -76.45,
            "cutoff": 0.60,
            "sensitivity": 0.75,
            "overlap": 0.0
        }

    def test_result_has_required_fields(self, mock_model, sample_species, sample_params):
        """Test that result contains all required database schema fields."""
        from model_service.inference_server import build_detection_result

        result = build_detection_result(
            sample_species,
            sample_params["chunk_index"],
            sample_params["total_chunks"],
            sample_params["step_seconds"],
            sample_params["file_timestamp"],
            sample_params["source_file_name"],
            sample_params["lat"],
            sample_params["lon"],
            sample_params["cutoff"],
            sample_params["sensitivity"],
            sample_params["overlap"],
            mock_model
        )

        # Required database schema fields
        assert "timestamp" in result
        assert "group_timestamp" in result
        assert "scientific_name" in result
        assert "common_name" in result
        assert "confidence" in result
        assert "latitude" in result
        assert "longitude" in result
        assert "cutoff" in result
        assert "sensitivity" in result
        assert "overlap" in result
        assert "extra" in result

    def test_extra_contains_model_info(self, mock_model, sample_species, sample_params):
        """Test that extra field contains model name and version."""
        from model_service.inference_server import build_detection_result

        result = build_detection_result(
            sample_species,
            sample_params["chunk_index"],
            sample_params["total_chunks"],
            sample_params["step_seconds"],
            sample_params["file_timestamp"],
            sample_params["source_file_name"],
            sample_params["lat"],
            sample_params["lon"],
            sample_params["cutoff"],
            sample_params["sensitivity"],
            sample_params["overlap"],
            mock_model
        )

        # Critical API contract - extra must contain model info
        assert result["extra"]["model"] == "birdnet"
        assert result["extra"]["model_version"] == "2.4"
        assert result["extra"]["ebird_code"] == "amerob"

    def test_species_parsing(self, mock_model, sample_species, sample_params):
        """Test correct parsing of species label into scientific and common name."""
        from model_service.inference_server import build_detection_result

        result = build_detection_result(
            sample_species,
            sample_params["chunk_index"],
            sample_params["total_chunks"],
            sample_params["step_seconds"],
            sample_params["file_timestamp"],
            sample_params["source_file_name"],
            sample_params["lat"],
            sample_params["lon"],
            sample_params["cutoff"],
            sample_params["sensitivity"],
            sample_params["overlap"],
            mock_model
        )

        # Species label is "Turdus migratorius_American Robin"
        # scientific_name should be first part (before underscore)
        # common_name should be everything after underscore
        assert result["scientific_name"] == "Turdus migratorius"
        assert result["common_name"] == "American Robin"
        assert result["confidence"] == 0.85

    def test_timestamp_calculation(self, mock_model, sample_species, sample_params):
        """Test timestamp is correctly offset by chunk index and step size."""
        from model_service.inference_server import build_detection_result

        result = build_detection_result(
            sample_species,
            sample_params["chunk_index"],  # chunk_index = 1
            sample_params["total_chunks"],
            sample_params["step_seconds"],  # step_seconds = 3.0
            sample_params["file_timestamp"],  # 10:30:00
            sample_params["source_file_name"],
            sample_params["lat"],
            sample_params["lon"],
            sample_params["cutoff"],
            sample_params["sensitivity"],
            sample_params["overlap"],
            mock_model
        )

        # timestamp should be file_timestamp + (chunk_index * step_seconds)
        # 10:30:00 + (1 * 3.0s) = 10:30:03
        expected_timestamp = datetime.datetime(2024, 6, 15, 10, 30, 3)
        assert result["timestamp"] == expected_timestamp.isoformat()

    def test_bird_song_duration_from_model(self, mock_model, sample_species, sample_params):
        """Test bird_song_duration comes from model.chunk_length_seconds."""
        from model_service.inference_server import build_detection_result

        # Set model chunk length to specific value
        mock_model.chunk_length_seconds = 3.0

        result = build_detection_result(
            sample_species,
            sample_params["chunk_index"],
            sample_params["total_chunks"],
            sample_params["step_seconds"],
            sample_params["file_timestamp"],
            sample_params["source_file_name"],
            sample_params["lat"],
            sample_params["lon"],
            sample_params["cutoff"],
            sample_params["sensitivity"],
            sample_params["overlap"],
            mock_model
        )

        assert result["bird_song_duration"] == 3.0


class TestGetScientificName:
    """Test scientific name extraction helper function."""

    def test_standard_label_format(self):
        """Test extraction from standard BirdNET label format."""
        from model_service.inference_server import get_scientific_name

        label = "Turdus migratorius_American Robin"
        result = get_scientific_name(label)
        assert result == "Turdus migratorius"

    def test_label_with_multiple_underscores(self):
        """Test extraction when common name has underscores."""
        from model_service.inference_server import get_scientific_name

        label = "Corvus brachyrhynchos_American Crow"
        result = get_scientific_name(label)
        assert result == "Corvus brachyrhynchos"

    def test_minimal_label(self):
        """Test extraction with minimal label (only two parts)."""
        from model_service.inference_server import get_scientific_name

        label = "Genus species_Common Name"
        result = get_scientific_name(label)
        assert result == "Genus species"

    def test_single_word_returns_as_is(self):
        """Test single-word labels are returned unchanged."""
        from model_service.inference_server import get_scientific_name

        label = "Unknown"
        result = get_scientific_name(label)
        assert result == "Unknown"
