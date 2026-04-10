# BirdNET-PiPy Backend Test Suite

This directory contains all tests for the BirdNET-PiPy backend, organized by functionality.

## Test Structure

```
tests/
├── conftest.py                              # Main pytest config and shared fixtures
├── api/                                     # API endpoint tests (13 files)
│   ├── conftest.py                          # API-specific fixtures
│   ├── test_api_utils.py                    # API utility functions (6 tests)
│   ├── test_auth.py                         # Authentication endpoints (39 tests)
│   ├── test_bird_image_api.py               # Custom bird image upload/serve/delete (21 tests)
│   ├── test_detections_api.py               # Paginated detections and DELETE (31 tests)
│   ├── test_ha_mode.py                      # Home Assistant mode API (17 tests)
│   ├── test_logs_api.py                     # System logs endpoint (4 tests)
│   ├── test_migration_api.py                # BirdNET-Pi migration endpoints (24 tests)
│   ├── test_migration_audio_api.py          # Migration audio/spectrogram endpoints (28 tests)
│   ├── test_simple_api.py                   # Core API endpoints (37 tests)
│   ├── test_stream_test.py                  # RTSP stream test endpoint (4 tests)
│   ├── test_system_api.py                   # System update API (35 tests)
│   ├── test_timezone_lookup.py              # Offline timezone lookup (10 tests)
│   └── test_utilities.py                    # API utility functions (10 tests)
├── audio/                                   # Audio recording tests (1 file)
│   ├── conftest.py                          # Audio-specific fixtures
│   └── test_audio_manager.py                # Recorder classes (33 tests)
├── config/                                  # Configuration tests (1 file)
│   └── test_constants.py                    # Configuration constants (13 tests)
├── database/                                # Database layer tests (4 files)
│   ├── conftest.py                          # Database-specific fixtures
│   ├── test_basic_operations.py             # CRUD operations (11 tests)
│   ├── test_extra_field.py                  # Extra JSON field functionality (33 tests)
│   ├── test_normalize_detection.py          # Detection normalization (9 tests)
│   ├── test_notification_queries.py         # Notification query methods (13 tests)
│   └── test_query_methods.py                # Query methods and edge cases (19 tests)
├── integration/                             # Full system integration tests (1 file)
│   ├── conftest.py                          # Integration-specific fixtures
│   └── test_main_pipeline.py                # Main processing pipeline (56 tests)
├── model_service/                           # Model service tests (6 files)
│   ├── test_api_contract.py                 # API response format stability (10 tests)
│   ├── test_base_model.py                   # Base model interface and factory (11 tests)
│   ├── test_birdnet_model.py                # V2.4 prediction and privacy filter (15 tests)
│   ├── test_birdnet_v3_model.py             # V3.0 ONNX inference (12 tests)
│   ├── test_location_filter.py              # Location filter abstraction (30 tests)
│   └── test_model_loader.py                 # eBird code functionality (9 tests)
├── notification_service/                    # Notification tests (1 file)
│   ├── conftest.py                          # Notification-specific fixtures
│   └── test_notification_service.py         # Notification service (28 tests)
├── scripts/                                 # Script tests (1 file)
│   └── test_download_ebird_taxonomy.py      # eBird taxonomy download (8 tests)
├── fixtures/                                # Shared test utilities
│   ├── create_test_db.py                    # Test database creation
│   └── test_config.py                       # Test database schema
├── test_bird_name_utils.py                  # Localized bird name helpers (2 tests)
├── test_birdweather_service.py              # BirdWeather service (22 tests)
├── test_log_reader.py                       # Log reader module (25 tests)
├── test_main.py                             # core.main helper functions (1 test)
├── test_migration_audio.py                  # Audio migration (8 tests)
├── test_runtime_config.py                   # Runtime setting change classification (27 tests)
├── test_split_audio.py                      # Audio chunking with overlap (12 tests)
├── test_storage_manager.py                  # Disk usage and cleanup (19 tests)
├── test_timezone_service.py                 # Timezone service (5 tests)
├── test_utils.py                            # Utility functions (65 tests)
└── test_weather_service.py                  # Weather service (20 tests)
```

## Running Tests

### Using Docker (Recommended)

Tests are designed to run inside a Docker container to ensure a consistent environment matching production:

```bash
# Navigate to backend directory
cd backend/

# Run all tests in Docker
./docker-test.sh

# Run specific test category in Docker
./docker-test.sh database
./docker-test.sh api
./docker-test.sh integration

# Run with coverage report
./docker-test.sh coverage
```

### Using the Test Script (inside Docker or with local Python)

```bash
# Run all tests
./run-tests.sh

# Run specific test categories
./run-tests.sh database      # Database tests only
./run-tests.sh api           # API tests only
./run-tests.sh integration   # Integration tests only

# Run all tests with coverage report
./run-tests.sh coverage

# Pass additional pytest arguments
./run-tests.sh database -k "test_insert"  # Run specific test
./run-tests.sh -x                         # Stop on first failure
```

### Direct pytest Commands (inside Docker)

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific directory
python -m pytest tests/database/ -v
python -m pytest tests/api/ -v
python -m pytest tests/model_service/ -v

