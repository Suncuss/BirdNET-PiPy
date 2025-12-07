# Known Issue: Test Artifact Directory (`backend/data/`)

This document describes a known issue where running tests creates a `backend/data/` directory with test artifacts.

## Overview

When running backend tests via `./docker-test.sh`, a `backend/data/` directory is created containing:
- `audio/` - Recording and extracted audio directories
- `db/` - Database directory
- `spectrograms/` - Spectrogram output directory

This directory is a **test artifact only** and is not used in production. It is already gitignored.

## Root Cause

### How Production Works

In production (`docker-compose.yml`), volume mounts separate code from data:

```yaml
volumes:
  - ./backend:/app
  - ./data:/app/data    # Overrides /app/data to use root data/
```

So `/app/data/` inside the container maps to `./data/` (root level), which is the correct production location.

### How Tests Work

In tests (`backend/docker-test.sh`), only the backend is mounted:

```bash
docker run -v $(pwd):/app ...
```

There's no separate data mount, so `/app/data/` maps to `./backend/data/`.

### The Problem: Module-Level Initialization

In `core/main.py:35-42`, directories are created **at import time**:

```python
# Line 35: Runs immediately when module is imported
db_manager = DatabaseManager()  # Creates /app/data/db/

# Lines 40-42: Also runs immediately on import
for dir in [RECORDING_DIR, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR]:
    os.makedirs(dir, exist_ok=True)  # Creates audio/, spectrograms/
```

When integration tests import from `core.main`:

```python
with patch('core.main.SAMPLE_RATE', 48000):
    from core.main import is_valid_recording  # Directories already created!
```

Python executes ALL module-level code **before** extracting the specific function, so directories are created before patches can take effect.

## What Has Been Fixed

### Auth Config Leakage (December 2024)

Previously, tests also created `backend/data/config/auth.json` because `create_app()` triggers session configuration which writes auth config.

**Fixed by**: Patching auth config paths in test fixtures (`backend/tests/api/conftest.py` and `backend/tests/api/test_simple_api.py`) to redirect to temp directories.

| Issue | Status | Files Modified |
|-------|--------|----------------|
| `auth.json` creation | Fixed | `tests/api/conftest.py`, `tests/api/test_simple_api.py` |
| `audio/`, `db/`, `spectrograms/` creation | Not fixed | N/A (would require `core/main.py` refactor) |

## Impact

| Environment | Impact |
|-------------|--------|
| Production | None - uses correct `data/` directory via docker-compose volumes |
| Development | Cosmetic - `backend/data/` created but gitignored |
| CI/Tests | None - tests pass, artifacts cleaned up with container |

## Proposed Fix (Future Improvement)

Refactor `core/main.py` to use lazy initialization:

### Current (Module-Level)

```python
# Runs on import
db_manager = DatabaseManager()

for dir in [RECORDING_DIR, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR]:
    os.makedirs(dir, exist_ok=True)
```

### Proposed (Lazy Initialization)

```python
# Module level - just declare
db_manager = None
_initialized = False

def _ensure_initialized():
    """Lazy initialization - only runs when actually needed."""
    global db_manager, _initialized
    if _initialized:
        return

    db_manager = DatabaseManager()
    for dir in [RECORDING_DIR, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR]:
        os.makedirs(dir, exist_ok=True)
    _initialized = True

def process_audio_file(...):
    _ensure_initialized()
    # ... rest of function

# Or for the main entry point
if __name__ == '__main__':
    _ensure_initialized()
    main()
```

### Why Not Fixed Yet

1. **Low priority**: The issue is cosmetic (gitignored test artifacts)
2. **High effort**: Would require updating ~55 integration tests
3. **Risk**: Lazy initialization adds complexity and potential for bugs

## Workaround

To clean up `backend/data/` after tests:

```bash
sudo rm -rf backend/data/
```

Note: `sudo` may be required because some files are created as root inside Docker.

## Related Files

- `backend/core/main.py:35-42` - Module-level initialization
- `backend/core/auth.py:22-24` - Auth config paths
- `backend/tests/api/conftest.py` - Test fixtures with auth patches
- `backend/docker-test.sh` - Test runner script
- `docker-compose.yml` - Production volume mounts
- `.gitignore` - Contains `backend/data/` exclusion
