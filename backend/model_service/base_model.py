"""Abstract base class for bird detection models.

This module defines the interface that all bird detection models must implement.
It allows the system to support multiple models (BirdNET, Perch, etc.) through
a common abstraction layer.
"""

from abc import ABC, abstractmethod

import numpy as np


class BirdDetectionModel(ABC):
    """Abstract base class for bird detection models.

    All bird detection models must implement this interface to be usable
    by the inference server. The interface provides methods for:
    - Model identification (name, version)
    - Audio requirements (sample_rate, chunk_length)
    - Core functionality (load, predict, get_labels)
    - Optional features (eBird codes, location filtering)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Model identifier (e.g., 'birdnet', 'perch')."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Model version string (e.g., '2.4')."""
        pass

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Required audio sample rate in Hz (e.g., 48000 for BirdNET)."""
        pass

    @property
    @abstractmethod
    def chunk_length_seconds(self) -> float:
        """Audio chunk length required for inference in seconds (e.g., 3.0 for BirdNET)."""
        pass

    @abstractmethod
    def load(self) -> None:
        """Load all model resources into memory.

        This method must load all resources needed for inference:
        - Main inference model
        - Any auxiliary models (e.g., meta-model for location filtering)
        - Species labels
        - Any additional data files (e.g., eBird codes)

        Must be called before predict() or filter_by_location().

        Raises:
            Exception: If model resources cannot be loaded.
        """
        pass

    @abstractmethod
    def predict(
        self,
        audio_chunk: np.ndarray,
        sensitivity: float = 1.0,
        cutoff: float = 0.0,
        chunk_index: int | None = None
    ) -> list[tuple[str, float]]:
        """Run inference on normalized audio chunk with filtering.

        This method should:
        1. Run model inference on the audio
        2. Apply sensitivity adjustment to confidence scores
        3. Filter results by cutoff threshold
        4. Apply privacy filter (return empty list if human detected)

        Args:
            audio_chunk: Audio samples as float32 array, normalized to [-1, 1].
                        Length should be sample_rate * chunk_length_seconds.
            sensitivity: Confidence adjustment parameter (sigmoid multiplier).
                        Higher values make the model more confident.
            cutoff: Minimum confidence threshold (0.0-1.0).
                   Predictions below this are filtered out.
            chunk_index: Optional chunk index for logging or diagnostics.

        Returns:
            List of (species_label, confidence) tuples, sorted by confidence desc.
            Returns empty list if human detected (privacy filter).
            Only includes species above cutoff threshold.
        """
        pass

    @abstractmethod
    def get_labels(self) -> list[str]:
        """Return all species labels this model can detect.

        Returns:
            List of species labels in the format used by the model.
            For BirdNET: "Genus_species_Common Name" format.
        """
        pass

    def get_ebird_code(self, scientific_name: str) -> str | None:
        """Look up eBird code for species.

        Override this method if the model supports eBird code lookup.

        Args:
            scientific_name: Scientific name (e.g., "Turdus migratorius")

        Returns:
            eBird species code (e.g., "amerob") or None if not found.
        """
        return None

    def filter_by_location(
        self,
        lat: float,
        lon: float,
        week: int
    ) -> list[str] | None:
        """Get species likely at a location during a specific week.

        Override this method if the model supports location-based filtering.
        This is typically implemented using a meta-model that predicts
        which species are likely to be present at a given location and time.

        Args:
            lat: Latitude (-90 to 90)
            lon: Longitude (-180 to 180)
            week: ISO week number (1-53)

        Returns:
            List of species labels likely at the location, or None if
            location filtering is not supported by this model.
            When None is returned, the caller should skip location filtering.
        """
        return None  # None means no filtering supported