# Run specific test file
python -m pytest tests/test_utils.py -v

# Run with coverage
python -m pytest tests/ --cov=core --cov=model_service --cov-report=term-missing

# Run specific test by name
python -m pytest -k "test_auth" -v
```

## Test Categories

### API Tests (`tests/api/`)
Tests for Flask API endpoints with real database integration.

| File | Tests | Description |
|------|-------|-------------|
| `test_api_utils.py` | 6 | API utility functions |
| `test_auth.py` | 39 | Authentication: login, logout, password setup/reset, protected routes |
| `test_bird_image_api.py` | 21 | Custom bird image upload, serve, and delete |
| `test_detections_api.py` | 31 | Paginated detections endpoint and DELETE |
| `test_ha_mode.py` | 17 | Home Assistant mode API behavior |
| `test_logs_api.py` | 4 | System logs endpoint |
| `test_migration_api.py` | 24 | BirdNET-Pi migration endpoints |
| `test_migration_audio_api.py` | 28 | Migration audio and spectrogram endpoints |
| `test_simple_api.py` | 37 | Core endpoints: detections, species, activity, sightings, recordings, settings |
| `test_stream_test.py` | 4 | RTSP stream test endpoint |
| `test_system_api.py` | 35 | System endpoints: version info, update checks, update triggers |
| `test_timezone_lookup.py` | 10 | Offline timezone lookup via timezonefinder |
| `test_utilities.py` | 10 | API utilities: image caching, settings management, flag files |

**Key Fixtures:**
- `api_client` - Flask test client with real temporary database
- `real_db_manager` - Real DatabaseManager with temp database
- `sample_api_detection` - Sample detection data for API tests

### Audio Tests (`tests/audio/`)
Tests for audio recording modules without actual subprocess execution.

| File | Tests | Description |
|------|-------|-------------|
| `test_audio_manager.py` | 33 | RtspRecorder, PulseAudioRecorder: initialization, chunk recording, atomic operations, thread lifecycle, error handling |

**Key Fixtures:**
- `temp_output_dir` - Temporary directory for recordings
- `mock_subprocess_success/failure` - Mocked subprocess execution
- `pulse_recorder_params`, `rtsp_recorder_params` - Standard recorder configs

### Config Tests (`tests/config/`)
Tests for configuration constants and validation.

| File | Tests | Description |
|------|-------|-------------|
| `test_constants.py` | 13 | Configuration constants validation |

### Database Tests (`tests/database/`)
Tests for DatabaseManager CRUD operations and queries.

| File | Tests | Description |
|------|-------|-------------|
| `test_basic_operations.py` | 11 | Insert/retrieve, date range filtering, hourly activity, summary stats |
| `test_extra_field.py` | 33 | Extra JSON field storage, retrieval, and querying |
| `test_normalize_detection.py` | 9 | Detection data normalization |
| `test_notification_queries.py` | 13 | Notification-related database queries |
| `test_query_methods.py` | 19 | Activity overview, species sightings, detection distribution, edge cases |

**Key Fixtures:**
- `test_db_manager` - DatabaseManager with temporary test database
- `sample_detection` - Standard bird detection data
- `populated_db` - Database pre-populated with test data

### Integration Tests (`tests/integration/`)
End-to-end tests for the main processing pipeline.

| File | Tests | Description |
|------|-------|-------------|
| `test_main_pipeline.py` | 56 | Recording validation, audio file processing, directory scanning, BirdNet API integration, error handling, thread management |

**Key Fixtures:**
- `temp_recording_dir` - Temporary recording directory
- `mock_birdnet_success_response` / `mock_birdnet_empty_response` - Mocked BirdNet API responses
- `create_test_wav_file` - Factory for creating test WAV files
- `pipeline_db_manager` - Real temp database for pipeline tests

### Model Service Tests (`tests/model_service/`)
Tests for BirdNET model inference, factory pattern, and location filtering.

| File | Tests | Description |
|------|-------|-------------|
| `test_api_contract.py` | 10 | API response format stability and regression |
| `test_base_model.py` | 11 | Base model interface, factory pattern, eBird codes |
| `test_birdnet_model.py` | 15 | V2.4 TFLite prediction and privacy filter |
| `test_birdnet_v3_model.py` | 12 | V3.0 ONNX inference |
| `test_location_filter.py` | 30 | Location filter abstraction and implementations |
| `test_model_loader.py` | 9 | Model loading and eBird code functionality |

### Notification Service Tests (`tests/notification_service/`)

| File | Tests | Description |
|------|-------|-------------|
| `test_notification_service.py` | 28 | Notification triggers, cooldowns, Apprise integration |

### Script Tests (`tests/scripts/`)

| File | Tests | Description |
|------|-------|-------------|
| `test_download_ebird_taxonomy.py` | 8 | eBird taxonomy download script |

### Root-Level Tests (`tests/`)
Standalone test files for specific modules.

| File | Tests | Description |
|------|-------|-------------|
| `test_bird_name_utils.py` | 2 | Localized bird name helpers |
| `test_birdweather_service.py` | 22 | BirdWeather API service |
| `test_log_reader.py` | 25 | Log reader module |
| `test_main.py` | 1 | core.main helper functions |
| `test_migration_audio.py` | 8 | Audio migration utilities |
| `test_runtime_config.py` | 27 | Runtime setting change classification |
| `test_split_audio.py` | 12 | Audio chunking with overlap support |
| `test_storage_manager.py` | 19 | Disk usage, cleanup candidates, file deletion |
| `test_timezone_service.py` | 5 | Timezone service |
| `test_utils.py` | 65 | `build_detection_filenames()`, `select_audio_chunks()`, `build_audio_path()`, etc. |
| `test_weather_service.py` | 20 | Weather service |

## Fixtures Overview

### Main Fixtures (`conftest.py`)
```python
reset_imports       # Clears cached imports between tests (autouse)
test_env            # Sets up test environment variables
TEST_BIRD_SPECIES   # Standard test bird species list
TEST_COORDINATES    # Standard test coordinates
TEST_DETECTION_PARAMS  # Standard detection parameters
```

### Database Fixtures (`database/conftest.py`)
```python
test_db_manager     # Temporary DatabaseManager instance
sample_detection    # Standard detection dict
multiple_species_data  # List of (common_name, scientific_name, count)
populated_db        # Pre-populated database with test data
```

### API Fixtures (`api/conftest.py`)
```python
api_client          # Flask test client with real database
real_db_manager     # Real DatabaseManager for integration tests
mock_db_manager     # Mocked DatabaseManager (legacy)
sample_wikimedia_response  # Sample Wikimedia API response
sample_api_detection      # Sample detection with API-specific fields
```

### Audio Fixtures (`audio/conftest.py`)
```python
temp_output_dir         # Temporary output directory
mock_subprocess_success # Mocked successful subprocess
mock_subprocess_failure # Mocked failed subprocess
pulse_recorder_params   # PulseAudio recorder config
rtsp_recorder_params    # RTSP recorder config
```

### Integration Fixtures (`integration/conftest.py`)
```python
temp_recording_dir       # Temporary recording directory
mock_config_settings     # Mocked configuration settings
mock_birdnet_success_response  # BirdNet API success response
mock_birdnet_empty_response    # BirdNet API empty response
create_test_wav_file     # Factory for test WAV files
pipeline_db_manager      # Real temp database for pipeline tests
mock_utils_functions     # Pre-configured utility mocks
```

## Writing Tests

### Example Database Test
```python
def test_bird_detection(test_db_manager, sample_detection):
    """Test inserting and retrieving bird detection."""
    row_id = test_db_manager.insert_detection(sample_detection)
    assert isinstance(row_id, int)

    results = test_db_manager.get_latest_detections(1)
    assert len(results) == 1
    assert results[0]['common_name'] == sample_detection['common_name']
