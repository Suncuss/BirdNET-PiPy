"""
Single source of truth for configuration constants.

All validation and default values should reference these constants.
Bash scripts should document their source as this file.
"""

from enum import Enum


class ModelType(Enum):
    """Supported model types."""
    BIRDNET = "birdnet"
    BIRDNET_V3 = "birdnet_v3"


class RecorderState:
    """Recorder health state constants for type-safe comparisons."""
    RUNNING = 'running'
    DEGRADED = 'degraded'
    STOPPED = 'stopped'


class RecordingMode:
    """Recording mode constants for type-safe comparisons."""
    PULSEAUDIO = 'pulseaudio'
    RTSP = 'rtsp'


# Recording modes with UI labels
RECORDING_MODES = {
    RecordingMode.PULSEAUDIO: 'Local Microphone',
    RecordingMode.RTSP: 'RTSP Stream',
}

# Valid recording mode values (for validation)
VALID_RECORDING_MODES = tuple(RECORDING_MODES.keys())

# Default recording mode
DEFAULT_RECORDING_MODE = RecordingMode.PULSEAUDIO

# Recording lengths (seconds)
RECORDING_LENGTH_OPTIONS = (9, 12, 15)

# Overlap options (seconds)
OVERLAP_OPTIONS = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)

# Update channels
UPDATE_CHANNELS = ('release', 'latest')

# Valid model types (derived from ModelType enum)
VALID_MODEL_TYPES = tuple(m.value for m in ModelType)

# Sample rates per model type (Hz)
MODEL_SAMPLE_RATES = {
    ModelType.BIRDNET: 48000,
    ModelType.BIRDNET_V3: 32000,
}

# Species filter default thresholds
DEFAULT_SPECIES_FILTER_THRESHOLD = 0.03      # V2.4 meta-model
DEFAULT_GEOMODEL_FILTER_THRESHOLD = 0.15     # V3.0 geomodel

# Log rotation
LOG_MAX_BYTES = 5 * 1024 * 1024   # 5 MB per file
LOG_BACKUP_COUNT = 2               # 2 rotated backups (15 MB max per service)
LOG_DEFAULT_LINES = 500
LOG_MAX_LINES = 2000
