"""Tests for BirdNetV3Model prediction and ONNX inference."""

import os
import tempfile
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest


class TestBirdNetV3ModelProperties:
    """Test BirdNetV3Model properties."""

    def test_properties(self):
        """Verify name, version, sample_rate, and chunk_length."""
        from model_service.birdnet_v3_model import BirdNetV3Model

        model = BirdNetV3Model.__new__(BirdNetV3Model)
        assert model.name == "birdnet"
        assert model.version == "3.0"
        assert model.sample_rate == 32000
        assert model.chunk_length_seconds == 3.0


class TestBirdNetV3ModelPredict:
    """Test BirdNetV3Model.predict() method."""

    @pytest.fixture
    def mock_v3_model(self):
        """Create a BirdNetV3Model with mocked ONNX session."""
        from model_service.birdnet_v3_model import BirdNetV3Model

        model = BirdNetV3Model.__new__(BirdNetV3Model)
        model.model_path = "/fake/model.onnx"
        model.labels_path = "/fake/labels.csv"
        model.ebird_codes_path = None

        # Create mock ONNX session
        model._session = MagicMock()
        model._input_name = "input"
        model._output_names = ["embeddings", "predictions"]

        # Set labels (no Human class in V3.0)
        model._labels = [
            "Turdus migratorius_American Robin",
            "Cardinalis cardinalis_Northern Cardinal",
            "Cyanocitta cristata_Blue Jay",
            "Corvus brachyrhynchos_American Crow"
        ]
        model._ebird_codes = {}
        model._inference_lock = threading.Lock()

        return model

    def test_predict_returns_sorted_results(self, mock_v3_model):
        """Test predict returns results sorted by confidence descending."""
        # V3.0 outputs (embeddings, predictions) — predictions are already probabilities
        embeddings = np.zeros((1, 256), dtype=np.float32)
        predictions = np.array([[0.3, 0.8, 0.1, 0.5]])  # Robin, Cardinal, BlueJay, Crow
        mock_v3_model._session.run.return_value = [embeddings, predictions]

        audio_chunk = np.zeros(96000, dtype=np.float32)  # 3 seconds at 32kHz
        results = mock_v3_model.predict(audio_chunk, sensitivity=1.0, cutoff=0.0)

        # Results should be sorted by confidence descending
        assert len(results) == 4
        confidences = [r[1] for r in results]
        assert confidences == sorted(confidences, reverse=True)

        # Cardinal should be first (highest prob)
        assert results[0][0] == "Cardinalis cardinalis_Northern Cardinal"

    def test_predict_applies_cutoff(self, mock_v3_model):
        """Test predict filters out results below cutoff threshold."""
        embeddings = np.zeros((1, 256), dtype=np.float32)
        predictions = np.array([[0.9, 0.3, 0.05, 0.1]])
        mock_v3_model._session.run.return_value = [embeddings, predictions]

        audio_chunk = np.zeros(96000, dtype=np.float32)

        # High cutoff should filter most results
        results = mock_v3_model.predict(audio_chunk, sensitivity=1.0, cutoff=0.5)

        # Only high confidence results should remain
        assert len(results) == 1
        assert results[0][0] == "Turdus migratorius_American Robin"
        for _label, confidence in results:
            assert confidence >= 0.5

    def test_predict_no_privacy_filter(self, mock_v3_model):
        """Test that V3.0 has NO human detection / privacy filter."""
        # Even if we add a label with "Human", V3.0 should NOT filter it out
        # (unlike V2.4 which checks for Human and returns empty list)
        mock_v3_model._labels = [
            "Turdus migratorius_American Robin",
            "Homo sapiens_Human",
            "Cyanocitta cristata_Blue Jay"
        ]

        embeddings = np.zeros((1, 256), dtype=np.float32)
        predictions = np.array([[0.3, 0.9, 0.1]])  # Human has highest confidence
        mock_v3_model._session.run.return_value = [embeddings, predictions]

        audio_chunk = np.zeros(96000, dtype=np.float32)
        results = mock_v3_model.predict(audio_chunk, sensitivity=1.0, cutoff=0.0)

        # V3.0 should NOT filter out Human - returns all results
        assert len(results) == 3
        labels = [r[0] for r in results]
        assert "Homo sapiens_Human" in labels

    def test_sensitivity_scaling(self, mock_v3_model):
        """Test probs^(1/sensitivity) math: 1.0 is no-op, >1.0 boosts, <1.0 reduces."""
        embeddings = np.zeros((1, 256), dtype=np.float32)
        # Use a moderate probability for clear sensitivity effect
        predictions = np.array([[0.5, 0.3, 0.1, 0.05]])
        mock_v3_model._session.run.return_value = [embeddings, predictions]

        audio_chunk = np.zeros(96000, dtype=np.float32)

        # Sensitivity = 1.0 should be (near) no-op
        results_default = mock_v3_model.predict(audio_chunk, sensitivity=1.0, cutoff=0.0)
        conf_default = results_default[0][1]
        assert abs(conf_default - 0.5) < 0.01

        # Sensitivity > 1.0 should boost confidence (prob^(1/2) > prob for prob < 1)
        mock_v3_model._session.run.return_value = [embeddings, predictions.copy()]
        results_high = mock_v3_model.predict(audio_chunk, sensitivity=2.0, cutoff=0.0)
        conf_high = results_high[0][1]
        assert conf_high > conf_default

        # Sensitivity < 1.0 should reduce confidence (prob^2 < prob for prob < 1)
        mock_v3_model._session.run.return_value = [embeddings, predictions.copy()]
        results_low = mock_v3_model.predict(audio_chunk, sensitivity=0.5, cutoff=0.0)
        conf_low = results_low[0][1]
        assert conf_low < conf_default

    def test_predict_raises_if_model_not_loaded(self):
        """Test predict raises RuntimeError if model not loaded."""
        from model_service.birdnet_v3_model import BirdNetV3Model

        model = BirdNetV3Model.__new__(BirdNetV3Model)
        model._session = None
        model._inference_lock = threading.Lock()

        audio_chunk = np.zeros(96000, dtype=np.float32)

        with pytest.raises(RuntimeError, match="Model not loaded"):
            model.predict(audio_chunk)

    def test_predict_thread_safety(self, mock_v3_model):
        """Test that predict uses lock for thread-safe inference."""
        embeddings = np.zeros((1, 256), dtype=np.float32)
        predictions = np.array([[0.5, 0.3, 0.1, 0.05]])
        mock_v3_model._session.run.return_value = [embeddings, predictions]

        audio_chunk = np.zeros(96000, dtype=np.float32)
        results = []
        errors = []

        def run_predict():
            try:
                r = mock_v3_model.predict(audio_chunk, sensitivity=1.0, cutoff=0.0)
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run_predict) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 5