```

### Example API Test
```python
def test_get_species(api_client, real_db_manager):
    """Test species endpoint with real database."""
    # Insert test data
    real_db_manager.insert_detection({
        'common_name': 'Blue Jay',
        'scientific_name': 'Cyanocitta cristata',
        ...
    })

    # Make request
    response = api_client.get('/api/species')

    # Verify response
    assert response.status_code == 200
    data = json.loads(response.data)
    assert len(data) >= 1
```

### Example Audio Test
```python
def test_recorder_initialization(temp_output_dir):
    """Test recorder creates correctly."""
    from core.audio_manager import create_recorder

    recorder = create_recorder(
        mode='pulseaudio',
        output_dir=temp_output_dir,
        ...
    )
    assert isinstance(recorder, PulseAudioRecorder)
```

## Test Guidelines

### Best Practices
- **Isolation**: Each test uses its own temporary database/directory
- **Real Integration**: API tests use real DatabaseManager, not mocks
- **Descriptive Names**: Test names describe what's being tested
- **Arrange-Act-Assert**: Follow the AAA pattern
- **Test Both Success and Error Cases**: Include happy path and error handling

### Test Organization
- Group related tests in classes (e.g., `TestAuthEndpoints`)
- Use fixtures for common setup
- Keep tests focused and independent

## Common Issues

1. **Tests should run in Docker**: Use `./docker-test.sh` to ensure correct environment
2. **Import errors**: Ensure PYTHONPATH includes backend directory
3. **Database tests failing**: Check temporary file permissions
4. **Mock not working**: Ensure patching the correct import path

## Test Counts Summary

| Category | Files | Tests |
|----------|-------|-------|
| API | 13 | 266 |
| Audio | 1 | 33 |
| Config | 1 | 13 |
| Database | 4 | 85 |
| Integration | 1 | 56 |
| Model Service | 6 | 87 |
| Notification | 1 | 28 |
| Scripts | 1 | 8 |
| Root-level | 11 | 206 |
| **Total** | **39** | **782** |

## Coverage Reports

When running with coverage, reports are generated in multiple formats:

```bash
./run-tests.sh coverage
# or
./docker-test.sh coverage
```

- **Terminal**: Summary displayed in console
- **HTML**: Detailed report in `htmlcov/index.html`

Coverage targets the `core/` and `model_service/` modules.
