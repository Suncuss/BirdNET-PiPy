"""Abstract base class for bird detection models."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from config.constants import DEFAULT_SPECIES_FILTER_THRESHOLD

from .label_utils import get_ebird_code as _lookup_ebird_code


@dataclass(frozen=True, slots=True)
class ChunkPrediction:
    """Structured prediction data for one audio chunk."""

    raw_top3: tuple[tuple[str, float], ...]
    candidates: tuple[tuple[str, float], ...]
    human_detected: bool = False


class BirdDetectionModel(ABC):
    """Abstract base class for bird detection models.

    All bird detection models must implement this interface to be usable
    by the inference server.
    """

    def __init__(self, ebird_codes_path: str | None = None):
        self.ebird_codes_path = ebird_codes_path

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

    def predict(
        self,
        audio_chunk: np.ndarray,
        sensitivity: float = 1.0,
        cutoff: float = 0.0,
        chunk_index: int | None = None
    ) -> list[tuple[str, float]]:
        """Run inference on an audio chunk and return filtered candidates.

        Args:
            audio_chunk: Float32 array normalized to [-1, 1].
            sensitivity: Confidence adjustment parameter.
            cutoff: Minimum confidence threshold (0.0-1.0).
            chunk_index: Optional chunk index for logging.

        Returns:
            List of (species_label, confidence) tuples, sorted by confidence descending.
        """
        return list(self.predict_chunk(audio_chunk, sensitivity, cutoff, chunk_index).candidates)

    @abstractmethod
    def predict_chunk(
        self,
        audio_chunk: np.ndarray,
        sensitivity: float = 1.0,
        cutoff: float = 0.0,
        chunk_index: int | None = None
    ) -> ChunkPrediction:
        """Run inference on an audio chunk and return structured chunk results."""

    @abstractmethod
    def get_labels(self) -> list[str]:
        """Return all species labels this model can detect."""

    def get_ebird_code(self, scientific_name: str) -> str | None:
        """Look up eBird species code for a scientific name."""
        return _lookup_ebird_code(scientific_name)

    def _post_process(
        self,
        labels: list[str],
        scores: np.ndarray,
        cutoff: float,
        chunk_index: int | None = None
    ) -> ChunkPrediction:
        """Build raw top-3 and filtered candidates for one chunk.

        Shared post-processing used by all model implementations after
        model-specific inference and score transformation.
        """
        # Verify labels and scores have matching lengths
        if len(labels) != len(scores):
            raise RuntimeError(
                f"Label count mismatch: {len(labels)} labels but {len(scores)} scores. "
                "Model and labels file may be out of sync."
            )

        # Top-3: O(n) partial sort, then stable argsort on the 3 winners
        # to preserve label order for tied scores (e.g. silent audio)
        k = min(3, len(scores))
        top3_idx = np.argpartition(scores, -k)[-k:]
        top3_idx = top3_idx[np.argsort(scores[top3_idx], kind='stable')[::-1]]
        raw_top3 = tuple((labels[i], float(scores[i])) for i in top3_idx)

        # Apply cutoff threshold and build candidates from passing species only
        # Use strict > 0 to exclude exact-zero scores (matches old dict-filter behavior)
        mask = (scores >= cutoff) & (scores > 0)
        passing_idx = np.nonzero(mask)[0]
        passing_scores = scores[passing_idx]
        order = np.argsort(passing_scores)[::-1]
        candidates = tuple(
            (labels[passing_idx[i]], float(passing_scores[i])) for i in order
        )
        return ChunkPrediction(raw_top3=raw_top3, candidates=candidates)

    def filter_by_location(self, lat: float, lon: float, week: int, threshold: float = DEFAULT_SPECIES_FILTER_THRESHOLD) -> list[str] | None:
        """Get species likely at a location during a specific week.

        Returns None if location filtering is not supported by this model.

        Deprecated: prefer the LocationFilter abstraction (location_filter.py)
        for new code. This method is retained for V2.4's embedded meta model.
        """
        return None
