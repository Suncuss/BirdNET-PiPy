import json
import os

from config.constants import DEFAULT_RECORDING_MODE, MODEL_SAMPLE_RATES, ModelType

BASE_DIR = '/app'
USER_SETTINGS_PATH = f'{BASE_DIR}/data/config/user_settings.json'

# Default settings structure - single source of truth
DEFAULT_SETTINGS = {
    "location": {"latitude": 42.47, "longitude": -76.45, "configured": False, "timezone": None},
    "detection": {"sensitivity": 0.75, "cutoff": 0.60},
    "species_filter": {
        "allowed_species": [],   # If non-empty, ONLY detect these (bypasses location filter)
        "blocked_species": []    # Never detect these species
    },
    "audio": {
        "recording_mode": DEFAULT_RECORDING_MODE,  # "pulseaudio", "http_stream", or "rtsp"
        "stream_url": None,
        "rtsp_url": None,
        "pulseaudio_source": None,
        "recording_length": 9,
        "overlap": 0.0,
        "recording_chunk_length": 3
    },
    "spectrogram": {
        "max_freq_khz": 12,
        "min_freq_khz": 0,
        "max_dbfs": 0,
        "min_dbfs": -120
    },
    "storage": {
        "auto_cleanup_enabled": True,
        "trigger_percent": 85,
        "target_percent": 80,
        "keep_per_species": 60,
        "check_interval_minutes": 30
    },
    "updates": {
        "channel": "release"  # "release" = main branch, "latest" = staging branch
    },
    "model": {
        "type": "birdnet"  # "birdnet" (v2.4, 6K species) or "birdnet_v3" (v3.0, 11K species)
    },
    "display": {
        "use_metric_units": True
    },
    "birdweather": {
        "id": None  # Station token from birdweather.com
    },
    "notifications": {
        "apprise_urls": [],
        "every_detection": False,
        "rate_limit_seconds": 300,
        "first_of_day": False,
        "rare_species": False,
        "rare_threshold": 3,
        "rare_window_days": 7
    }
}


def get_default_settings():
    """Get a deep copy of default settings."""
    import copy
    return copy.deepcopy(DEFAULT_SETTINGS)


def load_user_settings():
    """Load user settings from JSON file, merged with defaults."""
    defaults = get_default_settings()

    if os.path.exists(USER_SETTINGS_PATH):
        try:
            with open(USER_SETTINGS_PATH) as f:
                user_data = json.load(f)
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

# ── Services ──────────────────────────────────────────────────────────────────

BIRDNET_SERVICE_PORT = 5001
API_PORT = 5002
API_HOST = 'api'
BIRDNET_HOST = 'model-server'
BIRDNET_SERVER_ENDPOINT = f'http://{BIRDNET_HOST}:{BIRDNET_SERVICE_PORT}/api/analyze_audio_file'

# ── Model ─────────────────────────────────────────────────────────────────────

MODEL_TYPE = user_settings['model']['type']

MODELS_DIR = f'{BASE_DIR}/model_service/models'
EBIRD_CODES_PATH = f'{MODELS_DIR}/ebird_codes.json'

# V2.4 (TFLite, bundled with source)
MODEL_PATH = f'{MODELS_DIR}/v2.4/BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite'
META_MODEL_PATH = f'{MODELS_DIR}/v2.4/BirdNET_GLOBAL_6K_V2.4_MData_Model_FP16.tflite'
LABELS_PATH = f'{MODELS_DIR}/v2.4/labels/BirdNET_GLOBAL_6K_V2.4_Labels_en.txt'

# V3.0 (ONNX, downloaded on first use; labels bundled with source)
MODEL_V3_PATH = f'{MODELS_DIR}/v3.0/BirdNET_V3.0_Global_11K_FP32.onnx'
MODEL_V3_URL = 'https://zenodo.org/records/18247420/files/BirdNET+_V3.0-preview3_Global_11K_FP32.onnx?download=1'
LABELS_V3_PATH = f'{MODELS_DIR}/v3.0/BirdNET_V3.0_Global_11K_Labels.csv'

