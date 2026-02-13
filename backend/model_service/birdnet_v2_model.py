"""BirdNET V2.4 model implementation (TFLite)."""

import logging
import threading

import numpy as np

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    from tensorflow import lite as tflite

from .base_model import BirdDetectionModel

logger = logging.getLogger(__name__)

# Minimum probability threshold for local species filtering (meta model)
SPECIES_FILTER_THRESHOLD = 0.03


def custom_sigmoid(x: np.ndarray, sensitivity: float) -> np.ndarray:
    """Apply custom sigmoid with adjustable sensitivity."""
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

        # Cache for meta-model results (lat, lon, week -> species list)
        self._meta_model_cache = {}

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
        self.load_ebird_codes()

    def predict(
        self,
        audio_chunk: np.ndarray,
        sensitivity: float = 1.0,
        cutoff: float = 0.0,
        chunk_index: int | None = None
    ) -> list[tuple[str, float]]:
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

        # Shared post-processing: log, cutoff, filter, sort
        results = self._post_process(self._labels, model_output, cutoff, chunk_index)

        # Privacy filter: check for human detection
        human_detection = any('Human' in species_label for species_label, _ in results)
        if human_detection:
            logger.warning("Human detected in audio - chunk discarded for privacy")
            return []

        return results

    def get_labels(self) -> list[str]:
        if self._labels is None:
            self._load_labels()
        return self._labels

    def filter_by_location(self, lat: float, lon: float, week: int) -> list[str] | None:
        """Get species likely at a location using the meta-model.

        Results are cached by (lat, lon, week).
        """
        if self._meta_model is None:
            raise RuntimeError("Meta model not loaded. Call load() first.")

        cache_key = (lat, lon, week)

        if cache_key in self._meta_model_cache:
            logger.debug("Meta model cache hit", extra={
                'lat': lat, 'lon': lon, 'week': week,
                'cached_species_count': len(self._meta_model_cache[cache_key])
            })
            return self._meta_model_cache[cache_key]

        logger.debug("Meta model cache miss - running inference", extra={
            'lat': lat, 'lon': lon, 'week': week
        })

        local_species = []

        meta_model_input = np.expand_dims(
            np.array([lat, lon, week], dtype='float32'), 0)

        with self._inference_lock:
            self._meta_model.set_tensor(self.meta_input_layer_index, meta_model_input)
            self._meta_model.invoke()
            meta_model_output = self._meta_model.get_tensor(
                self.meta_output_layer_index)[0].copy()

        meta_model_output = np.where(
            meta_model_output >= SPECIES_FILTER_THRESHOLD, meta_model_output, 0)
        species_with_probs = list(zip(meta_model_output, self._labels, strict=False))
        species_with_probs = sorted(species_with_probs, key=lambda x: x[0], reverse=True)

        for prob, species_label in species_with_probs:
            if prob >= SPECIES_FILTER_THRESHOLD:
                local_species.append(species_label)

        self._meta_model_cache[cache_key] = local_species
        return local_species

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
