# Known Issues and Future Improvements

This document tracks known issues, technical debt, and potential improvements for future consideration.

---

# Issue 1: Test Artifact Directory (`backend/data/`)

This section describes a known issue where running tests creates a `backend/data/` directory with test artifacts.

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

---

# Issue 2: Public API Usage Compliance

This section tracks the status of public API usage (Wikimedia, OpenStreetMap Nominatim, GitHub) and potential improvements for better compliance with their usage policies.

## Overview

The project uses three public APIs without API keys:
- **Wikimedia Commons API** - For fetching bird species images
- **OpenStreetMap Nominatim API** - For geocoding and reverse geocoding
- **GitHub API** - For checking software updates

All APIs currently include User-Agent headers and error handling, but some improvements could enhance compliance with API usage policies.

## Current Status

### Wikimedia API (backend/core/api.py:62-145)

**Status: ✅ Excellent Compliance**

Current implementation:
```python
headers = {
    'User-Agent': f'{DISPLAY_NAME}/{__version__} (Bird detection system; educational/personal use)'
}
```

Strengths:
- ✅ User-Agent header with app name, version, and description
- ✅ Comment referencing Wikimedia's User-Agent policy (line 68-70)
- ✅ TODO note to update contact info for public deployment
- ✅ 10-hour caching (`CACHE_EXPIRATION = 36000`) to reduce API load
- ✅ Proper error handling with try/except

Compliance: **A+** - Exceeds requirements

### GitHub API (backend/core/api.py:409-425)

**Status: ✅ Good Compliance**

Current implementation:
```python
headers = {
    'Accept': 'application/vnd.github.v3+json',
    'User-Agent': f'{DISPLAY_NAME}/{__version__}'
}
```

Strengths:
- ✅ User-Agent header with app name and version
- ✅ API versioning with Accept header
- ✅ 10-second timeout configured
- ✅ Comprehensive error handling (timeout, RequestException)

Rate Limits:
- Unauthenticated: 60 requests/hour per IP
- Current usage (update checks) well within limits
- Could add authentication token for higher limits if needed (not necessary)

Compliance: **A** - Meets all requirements

### OpenStreetMap Nominatim API (frontend/src/components/LocationSetupModal.vue:248-305)

**Status: ⚠️ Partial Compliance - Needs Improvement**

Current implementation:
```javascript
headers: {
  'User-Agent': 'BirdNET-PiPy/1.0 (https://github.com/Suncuss/BirdNET-PiPy)'
}
```

Strengths:
- ✅ User-Agent header with project name and GitHub URL
- ✅ Proper error handling

Issues:
- ⚠️ **No rate limiting** - Nominatim policy requires maximum 1 request/second
- ⚠️ **Missing contact info** - Policy recommends including email in User-Agent

Compliance: **B+** - Functional but violates rate limit policy

## Impact

| API | Production Impact | Compliance Risk |
|-----|------------------|-----------------|
| Wikimedia | None - fully compliant | None |
| GitHub | None - fully compliant | None |
| Nominatim | Low - but could be rate-limited/blocked if users search rapidly | Medium - violates 1 req/sec policy |

## Proposed Improvements (Priority Order)

### 1. HIGH PRIORITY: Add Nominatim Rate Limiting

**Problem:** Users can trigger multiple rapid searches, violating the 1 request/second policy.

**Risk:** Temporary IP blocking by Nominatim service.

**Proposed Solution:** Add debouncing to search function in `LocationSetupModal.vue`:

```javascript
// Add to setup()
const debouncedSearch = ref(null)

// Modify searchAddress function
const searchAddress = async () => {
  if (!searchQuery.value.trim()) return

  // Clear existing timeout
  if (debouncedSearch.value) {
    clearTimeout(debouncedSearch.value)
  }

  // Debounce to enforce 1 req/sec minimum
  debouncedSearch.value = setTimeout(async () => {
    searching.value = true
    errorMessage.value = ''
    searchResults.value = []

    try {
      const response = await fetch(
        `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(searchQuery.value)}&format=json&limit=5`,
        {
          headers: {
            'User-Agent': 'BirdNET-PiPy/1.0 (https://github.com/Suncuss/BirdNET-PiPy)'
          }
        }
      )
      // ... rest of implementation
    } finally {
      searching.value = false
    }
  }, 1000) // Enforce 1 second delay
}
```

**Effort:** Low (15 minutes)
**Priority:** High
**Files to modify:** `frontend/src/components/LocationSetupModal.vue`

### 2. MEDIUM PRIORITY: Enhance Nominatim User-Agent

**Problem:** Nominatim policy recommends including contact info (email) for support purposes.

**Current:**
```javascript
'User-Agent': 'BirdNET-PiPy/1.0 (https://github.com/Suncuss/BirdNET-PiPy)'
```

**Proposed:**
```javascript
'User-Agent': 'BirdNET-PiPy/1.0 (https://github.com/Suncuss/BirdNET-PiPy; contact@example.com)'
```

**Effort:** Low (5 minutes)
**Priority:** Medium
**Files to modify:** `frontend/src/components/LocationSetupModal.vue:254, 284`
**Note:** Requires valid contact email before implementation

### 3. LOW PRIORITY: Add Retry Logic with Exponential Backoff

**Problem:** Transient network failures cause immediate errors without retries.

**Benefit:** Improved resilience for intermittent network issues.

**Proposed:** Add retry wrapper for all API calls:

```python
def retry_with_backoff(func, max_retries=3, initial_delay=1):
    """Retry function with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return func()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            delay = initial_delay * (2 ** attempt)
            time.sleep(delay)
```

**Effort:** Medium (1-2 hours)
**Priority:** Low
**Files to modify:** `backend/core/api.py`

## Compliance Scorecard

| API | User-Agent | Rate Limiting | Caching | Error Handling | Overall Grade |
|-----|-----------|---------------|---------|----------------|---------------|
| Wikimedia | ✅ Excellent | N/A | ✅ 10hr | ✅ Yes | **A+** |
| GitHub | ✅ Good | ⚠️ Implicit | N/A | ✅ Yes | **A** |
| Nominatim | ✅ Good | ❌ Missing | N/A | ✅ Yes | **B+** |

## Related Files

- `backend/core/api.py:62-145` - Wikimedia API implementation
- `backend/core/api.py:409-425` - GitHub API implementation
- `frontend/src/components/LocationSetupModal.vue:248-305` - Nominatim API implementation

## References

- [Wikimedia Foundation User-Agent Policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy)
- [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/)
- [GitHub API Rate Limiting](https://docs.github.com/en/rest/overview/resources-in-the-rest-api#rate-limiting)
