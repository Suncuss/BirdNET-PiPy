"""BirdNET model implementation.

This module provides the BirdNetModel class which implements the BirdDetectionModel
interface for the BirdNET v2.4 bird detection model.
"""

import json
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
    """Apply custom sigmoid with adjustable sensitivity.

    Args:
        x: Raw model output values
        sensitivity: Multiplier for the sigmoid function

    Returns:
        Transformed values in range [0, 1]
    """
    return 1 / (1.0 + np.exp(-sensitivity * x))


def _label_to_common_name(label: str) -> str:
    """Extract common name from a BirdNET label."""
    parts = label.split('_', 1)
    return parts[1] if len(parts) == 2 else label


class BirdNetModel(BirdDetectionModel):
    """BirdNET v2.4 bird detection model implementation.

    This class implements the BirdDetectionModel interface for the BirdNET
    Global 6K v2.4 model, providing bird species detection from audio input.

    Attributes:
        MODEL_NAME: Static identifier for this model type
        MODEL_VERSION: Version string for this model
    """

    # Model identification (class-level for backwards compatibility)
    MODEL_NAME = "birdnet"
    MODEL_VERSION = "2.4"

    # Audio requirements for BirdNET (hardcoded model constraints)
    SAMPLE_RATE = 48000
    CHUNK_LENGTH_SECONDS = 3.0

    def __init__(
        self,
        model_path: str,
        meta_model_path: str,
        labels_path: str,
        ebird_codes_path: str | None = None
    ):
        """Initialize BirdNetModel with model file paths.

        Args:
            model_path: Path to main TFLite model file
            meta_model_path: Path to meta-model TFLite file for location filtering
            labels_path: Path to species labels text file
            ebird_codes_path: Optional path to eBird codes JSON file
        """
        self.model_path = model_path
        self.meta_model_path = meta_model_path
        self.labels_path = labels_path
        self.ebird_codes_path = ebird_codes_path

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
        self._ebird_codes = None

        # Cache for meta-model results (lat, lon, week -> species list)
        self._meta_model_cache = {}

        # Lock for thread-safe inference
        self._inference_lock = threading.Lock()

    # =========================================================================
    # BirdDetectionModel interface implementation
    # =========================================================================

    @property
    def name(self) -> str:
        """Model identifier."""
        return self.MODEL_NAME

    @property
    def version(self) -> str:
        """Model version string."""
        return self.MODEL_VERSION

    @property
    def sample_rate(self) -> int:
        """Required audio sample rate in Hz."""
        return self.SAMPLE_RATE

    @property
    def chunk_length_seconds(self) -> float:
        """Audio chunk length required for inference."""
        return self.CHUNK_LENGTH_SECONDS

    def load(self) -> None:
        """Load all model resources into memory.

        Loads:
        - Main TFLite model (for inference)
        - Meta model (for location filtering)
        - Species labels
        - eBird codes mapping
        """
        self.load_model()
        self.load_meta_model()
        self.load_labels()
        self.load_ebird_codes()

    def predict(
        self,
        audio_chunk: np.ndarray,
        sensitivity: float = 1.0,
        cutoff: float = 0.0,
        chunk_index: int | None = None
    ) -> list[tuple[str, float]]:
        """Run inference on audio chunk with filtering.

        Args:
            audio_chunk: Audio samples as float32 array, normalized to [-1, 1]
            sensitivity: Confidence adjustment parameter (sigmoid multiplier)
            cutoff: Minimum confidence threshold (0.0-1.0)
            chunk_index: Optional chunk index for logging or diagnostics

        Returns:
            List of (species_label, confidence) tuples, sorted by confidence desc.
            Returns empty list if human detected (privacy filter).
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        if self._labels is None:
            self.load_labels()

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

        # Log top 3 raw confidence scores before cutoff filtering
        if logger.isEnabledFor(logging.INFO):
            raw_scores = list(zip(self._labels, model_output, strict=False))
            raw_scores_sorted = sorted(raw_scores, key=lambda x: x[1], reverse=True)[:3]
            top3_info = [(_label_to_common_name(label), round(float(score) * 100, 1))
                         for label, score in raw_scores_sorted]
            chunk_str = f"Chunk {chunk_index}" if chunk_index is not None else "Chunk"
            logger.info(f"{chunk_str} raw model output", extra={
                'top3': top3_info,
                'cutoff': round(cutoff * 100, 1)
            })

        # Apply cutoff threshold
        model_output = np.where(model_output >= cutoff, model_output, 0)

        # Build results dict
        results_dict = dict(zip(self._labels, model_output, strict=False))
        results_dict = {k: v for k, v in results_dict.items() if v != 0}

        # Sort by confidence (descending)
        results = sorted(results_dict.items(), key=lambda x: x[1], reverse=True)

        # Privacy filter: check for human detection
        human_detection = any('Human' in species_label for species_label, _ in results)
        if human_detection:
            logger.warning("Human detected in audio - chunk discarded for privacy")
            return []

        return results

    def get_labels(self) -> list[str]:
        """Return all species labels this model can detect."""
        if self._labels is None:
            self.load_labels()
        return self._labels

    def get_ebird_code(self, scientific_name: str) -> str | None:
        """Get eBird species code for a scientific name.

        Args:
            scientific_name: Scientific name (e.g., "Turdus migratorius")

        Returns:
            eBird species code (e.g., "amerob") or None if not found
        """
        if self._ebird_codes is None:
            self.load_ebird_codes()
        return self._ebird_codes.get(scientific_name)

    def filter_by_location(
        self,
        lat: float,
        lon: float,
        week: int
    ) -> list[str] | None:
        """Get species likely at a location using the meta-model.

        Results are cached by (lat, lon, week) since these values change infrequently.

        Args:
            lat: Latitude (-90 to 90)
            lon: Longitude (-180 to 180)
            week: ISO week number (1-53)

        Returns:
            List of species labels likely at the location.
        """
        if self._meta_model is None:
            raise RuntimeError("Meta model not loaded. Call load() first.")

        cache_key = (lat, lon, week)

        # Return cached result if available
        if cache_key in self._meta_model_cache:
            logger.debug("Meta model cache hit", extra={
                'lat': lat, 'lon': lon, 'week': week,
                'cached_species_count': len(self._meta_model_cache[cache_key])
            })
            return self._meta_model_cache[cache_key]

        # Cache miss - run inference
        logger.debug("Meta model cache miss - running inference", extra={
            'lat': lat, 'lon': lon, 'week': week
        })

        local_species = []

        # Prepare input tensor
        meta_model_input = np.expand_dims(
            np.array([lat, lon, week], dtype='float32'), 0)

        # Run meta-model inference (thread-safe)
        with self._inference_lock:
            self._meta_model.set_tensor(self.meta_input_layer_index, meta_model_input)
            self._meta_model.invoke()
            # Use .copy() to avoid holding references to internal TFLite tensor data
            meta_model_output = self._meta_model.get_tensor(
                self.meta_output_layer_index)[0].copy()

        # Apply threshold and filter
        meta_model_output = np.where(
            meta_model_output >= SPECIES_FILTER_THRESHOLD, meta_model_output, 0)
        species_with_probs = list(zip(meta_model_output, self._labels, strict=False))
        species_with_probs = sorted(species_with_probs, key=lambda x: x[0], reverse=True)

        for prob, species_label in species_with_probs:
            if prob >= SPECIES_FILTER_THRESHOLD:
                local_species.append(species_label)

        # Cache the result
        self._meta_model_cache[cache_key] = local_species

        return local_species

    # =========================================================================
    # Legacy methods (kept for backwards compatibility)
    # =========================================================================

    @property
    def model(self):
        """Legacy accessor for the TFLite model interpreter."""
        return self._model

    @property
    def meta_model(self):
        """Legacy accessor for the meta-model interpreter."""
        return self._meta_model

    @property
    def labels(self):
        """Legacy accessor for labels."""
        return self._labels

    @property
    def ebird_codes(self):
        """Legacy accessor for eBird codes."""
        return self._ebird_codes

    def load_model(self):
        """Load the main TFLite model (lazy-loaded).

        Returns:
            TFLite Interpreter instance
        """
        if self._model is None:
            self._model = tflite.Interpreter(model_path=self.model_path, num_threads=2)
            self._model.allocate_tensors()
            self.input_layer_index = self._model.get_input_details()[0]['index']
            self.output_layer_index = self._model.get_output_details()[0]['index']
        return self._model

    def load_meta_model(self):
        """Load the meta-model for location filtering (lazy-loaded).

        Returns:
            TFLite Interpreter instance
        """
        if self._meta_model is None:
            self._meta_model = tflite.Interpreter(model_path=self.meta_model_path)
            self._meta_model.allocate_tensors()
            self.meta_input_layer_index = self._meta_model.get_input_details()[0]['index']
            self.meta_output_layer_index = self._meta_model.get_output_details()[0]['index']
        return self._meta_model

    def load_labels(self):
        """Load species labels from text file (lazy-loaded).

        Returns:
            List of species labels
        """
        if self._labels is None:
            with open(self.labels_path) as f:
                self._labels = [line.strip() for line in f.readlines()]
        return self._labels

    def load_ebird_codes(self):
        """Load eBird species codes mapping from JSON file.

        Returns empty dict if file is missing or invalid.

        Returns:
            Dict mapping scientific names to eBird codes
        """
        if self._ebird_codes is not None:
            return self._ebird_codes

        if not self.ebird_codes_path:
            self._ebird_codes = {}
            return self._ebird_codes

        try:
            with open(self.ebird_codes_path, encoding='utf-8') as f:
                self._ebird_codes = json.load(f)
            logger.info(f"Loaded {len(self._ebird_codes)} eBird species codes")
        except FileNotFoundError:
            logger.warning(f"eBird codes file not found: {self.ebird_codes_path}")
            self._ebird_codes = {}
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in eBird codes file: {e}")
            self._ebird_codes = {}

        return self._ebird_codes


# Backwards compatibility alias
ModelLoader = BirdNetModel
