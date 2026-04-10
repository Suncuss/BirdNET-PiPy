"""BirdNET V2.4 model implementation (TFLite)."""

import logging
import threading
from collections import OrderedDict

import numpy as np

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    from tensorflow import lite as tflite

from config import settings
from config.constants import DEFAULT_SPECIES_FILTER_THRESHOLD

from .base_model import BirdDetectionModel, ChunkPrediction

logger = logging.getLogger(__name__)

def custom_sigmoid(x: np.ndarray, sensitivity: float) -> np.ndarray:
    """Apply custom sigmoid with adjustable sensitivity."""
    if sensitivity <= 0:
        raise ValueError(f"Sensitivity must be positive, got {sensitivity}")
    return 1 / (1.0 + np.exp(-sensitivity * x))


class BirdNetModel(BirdDetectionModel):
    """BirdNET V2.4 bird detection model (TFLite, 6K species, 48kHz)."""

    MODEL_NAME = "birdnet"
    MODEL_VERSION = "2.4"
    SAMPLE_RATE = 48000
    CHUNK_LENGTH_SECONDS = 3.0

    def __init__(
        self,
        model_path: str,
        meta_model_path: str,
        labels_path: str,
        ebird_codes_path: str | None = None
    ):
        super().__init__(ebird_codes_path=ebird_codes_path)
        self.model_path = model_path
        self.meta_model_path = meta_model_path
        self.labels_path = labels_path

        # Model interpreters (lazy-loaded)
        self._model = None
        self._meta_model = None

        # Layer indices for model inference
        self.input_layer_index = None
        self.output_layer_index = None
        self.meta_input_layer_index = None
        self.meta_output_layer_index = None

        # Data (lazy-loaded)
        self._labels = None

        # Cache raw meta-model probabilities by (lat, lon, week).
        self._meta_probs_cache: OrderedDict[tuple, dict[str, float]] = OrderedDict()
        self._meta_probs_cache_max_size = settings.LOCATION_FILTER_CACHE_SIZE

        # Lock for thread-safe inference
        self._inference_lock = threading.Lock()

    # =========================================================================
    # BirdDetectionModel interface
    # =========================================================================

    @property
    def name(self) -> str:
        return self.MODEL_NAME

    @property
    def version(self) -> str:
        return self.MODEL_VERSION

    @property
    def sample_rate(self) -> int:
        return self.SAMPLE_RATE

    @property
    def chunk_length_seconds(self) -> float:
        return self.CHUNK_LENGTH_SECONDS

    def load(self) -> None:
        self._load_model()
        self._load_meta_model()
        self._load_labels()

    def predict_chunk(
        self,
        audio_chunk: np.ndarray,
        sensitivity: float = 1.0,
        cutoff: float = 0.0,
        chunk_index: int | None = None
    ) -> ChunkPrediction:
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        if self._labels is None:
            self._load_labels()

        # Prepare input tensor
        model_input = np.array(np.expand_dims(audio_chunk, 0), dtype='float32')

        # Run inference (thread-safe)
        with self._inference_lock:
            self._model.set_tensor(self.input_layer_index, model_input)
            self._model.invoke()
            # Use .copy() to avoid holding references to internal TFLite tensor data
            model_output = self._model.get_tensor(self.output_layer_index)[0].copy()

        # Apply custom sigmoid with sensitivity
        model_output = custom_sigmoid(model_output, sensitivity)

        # Shared post-processing: collect raw top-3 and filtered candidates
        prediction = self._post_process(self._labels, model_output, cutoff, chunk_index)

        # Privacy filter: check for human detection
        human_detection = any('Human' in species_label for species_label, _ in prediction.candidates)
        if human_detection:
            logger.warning("Human detected in audio - chunk discarded for privacy")
            return ChunkPrediction(
                raw_top3=prediction.raw_top3,
                candidates=(),
                human_detected=True,
            )

        return prediction

    def get_labels(self) -> list[str]:
        if self._labels is None:
            self._load_labels()
        return self._labels

    def filter_by_location(self, lat: float, lon: float, week: int, threshold: float = DEFAULT_SPECIES_FILTER_THRESHOLD) -> list[str] | None:
        """Get species likely at a location using the meta-model.

        Raw probabilities are cached by (lat, lon, week) and the threshold
        is applied per call.
        """
        probabilities = self.get_location_probabilities(lat, lon, week)
        if probabilities is None:
            return None

        return [
            label
            for label, probability in sorted(
                probabilities.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            if probability >= threshold
        ]

    def get_location_probabilities(self, lat: float, lon: float, week: int) -> dict[str, float] | None:
        """Return raw meta-model probabilities for one location/week."""
        if self._meta_model is None:
            raise RuntimeError("Meta model not loaded. Call load() first.")
        if self._labels is None:
            self._load_labels()

        cache_key = (lat, lon, week)

        with self._inference_lock:
            if cache_key in self._meta_probs_cache:
                self._meta_probs_cache.move_to_end(cache_key)
                logger.debug("Meta model cache hit", extra={
                    'lat': lat,
                    'lon': lon,
                    'week': week,
                    'cached_species_count': len(self._meta_probs_cache[cache_key]),
                })
                return self._meta_probs_cache[cache_key]

            logger.debug("Meta model cache miss - running inference", extra={
                'lat': lat,
                'lon': lon,
                'week': week,
            })

            meta_model_input = np.expand_dims(
                np.array([lat, lon, week], dtype='float32'), 0)
            self._meta_model.set_tensor(self.meta_input_layer_index, meta_model_input)
            self._meta_model.invoke()
            meta_model_output = self._meta_model.get_tensor(
                self.meta_output_layer_index)[0].copy()

            probabilities = {
                label: float(p)
                for label, p in zip(self._labels, meta_model_output, strict=True)
            }
            self._meta_probs_cache[cache_key] = probabilities
            if len(self._meta_probs_cache) > self._meta_probs_cache_max_size:
                self._meta_probs_cache.popitem(last=False)

        return probabilities

    # =========================================================================
    # Internal loading
    # =========================================================================

    def _load_model(self):
        """Load the main TFLite model."""
        if self._model is None:
            self._model = tflite.Interpreter(model_path=self.model_path, num_threads=2)
            self._model.allocate_tensors()
            self.input_layer_index = self._model.get_input_details()[0]['index']
            self.output_layer_index = self._model.get_output_details()[0]['index']

    def _load_meta_model(self):
        """Load the meta-model for location filtering."""
        if self._meta_model is None:
            self._meta_model = tflite.Interpreter(model_path=self.meta_model_path)
            self._meta_model.allocate_tensors()
            self.meta_input_layer_index = self._meta_model.get_input_details()[0]['index']
            self.meta_output_layer_index = self._meta_model.get_output_details()[0]['index']

    def _load_labels(self):
        """Load species labels from text file."""
        if self._labels is None:
            with open(self.labels_path) as f:
                self._labels = [line.strip() for line in f.readlines()]
