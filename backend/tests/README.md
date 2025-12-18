# BirdNET-PiPy Backend Test Suite

This directory contains all tests for the BirdNET-PiPy backend, organized by functionality.

## Test Structure

```
tests/
├── conftest.py              # Main pytest configuration and shared fixtures
├── api/                     # API endpoint tests (4 test files)
│   ├── conftest.py          # API-specific fixtures
│   ├── test_auth.py         # Authentication endpoint tests (36 tests)
│   ├── test_simple_api.py   # Core API endpoint tests (15 tests)
│   ├── test_system_api.py   # System update API tests (20 tests)
│   └── test_utilities.py    # API utility function tests (17 tests)
├── audio/                   # Audio recording tests (1 test file)
│   ├── conftest.py          # Audio-specific fixtures
│   └── test_audio_manager.py # Recorder classes tests (66 tests)
├── database/                # Database layer tests (2 test files)
│   ├── conftest.py          # Database-specific fixtures
│   ├── test_basic_operations.py  # CRUD operations tests (12 tests)
│   └── test_query_methods.py     # Query method tests (11 tests)
├── integration/             # Full system integration tests (1 test file)
│   ├── conftest.py          # Integration-specific fixtures
│   └── test_main_pipeline.py # Main processing pipeline tests (84 tests)
├── fixtures/                # Shared test data and configuration
│   ├── create_test_db.py    # Test database creation utilities
│   └── test_config.py       # Test configuration and schema
├── test_split_audio.py      # Audio chunking/overlap tests (17 tests)
├── test_storage_manager.py  # Storage and cleanup tests (26 tests)
└── test_utils.py            # Utility function tests (46 tests)
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
python -m pytest tests/audio/ -v

# Run specific test file
python -m pytest tests/test_utils.py -v

# Run with coverage
python -m pytest tests/ --cov=core --cov=birdnet_service --cov-report=term-missing

# Run specific test by name
python -m pytest -k "test_auth" -v
```

## Test Categories

### API Tests (`tests/api/`)
Tests for Flask API endpoints with real database integration.

| File | Tests | Description |
|------|-------|-------------|
| `test_auth.py` | 36 | Authentication: login, logout, password setup/reset, protected routes, auth toggle |
| `test_simple_api.py` | 15 | Core endpoints: detections, species, activity, sightings, recordings, settings |
| `test_system_api.py` | 20 | System endpoints: version info, update checks, update triggers, GitHub API |
| `test_utilities.py` | 17 | API utilities: image caching, settings management, flag files, WebSocket broadcasting |

**Key Fixtures:**
- `api_client` - Flask test client with real temporary database
- `real_db_manager` - Real DatabaseManager with temp database
- `sample_api_detection` - Sample detection data for API tests

### Audio Tests (`tests/audio/`)
Tests for audio recording modules without actual subprocess execution.

| File | Tests | Description |
|------|-------|-------------|
| `test_audio_manager.py` | 66 | HttpStreamRecorder, RtspRecorder, PulseAudioRecorder: initialization, chunk recording, atomic operations, thread lifecycle, error handling |

**Key Fixtures:**
- `temp_output_dir` - Temporary directory for recordings
- `mock_subprocess_success/failure` - Mocked subprocess execution
- `http_recorder_params`, `pulse_recorder_params`, `rtsp_recorder_params` - Standard recorder configs

### Database Tests (`tests/database/`)
Tests for DatabaseManager CRUD operations and queries.

| File | Tests | Description |
|------|-------|-------------|
| `test_basic_operations.py` | 12 | Insert/retrieve, date range filtering, hourly activity, summary stats, bird recordings |
| `test_query_methods.py` | 10 | Activity overview, species sightings, detection distribution, edge cases |

**Key Fixtures:**
- `test_db_manager` - DatabaseManager with temporary test database
- `sample_detection` - Standard bird detection data
- `populated_db` - Database pre-populated with test data

### Integration Tests (`tests/integration/`)
End-to-end tests for the main processing pipeline.

| File | Tests | Description |
|------|-------|-------------|
| `test_main_pipeline.py` | 84 | Recording validation, audio file processing, directory scanning, BirdNet API integration, error handling, thread management |

**Key Fixtures:**
- `temp_recording_dir` - Temporary recording directory
- `mock_birdnet_success_response` / `mock_birdnet_empty_response` - Mocked BirdNet API responses
- `create_test_wav_file` - Factory for creating test WAV files
- `pipeline_db_manager` - Real temp database for pipeline tests

### Root-Level Tests (`tests/`)
Standalone test files for specific modules.

| File | Tests | Description |
|------|-------|-------------|
| `test_utils.py` | 46 | `build_detection_filenames()`, `select_audio_chunks()`, `build_audio_path()`, `build_spectrogram_file_path()` |
| `test_storage_manager.py` | 26 | Disk usage, cleanup candidates, file deletion, protected species detection |
| `test_split_audio.py` | 17 | Audio chunking with overlap support, chunk sizing, backward compatibility |

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
http_recorder_params    # HTTP stream recorder config
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
| API | 4 | ~88 |
| Audio | 1 | ~66 |
| Database | 2 | ~23 |
| Integration | 1 | ~84 |
| Root-level | 3 | ~89 |
| **Total** | **11** | **~350** |

## Coverage Reports

When running with coverage, reports are generated in multiple formats:

```bash
./run-tests.sh coverage
# or
./docker-test.sh coverage
```

- **Terminal**: Summary displayed in console
- **HTML**: Detailed report in `htmlcov/index.html`

Coverage targets the `core/` and `birdnet_service/` modules.