class TestBirdNetV3ModelLoadLabels:
    """Test BirdNetV3Model label loading from CSV."""

    def test_load_labels_csv(self):
        """Test parsing semicolon-delimited CSV to SciName_CommonName format."""
        from model_service.birdnet_v3_model import BirdNetV3Model

        # Create a temp CSV matching V3.0 format
        csv_content = (
            "idx;id;sci_name;com_name;class;order\n"
            "0;3;Turdus migratorius;American Robin;Aves;Passeriformes\n"
            "1;5;Cardinalis cardinalis;Northern Cardinal;Aves;Passeriformes\n"
            "2;6;Cyanocitta cristata;Blue Jay;Aves;Passeriformes\n"
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False,
                                         encoding='utf-8') as f:
            f.write(csv_content)
            csv_path = f.name

        try:
            model = BirdNetV3Model.__new__(BirdNetV3Model)
            model.labels_path = csv_path
            model._labels = None

            model._load_labels()

            assert len(model._labels) == 3
            assert model._labels[0] == "Turdus migratorius_American Robin"
            assert model._labels[1] == "Cardinalis cardinalis_Northern Cardinal"
            assert model._labels[2] == "Cyanocitta cristata_Blue Jay"
        finally:
            os.unlink(csv_path)

    def test_load_labels_csv_with_bom(self):
        """Test parsing CSV with UTF-8 BOM (as the real file has)."""
        from model_service.birdnet_v3_model import BirdNetV3Model

        csv_content = (
            "\ufeffidx;id;sci_name;com_name;class;order\n"
            "0;3;Abeillia abeillei;Emerald-chinned Hummingbird;Aves;Apodiformes\n"
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False,
                                         encoding='utf-8') as f:
            f.write(csv_content)
            csv_path = f.name

        try:
            model = BirdNetV3Model.__new__(BirdNetV3Model)
            model.labels_path = csv_path
            model._labels = None

            model._load_labels()

            assert len(model._labels) == 1
            assert model._labels[0] == "Abeillia abeillei_Emerald-chinned Hummingbird"
        finally:
            os.unlink(csv_path)

    def test_load_labels_empty_raises(self):
        """Test that empty CSV raises ValueError."""
        from model_service.birdnet_v3_model import BirdNetV3Model

        csv_content = "idx;id;sci_name;com_name;class;order\n"

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False,
                                         encoding='utf-8') as f:
            f.write(csv_content)
            csv_path = f.name

        try:
            model = BirdNetV3Model.__new__(BirdNetV3Model)
            model.labels_path = csv_path
            model._labels = None

            with pytest.raises(ValueError, match="No labels found"):
                model._load_labels()
        finally:
            os.unlink(csv_path)


class TestBirdNetV3ModelFilterByLocation:
    """Test BirdNetV3Model location filtering."""

    def test_filter_by_location_returns_none(self):
        """V3.0 has no meta-model, so filter_by_location should return None."""
        from model_service.birdnet_v3_model import BirdNetV3Model

        model = BirdNetV3Model.__new__(BirdNetV3Model)

        result = model.filter_by_location(42.0, -76.0, 25)
        assert result is None
