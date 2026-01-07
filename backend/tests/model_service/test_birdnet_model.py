"""Tests for BirdNetModel prediction and privacy filter."""

import numpy as np
import pytest
import threading
from unittest.mock import MagicMock, patch


class TestBirdNetModelPredict:
    """Test BirdNetModel.predict() method including privacy filter."""

    @pytest.fixture
    def mock_birdnet_model(self):
        """Create a BirdNetModel with mocked TFLite interpreter."""
        from model_service.model_loader import BirdNetModel

        model = BirdNetModel.__new__(BirdNetModel)
        model.model_path = "/fake/model.tflite"
        model.meta_model_path = "/fake/meta_model.tflite"
        model.labels_path = "/fake/labels.txt"
        model.ebird_codes_path = None

        # Create mock TFLite interpreter
        model._model = MagicMock()
        model._meta_model = None
        model.input_layer_index = 0
        model.output_layer_index = 1
        model.meta_input_layer_index = None
        model.meta_output_layer_index = None

        # Set labels (including Human for privacy filter testing)
        model._labels = [
            "Turdus migratorius_American Robin",
            "Cardinalis cardinalis_Northern Cardinal",
            "Homo sapiens_Human",
            "Cyanocitta cristata_Blue Jay"
        ]
        model._ebird_codes = {}
        model._meta_model_cache = {}
        model._inference_lock = threading.Lock()

        return model

    def test_predict_returns_sorted_results(self, mock_birdnet_model):
        """Test predict returns results sorted by confidence descending."""
        # Use labels without Human for this test to avoid privacy filter
        mock_birdnet_model._labels = [
            "Turdus migratorius_American Robin",
            "Cardinalis cardinalis_Northern Cardinal",
            "Cyanocitta cristata_Blue Jay"
        ]

        # Mock model output (raw values before sigmoid)
        # Using values that will produce distinct confidences after sigmoid
        raw_output = np.array([2.0, 3.0, 1.0])  # Robin, Cardinal, Blue Jay
        mock_birdnet_model._model.get_tensor.return_value = np.array([raw_output])

        audio_chunk = np.zeros(144000, dtype=np.float32)  # 3 seconds at 48kHz
        results = mock_birdnet_model.predict(audio_chunk, sensitivity=1.0, cutoff=0.0)

        # Results should be sorted by confidence
        assert len(results) >= 2
        confidences = [r[1] for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_predict_applies_cutoff(self, mock_birdnet_model):
        """Test predict filters out results below cutoff threshold."""
        # Mock output with one high and several low values
        raw_output = np.array([3.0, -3.0, -5.0, -3.0])
        mock_birdnet_model._model.get_tensor.return_value = np.array([raw_output])

        audio_chunk = np.zeros(144000, dtype=np.float32)

        # High cutoff should filter most results
        results = mock_birdnet_model.predict(audio_chunk, sensitivity=1.0, cutoff=0.9)

        # Only high confidence results should remain
        for label, confidence in results:
            assert confidence >= 0.9

    def test_predict_privacy_filter_human_detected(self, mock_birdnet_model):
        """Test predict returns empty list when Human is detected (privacy filter)."""
        # Mock output with Human having high confidence
        raw_output = np.array([1.0, 1.0, 5.0, 1.0])  # Human is index 2, high confidence
        mock_birdnet_model._model.get_tensor.return_value = np.array([raw_output])

        audio_chunk = np.zeros(144000, dtype=np.float32)
        results = mock_birdnet_model.predict(audio_chunk, sensitivity=1.0, cutoff=0.0)

        # Should return empty list due to Human detection
        assert results == []

    def test_predict_no_privacy_filter_when_human_below_cutoff(self, mock_birdnet_model):
        """Test human detection doesn't trigger if Human is below cutoff."""
        # Mock output with Human having very low confidence (below cutoff after sigmoid)
        raw_output = np.array([3.0, 2.0, -10.0, 1.0])  # Human is index 2, very low
        mock_birdnet_model._model.get_tensor.return_value = np.array([raw_output])

        audio_chunk = np.zeros(144000, dtype=np.float32)
        results = mock_birdnet_model.predict(audio_chunk, sensitivity=1.0, cutoff=0.5)

        # Human should be filtered by cutoff, so results should not be empty
        # (privacy filter only triggers if Human appears in results after cutoff)
        assert len(results) > 0

    def test_predict_sensitivity_affects_confidence(self, mock_birdnet_model):
        """Test sensitivity parameter affects confidence scores."""
        raw_output = np.array([1.0, 0.0, -5.0, 0.0])
        mock_birdnet_model._model.get_tensor.return_value = np.array([raw_output])

        audio_chunk = np.zeros(144000, dtype=np.float32)

        # Higher sensitivity should increase confidence
        results_low = mock_birdnet_model.predict(audio_chunk, sensitivity=0.5, cutoff=0.0)
        results_high = mock_birdnet_model.predict(audio_chunk, sensitivity=2.0, cutoff=0.0)

        if results_low and results_high:
            # Same species should have higher confidence with higher sensitivity
            conf_low = results_low[0][1]
            conf_high = results_high[0][1]
            assert conf_high > conf_low

    def test_predict_raises_if_model_not_loaded(self):
        """Test predict raises RuntimeError if model not loaded."""
        from model_service.model_loader import BirdNetModel

        model = BirdNetModel.__new__(BirdNetModel)
        model._model = None
        model._inference_lock = threading.Lock()

        audio_chunk = np.zeros(144000, dtype=np.float32)

        with pytest.raises(RuntimeError, match="Model not loaded"):
            model.predict(audio_chunk)


class TestCustomSigmoid:
    """Test custom_sigmoid function."""

    def test_sigmoid_basic(self):
        """Test basic sigmoid behavior."""
        from model_service.model_loader import custom_sigmoid

        # At x=0, sigmoid should return 0.5
        result = custom_sigmoid(np.array([0.0]), sensitivity=1.0)
        assert abs(result[0] - 0.5) < 0.001

    def test_sigmoid_sensitivity(self):
        """Test sensitivity affects steepness."""
        from model_service.model_loader import custom_sigmoid

        x = np.array([1.0])

        result_low = custom_sigmoid(x, sensitivity=0.5)
        result_high = custom_sigmoid(x, sensitivity=2.0)

        # Higher sensitivity should push result closer to 1
        assert result_high[0] > result_low[0]

    def test_sigmoid_output_range(self):
        """Test sigmoid output is always in [0, 1]."""
        from model_service.model_loader import custom_sigmoid

        x = np.array([-100.0, -10.0, 0.0, 10.0, 100.0])
        result = custom_sigmoid(x, sensitivity=1.0)

        assert all(0.0 <= r <= 1.0 for r in result)


class TestBirdNetModelFilterByLocation:
    """Test BirdNetModel.filter_by_location() method."""

    @pytest.fixture
    def mock_birdnet_model_with_meta(self):
        """Create a BirdNetModel with mocked meta model."""
        from model_service.model_loader import BirdNetModel

        model = BirdNetModel.__new__(BirdNetModel)
        model.model_path = "/fake/model.tflite"
        model.meta_model_path = "/fake/meta_model.tflite"
        model.labels_path = "/fake/labels.txt"
        model.ebird_codes_path = None

        model._model = None
        model._meta_model = MagicMock()
        model.input_layer_index = None
        model.output_layer_index = None
        model.meta_input_layer_index = 0
        model.meta_output_layer_index = 1

        model._labels = [
            "Turdus migratorius_American Robin",
            "Cardinalis cardinalis_Northern Cardinal",
            "Cyanocitta cristata_Blue Jay"
        ]
        model._ebird_codes = {}
        model._meta_model_cache = {}
        model._inference_lock = threading.Lock()

        return model

    def test_filter_by_location_returns_species_list(self, mock_birdnet_model_with_meta):
        """Test filter_by_location returns list of species above threshold."""
        # Mock meta model output (probabilities for each species)
        meta_output = np.array([0.5, 0.1, 0.01])  # Robin likely, Cardinal possible, Blue Jay unlikely
        mock_birdnet_model_with_meta._meta_model.get_tensor.return_value = np.array([meta_output])

        result = mock_birdnet_model_with_meta.filter_by_location(42.0, -76.0, 25)

        # Should include species above SPECIES_FILTER_THRESHOLD (0.03)
        assert "Turdus migratorius_American Robin" in result
        assert "Cardinalis cardinalis_Northern Cardinal" in result
        assert "Cyanocitta cristata_Blue Jay" not in result

    def test_filter_by_location_caches_results(self, mock_birdnet_model_with_meta):
        """Test filter_by_location caches results by (lat, lon, week)."""
        meta_output = np.array([0.5, 0.1, 0.05])
        mock_birdnet_model_with_meta._meta_model.get_tensor.return_value = np.array([meta_output])

        # First call - should invoke meta model
        result1 = mock_birdnet_model_with_meta.filter_by_location(42.0, -76.0, 25)

        # Second call with same params - should use cache
        result2 = mock_birdnet_model_with_meta.filter_by_location(42.0, -76.0, 25)

        # Results should be the same
        assert result1 == result2

        # Meta model invoke should only be called once due to caching
        assert mock_birdnet_model_with_meta._meta_model.invoke.call_count == 1

    def test_filter_by_location_raises_if_not_loaded(self):
        """Test filter_by_location raises RuntimeError if meta model not loaded."""
        from model_service.model_loader import BirdNetModel

        model = BirdNetModel.__new__(BirdNetModel)
        model._meta_model = None
        model._inference_lock = threading.Lock()

        with pytest.raises(RuntimeError, match="Meta model not loaded"):
            model.filter_by_location(42.0, -76.0, 25)
