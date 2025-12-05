# Refactoring Plan: birdnet_server.py & main.py

This document outlines code improvements identified during a comprehensive review of the core processing modules.

## birdnet_server.py

### Issues Found

| Line | Issue | Severity |
|------|-------|----------|
| 102-103 | `custom_sigmoid` defined inside function (recreated every call) | Medium |
| 140 | `import os` inside function (already imported at top) | Low |
| 264 | `zip(audio_chunks, range(len(audio_chunks)))` → should use `enumerate()` | Low |
| 288-291 | File timestamp parsing repeated every loop iteration (constant value) | Medium |
| 251, 288, 375, 388, 402, 411 | `path.split('/')[-1]` instead of `os.path.basename()` | Low |
| 69 | Magic number `sf_thresh = 0.03` | Low |
| 79-85 | Variable `meta_model_output` reused for different types | Low |
| 222 | `process_audio_file` does too much (meta model + audio + inference + results) | High |

### Suggested Refactorings

#### 1. Move `custom_sigmoid` to module level

**Before:**
```python
def detect_species_in_audio(model, audio_input, labels, sensitivity, cutoff):
    # ...
    def custom_sigmoid(x, sensitivity):
        return 1 / (1.0 + np.exp(-sensitivity * x))
    # ...
```

**After:**
```python
# At module level - computed once
def custom_sigmoid(x, sensitivity):
    """Apply custom sigmoid with adjustable sensitivity."""
    return 1 / (1.0 + np.exp(-sensitivity * x))
```

#### 2. Use `enumerate()` instead of `zip(..., range())`

**Before:**
```python
for audio_chunk, chunk_index in zip(audio_chunks, range(len(audio_chunks))):
```

**After:**
```python
for chunk_index, audio_chunk in enumerate(audio_chunks):
```

#### 3. Hoist constant calculations out of loop

**Before (inside loop, repeated N times):**
```python
for chunk_index, audio_chunk in enumerate(audio_chunks):
    # ... processing ...
    source_file_name = audio_file_path.split('/')[-1]
    file_timestamp_str = source_file_name.split('.')[0]
    file_timestamp = datetime.datetime.strptime(file_timestamp_str, "%Y%m%d_%H%M%S")
```

**After (before loop, computed once):**
```python
source_file_name = os.path.basename(audio_file_path)
file_timestamp_str = source_file_name.split('.')[0]
file_timestamp = datetime.datetime.strptime(file_timestamp_str, "%Y%m%d_%H%M%S")

for chunk_index, audio_chunk in enumerate(audio_chunks):
    # ... processing ...
```

#### 4. Remove redundant import

```python
# Line 140 inside split_audio() - remove this
import os  # Already imported at module level
```

#### 5. Use `os.path.basename()` consistently

**Before:**
```python
audio_file_path.split('/')[-1]
```

**After:**
```python
os.path.basename(audio_file_path)
```

#### 6. Extract magic numbers to constants

```python
# At module level with other constants
SPECIES_FILTER_THRESHOLD = 0.03  # Minimum probability for local species filtering
```

---

## main.py

### Issues Found

