"""Abstract base class for bird detection models."""

import json
import logging
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)


class BirdDetectionModel(ABC):
    """Abstract base class for bird detection models.

    All bird detection models must implement this interface to be usable
    by the inference server.
    """

    def __init__(self, ebird_codes_path: str | None = None):
        self.ebird_codes_path = ebird_codes_path
        self._ebird_codes = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Model identifier (e.g., 'birdnet')."""

    @property
    @abstractmethod
    def version(self) -> str:
        """Model version string (e.g., '2.4')."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Required audio sample rate in Hz."""

    @property
    @abstractmethod
    def chunk_length_seconds(self) -> float:
        """Audio chunk length in seconds required for inference."""

    @abstractmethod
    def load(self) -> None:
        """Load all model resources into memory. Must be called before predict()."""

    @abstractmethod
    def predict(
        self,
        audio_chunk: np.ndarray,
        sensitivity: float = 1.0,
        cutoff: float = 0.0,
        chunk_index: int | None = None
    ) -> list[tuple[str, float]]:
        """Run inference on an audio chunk.

        Args:
            audio_chunk: Float32 array normalized to [-1, 1].
            sensitivity: Confidence adjustment parameter.
            cutoff: Minimum confidence threshold (0.0-1.0).
            chunk_index: Optional chunk index for logging.

        Returns:
            List of (species_label, confidence) tuples, sorted by confidence descending.
        """

    @abstractmethod
    def get_labels(self) -> list[str]:
        """Return all species labels this model can detect."""

    def get_ebird_code(self, scientific_name: str) -> str | None:
        """Look up eBird species code for a scientific name."""
        if self._ebird_codes is None:
            self.load_ebird_codes()
        return self._ebird_codes.get(scientific_name)

    def load_ebird_codes(self):
        """Load eBird species codes mapping from JSON file.

        Returns empty dict if file is missing or invalid.
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

    def _post_process(
        self,
        labels: list[str],
        scores: np.ndarray,
        cutoff: float,
        chunk_index: int | None = None
    ) -> list[tuple[str, float]]:
        """Log top results, apply cutoff threshold, filter and sort.

        Shared post-processing used by all model implementations after
        model-specific inference and score transformation.
        """
        # Log top 3 raw confidence scores before cutoff filtering
        if logger.isEnabledFor(logging.INFO):
            raw_scores = list(zip(labels, scores, strict=False))
            raw_scores_sorted = sorted(raw_scores, key=lambda x: x[1], reverse=True)[:3]
            top3_info = [
                (label.split('_', 1)[-1], round(float(score) * 100, 1))
                for label, score in raw_scores_sorted
            ]
            chunk_str = f"Chunk {chunk_index}" if chunk_index is not None else "Chunk"
            logger.info(f"{chunk_str} raw model output", extra={
                'top3': top3_info,
                'cutoff': round(cutoff * 100, 1)
            })

        # Apply cutoff threshold
        scores = np.where(scores >= cutoff, scores, 0)

        # Build results dict, filter zeros, sort descending
        results_dict = dict(zip(labels, scores, strict=False))
        results_dict = {k: v for k, v in results_dict.items() if v != 0}
        return sorted(results_dict.items(), key=lambda x: x[1], reverse=True)

    def filter_by_location(self, lat: float, lon: float, week: int) -> list[str] | None:
        """Get species likely at a location during a specific week.

        Returns None if location filtering is not supported by this model.
        """
        return None
