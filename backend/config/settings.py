import os
import json

# Base directory (always in Docker)
BASE_DIR = '/app'

# Default settings structure - single source of truth
DEFAULT_SETTINGS = {
    "location": {"latitude": 42.47, "longitude": -76.45, "configured": False},
    "detection": {"sensitivity": 0.75, "cutoff": 0.60},
    "species_filter": {
        "allowed_species": [],   # If non-empty, ONLY detect these (bypasses location filter)
        "blocked_species": []    # Never detect these species
    },
    "audio": {
        "recording_mode": "pulseaudio",  # "pulseaudio", "http_stream", or "rtsp"
        "stream_url": None,  # Custom stream URL for http_stream mode
        "rtsp_url": None,  # RTSP stream URL for rtsp mode
        "pulseaudio_source": None,  # PulseAudio source name (e.g., "default")
        "recording_length": 9,
        "overlap": 0.0,  # Overlap in seconds for future use
        "sample_rate": 48000,  # Default sample rate in Hz
        "recording_chunk_length": 3
    },
    "spectrogram": {
        "max_freq_khz": 12,
        "min_freq_khz": 0,
        "max_dbfs": 0,
        "min_dbfs": -120
    },
    "storage": {
        "auto_cleanup_enabled": True,  # Enable automatic storage cleanup
        "trigger_percent": 85,  # Start cleanup when disk usage exceeds this
        "target_percent": 80,  # Free space until usage drops to this
        "keep_per_species": 60,  # Keep top N recordings per species by confidence
        "check_interval_minutes": 30  # How often to check disk usage
    }
}


def get_default_settings():
    """Get a deep copy of default settings."""
    import copy
    return copy.deepcopy(DEFAULT_SETTINGS)


def load_user_settings():
    """Load user settings from JSON file"""
    json_path = os.path.join(BASE_DIR, 'data', 'config', 'user_settings.json')

    # Get a copy of defaults to merge with
    defaults = get_default_settings()

    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                user_data = json.load(f)
                # Deep merge user settings with defaults
                for key in defaults:
                    if key in user_data:
                        if isinstance(defaults[key], dict):
                            defaults[key].update(user_data[key])
                        else:
                            defaults[key] = user_data[key]
                return defaults
        except Exception as e:
            print(f"Error loading user settings: {e}, using defaults")
    
    return defaults

# Load settings on module import
user_settings = load_user_settings()

# Ports
BIRDNET_SERVICE_PORT = 5001
API_PORT = 5002

# Service hostnames (Docker container names)
API_HOST = 'api'
BIRDNET_HOST = 'birdnet-server'

# Recording mode configuration
RECORDING_MODE = user_settings['audio'].get('recording_mode', 'pulseaudio')

# Stream URL configuration (for http_stream mode) - directly from JSON
STREAM_URL = user_settings['audio'].get('stream_url', None)

# RTSP URL configuration (for rtsp mode) - directly from JSON
RTSP_URL = user_settings['audio'].get('rtsp_url', None)

# PulseAudio source configuration (for pulseaudio mode) - directly from JSON
PULSEAUDIO_SOURCE = user_settings['audio'].get('pulseaudio_source', 'default')


# Birdnet configuration
# Model configuration (always in Docker)
MODEL_PATH = f'{BASE_DIR}/birdnet_service/models/BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite'
META_MODEL_PATH = f'{BASE_DIR}/birdnet_service/models/BirdNET_GLOBAL_6K_V2.4_MData_Model_FP16.tflite'
LABELS_PATH = f'{BASE_DIR}/birdnet_service/models/labels.txt'
EBIRD_CODES_PATH = f'{BASE_DIR}/birdnet_service/models/ebird_codes.json'

# Geolocation configuration - from user settings
LAT = user_settings['location']['latitude']
LON = user_settings['location']['longitude']

# Prediction configuration - from user settings
SENSITIVITY = user_settings['detection']['sensitivity']
CUTOFF = user_settings['detection']['cutoff']

# Species filter configuration - from user settings
ALLOWED_SPECIES = user_settings.get('species_filter', {}).get('allowed_species', [])
BLOCKED_SPECIES = user_settings.get('species_filter', {}).get('blocked_species', [])

# Folders configuration
RECORDING_DIR = f'{BASE_DIR}/data/audio/recordings'
EXTRACTED_AUDIO_DIR = f'{BASE_DIR}/data/audio/extracted_songs'
SPECTROGRAM_DIR = f'{BASE_DIR}/data/spectrograms'

# Default placeholder files (always in Docker)
DEFAULT_AUDIO_PATH = f'{BASE_DIR}/assets/default_audio.mp3'
DEFAULT_IMAGE_PATH = f'{BASE_DIR}/assets/default_spectrogram.png'

# Audio configuration - from user settings
RECORDING_LENGTH = user_settings['audio']['recording_length']
OVERLAP = user_settings['audio']['overlap']  # Overlap in seconds for future use
SAMPLE_RATE = user_settings['audio']['sample_rate']
ANALYSIS_CHUNK_LENGTH = user_settings['audio']['recording_chunk_length']  # BirdNet analysis window (3s)

# Spectrogram configuration - from user settings
SPECTROGRAM_MAX_FREQ_IN_KHZ = user_settings['spectrogram']['max_freq_khz']
SPECTROGRAM_MIN_FREQ_IN_KHZ = user_settings['spectrogram']['min_freq_khz']
SPECTROGRAM_MAX_DBFS = user_settings['spectrogram']['max_dbfs']
SPECTROGRAM_MIN_DBFS = user_settings['spectrogram']['min_dbfs']

# Spectrogram font (always in Docker)
SPECTROGRAM_FONT_PATH = f'{BASE_DIR}/assets/Inter-Regular.ttf'

# Birdnet Server Configuration (always in Docker)
BIRDNET_SERVER_ENDPOINT = f'http://{BIRDNET_HOST}:{BIRDNET_SERVICE_PORT}/api/analyze_audio_file'

# Database configuration
DATABASE_PATH = f'{BASE_DIR}/data/db/birds.db'
DATABASE_SCHEMA = '''
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    group_timestamp DATETIME NOT NULL,
    scientific_name VARCHAR(100) NOT NULL,
    common_name VARCHAR(100) NOT NULL,
    confidence DECIMAL(5,4) NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    latitude DECIMAL(10,8) CHECK(latitude >= -90 AND latitude <= 90),
    longitude DECIMAL(11,8) CHECK(longitude >= -180 AND longitude <= 180),
    cutoff DECIMAL(4,3) CHECK(cutoff > 0 AND cutoff <= 1),
    sensitivity DECIMAL(4,3) CHECK(sensitivity > 0),
    overlap DECIMAL(4,3) CHECK(overlap >= 0 AND overlap <= 1),
    week INT GENERATED ALWAYS AS (strftime('%W', timestamp)) STORED,
    extra TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_detections_timestamp ON detections(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_detections_common_name ON detections(common_name);
CREATE INDEX IF NOT EXISTS idx_detections_scientific_name ON detections(scientific_name);
CREATE INDEX IF NOT EXISTS idx_detections_week ON detections(week);
CREATE INDEX IF NOT EXISTS idx_detections_location ON detections(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_detections_timestamp_date ON detections(date(timestamp));
CREATE INDEX IF NOT EXISTS idx_detections_species_date ON detections(common_name, date(timestamp));
'''