# ── Audio ─────────────────────────────────────────────────────────────────────

RECORDING_MODE = user_settings['audio']['recording_mode']
STREAM_URL = user_settings['audio']['stream_url']
RTSP_URL = user_settings['audio']['rtsp_url']
PULSEAUDIO_SOURCE = user_settings['audio']['pulseaudio_source'] or 'default'
RECORDING_LENGTH = user_settings['audio']['recording_length']
OVERLAP = user_settings['audio']['overlap']
ANALYSIS_CHUNK_LENGTH = user_settings['audio']['recording_chunk_length']

# Sample rate is determined by model, not user-configurable
try:
    SAMPLE_RATE = MODEL_SAMPLE_RATES[ModelType(MODEL_TYPE)]
except ValueError:
    SAMPLE_RATE = MODEL_SAMPLE_RATES[ModelType.BIRDNET]

# ── Detection ─────────────────────────────────────────────────────────────────

SENSITIVITY = user_settings['detection']['sensitivity']
CUTOFF = user_settings['detection']['cutoff']
ALLOWED_SPECIES = user_settings['species_filter']['allowed_species']
BLOCKED_SPECIES = user_settings['species_filter']['blocked_species']

# ── Location ──────────────────────────────────────────────────────────────────

LAT = user_settings['location']['latitude']
LON = user_settings['location']['longitude']
LOCATION_CONFIGURED = user_settings['location']['configured']
TIMEZONE = user_settings['location']['timezone']


def _is_valid_timezone(tz):
    if not tz:
        return False
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
        return True
    except Exception:
        return False


LOCATION_READY = LOCATION_CONFIGURED and _is_valid_timezone(TIMEZONE)

# ── BirdWeather ───────────────────────────────────────────────────────────────

BIRDWEATHER_ID = user_settings['birdweather']['id']

# ── Notifications ────────────────────────────────────────────────────────────

NOTIFICATIONS_APPRISE_URLS = user_settings['notifications']['apprise_urls']
NOTIFICATIONS_EVERY_DETECTION = user_settings['notifications']['every_detection']
NOTIFICATIONS_RATE_LIMIT_SECONDS = user_settings['notifications']['rate_limit_seconds']
NOTIFICATIONS_FIRST_OF_DAY = user_settings['notifications']['first_of_day']
NOTIFICATIONS_RARE_SPECIES = user_settings['notifications']['rare_species']
NOTIFICATIONS_RARE_THRESHOLD = user_settings['notifications']['rare_threshold']
NOTIFICATIONS_RARE_WINDOW_DAYS = user_settings['notifications']['rare_window_days']

# ── Spectrogram ───────────────────────────────────────────────────────────────

SPECTROGRAM_MAX_FREQ_IN_KHZ = user_settings['spectrogram']['max_freq_khz']
SPECTROGRAM_MIN_FREQ_IN_KHZ = user_settings['spectrogram']['min_freq_khz']
SPECTROGRAM_MAX_DBFS = user_settings['spectrogram']['max_dbfs']
SPECTROGRAM_MIN_DBFS = user_settings['spectrogram']['min_dbfs']
SPECTROGRAM_FONT_PATH = f'{BASE_DIR}/assets/Inter-Regular.ttf'

# ── Storage ───────────────────────────────────────────────────────────────────

RECORDING_DIR = f'{BASE_DIR}/data/audio/recordings'
EXTRACTED_AUDIO_DIR = f'{BASE_DIR}/data/audio/extracted_songs'
SPECTROGRAM_DIR = f'{BASE_DIR}/data/spectrograms'
CUSTOM_BIRD_IMAGES_DIR = f'{BASE_DIR}/data/bird_images'
DEFAULT_AUDIO_PATH = f'{BASE_DIR}/assets/default_audio.mp3'
DEFAULT_IMAGE_PATH = f'{BASE_DIR}/assets/default_spectrogram.webp'
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
CREATE INDEX IF NOT EXISTS idx_detections_scientific_timestamp ON detections(scientific_name, timestamp DESC);
'''