| Line | Issue | Severity |
|------|-------|----------|
| 112-194 | `handle_detection` does 6 different things (SRP violation) | High |
| 177 | `detection.get('id')` always None (birdnet_server doesn't set it) | Low |
| 207-209 | WAV duration calc ignores header, assumes mono 16-bit | Low |
| 370-384 | `shutdown()` references threads defined later (fragile) | Medium |

### Suggested Refactorings

#### 1. Break `handle_detection` into smaller functions

**Current structure (82 lines, 6 responsibilities):**
```python
def handle_detection(detection, input_file_path, thread_logger):
    # 1. Log detection
    # 2. Calculate audio segment times
    # 3. Extract audio + convert to MP3
    # 4. Generate spectrogram
    # 5. Insert into database
    # 6. Broadcast via WebSocket
```

**Proposed structure:**
```python
def extract_detection_audio(detection: Dict, input_file_path: str) -> str:
    """Extract audio segment for detection and convert to MP3.

    Returns:
        Path to the MP3 file
    """
    step_seconds = detection.get('step_seconds', ANALYSIS_CHUNK_LENGTH)
    audio_segments_indices = select_audio_chunks(
        detection['chunk_index'], detection['total_chunks'])
    start_time = audio_segments_indices[0] * step_seconds
    end_time = audio_segments_indices[1] * step_seconds + ANALYSIS_CHUNK_LENGTH

    wav_path = os.path.join(EXTRACTED_AUDIO_DIR, detection['bird_song_file_name'])
    mp3_path = wav_path.replace('.wav', '.mp3')

    trim_audio(input_file_path, wav_path, start_time, end_time)
    convert_wav_to_mp3(wav_path, mp3_path)
    os.remove(wav_path)

    return mp3_path


def create_detection_spectrogram(detection: Dict, input_file_path: str) -> str:
    """Generate spectrogram image for detection.

    Returns:
        Path to the spectrogram image
    """
    step_seconds = detection.get('step_seconds', ANALYSIS_CHUNK_LENGTH)
    spectrogram_path = os.path.join(SPECTROGRAM_DIR, detection['spectrogram_file_name'])

    title = f"{detection['common_name']} ({detection['confidence']:.2f}) - {detection['timestamp']}"
    start_time = step_seconds * detection['chunk_index']
    end_time = start_time + ANALYSIS_CHUNK_LENGTH

    generate_spectrogram(input_file_path, spectrogram_path, title,
                        start_time=start_time, end_time=end_time)
    return spectrogram_path


def save_detection_to_db(detection: Dict) -> None:
    """Insert detection record into database."""
    db_manager.insert_detection({
        'timestamp': detection['timestamp'],
        'group_timestamp': detection['group_timestamp'],
        'scientific_name': detection['scientific_name'],
        'common_name': detection['common_name'],
        'confidence': detection['confidence'],
        'latitude': detection['latitude'],
        'longitude': detection['longitude'],
        'cutoff': detection['cutoff'],
        'sensitivity': detection['sensitivity'],
        'overlap': detection['overlap']
    })


def broadcast_detection(detection: Dict, thread_logger) -> None:
    """Send detection to WebSocket clients via API."""
    try:
        detection_data = {
            'timestamp': detection['timestamp'],
            'common_name': detection['common_name'],
            'scientific_name': detection['scientific_name'],
            'confidence': detection['confidence'],
            'bird_song_file_name': detection['bird_song_file_name'].replace('.wav', '.mp3'),
            'spectrogram_file_name': detection['spectrogram_file_name']
        }
        requests.post(
            f'http://{API_HOST}:{API_PORT}/api/broadcast/detection',
            json=detection_data,
            timeout=BROADCAST_TIMEOUT
        )
    except Exception as e:
        thread_logger.warning("Failed to broadcast detection", extra={
            'species': detection['common_name'],
            'error': str(e)
        })


def handle_detection(detection: Dict, input_file_path: str, thread_logger) -> None:
    """Process a single bird detection: create audio, spectrogram, save to DB, broadcast."""
    thread_logger.info("🐦 Bird detected", extra={
        'species': detection['common_name'],
        'confidence': round(detection['confidence'] * 100),
        'time': detection['timestamp'].split('T')[1].split('.')[0]
    })

    extract_detection_audio(detection, input_file_path)
    create_detection_spectrogram(detection, input_file_path)
    save_detection_to_db(detection)
    broadcast_detection(detection, thread_logger)

    thread_logger.debug("Saving detection to database", extra={
        'species': detection['common_name'],
        'scientific_name': detection['scientific_name']
    })
```

#### 2. Remove dead code

```python
# Line 177 - 'id' is never set by birdnet_server, remove it
detection_data = {
    'id': detection.get('id'),  # DELETE THIS LINE
    'timestamp': detection['timestamp'],
    # ...
}
```

---

## Cross-Cutting Improvements

| Improvement | Impact | Effort | Priority |
|-------------|--------|--------|----------|
| Use `os.path.basename()` consistently | Readability | Low | P1 |
| Extract `custom_sigmoid` to module level | Performance (micro) | Low | P1 |
| Use `enumerate()` | Pythonic | Low | P1 |
| Hoist loop-invariant calculations | Performance | Low | P1 |
| Remove redundant `import os` | Cleanup | Low | P1 |
| Remove dead `id` field | Cleanup | Low | P1 |
| Break down `handle_detection` | Maintainability | Medium | P2 |
| Extract magic numbers to constants | Readability | Low | P2 |
| Break down `process_audio_file` | Maintainability | High | P3 |

---

## Implementation Order

### Phase 1: Quick Wins (Low effort, immediate impact) ✅ COMPLETE
- [x] `birdnet_server.py`: Move `custom_sigmoid` to module level
- [x] `birdnet_server.py`: Use `enumerate()` instead of `zip(..., range())`
- [x] `birdnet_server.py`: Hoist file timestamp parsing out of loop
- [x] `birdnet_server.py`: Remove redundant `import os` in `split_audio()`
- [x] `birdnet_server.py`: Use `os.path.basename()` consistently
- [x] `main.py`: Remove dead `detection.get('id')` field

### Phase 2: Moderate Refactoring ✅ COMPLETE
- [x] `birdnet_server.py`: Extract `SPECIES_FILTER_THRESHOLD` constant
- [x] `main.py`: Break `handle_detection` into smaller functions

### Phase 3: Major Refactoring ✅ COMPLETE
- [x] `birdnet_server.py`: Extract `build_detection_result()` from `process_audio_file`
- [ ] Consider adding error handling/rollback in `handle_detection` (deferred - not needed currently)

---

## Notes

- All changes should be followed by running the test suite: `cd backend && ./docker-test.sh`
- Phase 1 changes are safe and unlikely to introduce bugs
- Phase 2-3 changes should be done incrementally with testing between each change
