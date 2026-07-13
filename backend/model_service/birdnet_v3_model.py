"""BirdNET V3.1 model implementation (ONNX Runtime)."""

import logging
import threading

import numpy as np

from .base_model import BirdDetectionModel, ChunkPrediction
from .birdnet_v3_assets import load_validated_birdnet_v3

logger = logging.getLogger(__name__)


class BirdNetV3Model(BirdDetectionModel):
    """BirdNET V3.1 bird detection model (ONNX, 11K species, 32kHz).

    Key differences from V2.4:
    - 11K species (vs 6K)
    - 32kHz sample rate (vs 48kHz)
    - ONNX Runtime inference (vs TFLite)
    - No meta-model for location filtering
    - No privacy filter (no Human class)
    - Output is already probabilities (no sigmoid needed)
    """

    MODEL_NAME = "birdnet"
    MODEL_VERSION = "3.1"
    SAMPLE_RATE = 32000
    CHUNK_LENGTH_SECONDS = 3.0

    def __init__(
        self,
        model_path: str,
        labels_path: str,
        manifest_path: str,
    ):
        super().__init__()
        self.model_path = model_path
        self.labels_path = labels_path
        self.manifest_path = manifest_path

        # ONNX session (lazy-loaded)
        self._session = None
        self._input_name = None
        self._prediction_output_name = None

        # Data (lazy-loaded)
        self._labels = None

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
        loaded = load_validated_birdnet_v3(
            self.model_path,
            self.labels_path,
            self.manifest_path,
        )
        self._session = loaded.session
        self._input_name = loaded.manifest.input_name
        self._prediction_output_name = loaded.manifest.prediction_name
        self._labels = [f"{sci}_{common}" for sci, common in loaded.labels]

        logger.info(
            "Loaded bundled BirdNET V3.1 model",
            extra={
                "model": self.model_path,
                "version": loaded.manifest.version,
                "upstream_release": loaded.manifest.upstream_name,
                "precision": loaded.manifest.precision,
                "species": len(self._labels),
            },
        )

    def predict_chunk(
        self,
        audio_chunk: np.ndarray,
        sensitivity: float = 1.0,
        cutoff: float = 0.0,
        chunk_index: int | None = None
    ) -> ChunkPrediction:
        if self._session is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        if self._labels is None:
            raise RuntimeError("Model labels were not initialized during load().")

        # Prepare input tensor: [1, samples] float32
        model_input = np.expand_dims(audio_chunk, 0).astype(np.float32)

        # Run inference (thread-safe)
        with self._inference_lock:
            outputs = self._session.run(
                [self._prediction_output_name],
                {self._input_name: model_input},
            )

        # Predictions are already probabilities. Selecting by name avoids relying
        # on the output tuple order, which changed in the V3.1 upstream export.
        probs = outputs[0][0].astype(np.float32)

        # V3 model returns NaN for all species on silent audio — treat as zero confidence
        np.nan_to_num(probs, copy=False, nan=0.0)

        # Apply sensitivity scaling: probs^(1/sensitivity)
        if sensitivity <= 0:
            raise ValueError(f"Sensitivity must be positive, got {sensitivity}")
        probs = np.power(np.clip(probs, 1e-7, 1.0), 1.0 / sensitivity)

        # Shared post-processing: collect raw top-3 and filtered candidates
        return self._post_process(self._labels, probs, cutoff, chunk_index)

    def get_labels(self) -> list[str]:
        if self._labels is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        return self._labels

    # filter_by_location inherited from base class (returns None)
