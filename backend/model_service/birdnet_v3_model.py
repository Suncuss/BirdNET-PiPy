"""BirdNET V3.0 model implementation (ONNX Runtime)."""

import logging
import os
import subprocess
import threading

import numpy as np
import onnxruntime as ort

from .base_model import BirdDetectionModel
from .label_utils import parse_v3_labels

logger = logging.getLogger(__name__)


class BirdNetV3Model(BirdDetectionModel):
    """BirdNET V3.0 bird detection model (ONNX, 11K species, 32kHz).

    Key differences from V2.4:
    - 11K species (vs 6K)
    - 32kHz sample rate (vs 48kHz)
    - ONNX Runtime inference (vs TFLite)
    - No meta-model for location filtering
    - No privacy filter (no Human class)
    - Output is already probabilities (no sigmoid needed)
    """

    MODEL_NAME = "birdnet"
    MODEL_VERSION = "3.0"
    SAMPLE_RATE = 32000
    CHUNK_LENGTH_SECONDS = 3.0

    def __init__(
        self,
        model_path: str,
        labels_path: str,
        ebird_codes_path: str | None = None
    ):
        super().__init__(ebird_codes_path=ebird_codes_path)
        self.model_path = model_path
        self.labels_path = labels_path

        # ONNX session (lazy-loaded)
        self._session = None
        self._input_name = None
        self._output_names = None

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
        if not os.path.exists(self.model_path):
            self._download_model()
        self._load_session()
        self._load_labels()
        self.load_ebird_codes()

    def predict(
        self,
        audio_chunk: np.ndarray,
        sensitivity: float = 1.0,
        cutoff: float = 0.0,
        chunk_index: int | None = None
    ) -> list[tuple[str, float]]:
        if self._session is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        if self._labels is None:
            self._load_labels()

        # Prepare input tensor: [1, samples] float32
        model_input = np.expand_dims(audio_chunk, 0).astype(np.float32)

        # Run inference (thread-safe)
        with self._inference_lock:
            outputs = self._session.run(self._output_names, {self._input_name: model_input})

        # V3.0 returns (embeddings, predictions) — predictions are already probabilities
        probs = outputs[1][0].astype(np.float32)

        # Apply sensitivity scaling: probs^(1/sensitivity)
        probs = np.power(np.clip(probs, 1e-7, 1.0), 1.0 / sensitivity)

        # Shared post-processing: log, cutoff, filter, sort
        return self._post_process(self._labels, probs, cutoff, chunk_index)

    def get_labels(self) -> list[str]:
        if self._labels is None:
            self._load_labels()
        return self._labels

    # filter_by_location inherited from base class (returns None)

    # =========================================================================
    # Internal loading
    # =========================================================================

    def _download_model(self):
        """Download the V3.0 ONNX model from Zenodo."""
        from config import settings

        url = settings.MODEL_V3_URL
        tmp_path = f"{self.model_path}.tmp"
        min_size = 500_000_000  # ~541MB expected

        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)

        logger.info("BirdNET V3.0 model not found. Downloading (~541MB)...",
                     extra={'url': url, 'dest': self.model_path})

        try:
            subprocess.run(
                ["curl", "-SL", "--fail", "--progress-bar", "-o", tmp_path, url],
                check=True
            )
        except subprocess.CalledProcessError as e:
            self._cleanup(tmp_path)
            raise FileNotFoundError(
                f"Failed to download BirdNET V3.0 model from {url}"
            ) from e

        file_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
        if file_size < min_size:
            self._cleanup(tmp_path)
            raise FileNotFoundError(
                f"Downloaded file too small ({file_size} bytes), expected >{min_size}"
            )

        os.replace(tmp_path, self.model_path)
        logger.info("BirdNET V3.0 model downloaded successfully")

    @staticmethod
    def _cleanup(path: str):
        """Remove a file if it exists."""
        try:
            os.remove(path)
        except OSError:
            pass

    def _load_session(self):
        """Load the ONNX Runtime inference session."""
        if self._session is None:
            self._session = ort.InferenceSession(
                self.model_path, providers=['CPUExecutionProvider']
            )
            self._input_name = self._session.get_inputs()[0].name
            self._output_names = [o.name for o in self._session.get_outputs()]
            logger.info(f"Loaded ONNX model: {self.model_path}")

    def _load_labels(self):
        """Load species labels from semicolon-delimited CSV file.

        Labels are formatted as "SciName_CommonName" to match V2.4 format.
        """
        if self._labels is None:
            parsed = parse_v3_labels(self.labels_path)
            if not parsed:
                raise ValueError(f"No labels found in {self.labels_path}")
            self._labels = [f"{sci}_{com}" for sci, com in parsed]
            logger.info(f"Loaded {len(self._labels)} species labels")
