# Overlap Implementation

This document describes the audio overlap feature in BirdNET-PiPy and its compatibility with BirdNET-Pi.

## Overview

The overlap feature improves bird detection accuracy by analyzing audio with sliding windows instead of non-overlapping chunks. This helps catch bird calls that occur at chunk boundaries.

## How Overlap Works

BirdNET requires exactly 3-second audio chunks for analysis. With overlap, these 3-second windows slide across the recording with a configurable step size:

```
No Overlap (overlap=0.0, step=3.0s):
[----Chunk 0----][----Chunk 1----][----Chunk 2----]
0s              3s              6s              9s

With Overlap 1.5s (step=1.5s):
[----Chunk 0----]
      [----Chunk 1----]
            [----Chunk 2----]
                  [----Chunk 3----]
                        [----Chunk 4----]
                              [----Chunk 5----]
0s   1.5s  3s   4.5s  6s   7.5s  9s
```

## Configuration

Set the overlap value in `data/config/user_settings.json`:

```json
{
  "audio": {
    "overlap": 1.5,
    "recording_length": 9,
    "recording_chunk_length": 3,
    "sample_rate": 48000
  }
}
```

Valid overlap values: `0.0`, `0.5`, `1.0`, `1.5`, `2.0`, `2.5` seconds.

## Chunk Count by Configuration

| Recording | Overlap 0.0 | Overlap 0.5 | Overlap 1.0 | Overlap 1.5 | Overlap 2.0 | Overlap 2.5 |
|-----------|-------------|-------------|-------------|-------------|-------------|-------------|
| **9s**    | 3           | 4           | 4           | 6           | 8           | 13          |
| **12s**   | 4           | 5           | 5           | 8           | 10          | 19          |
| **15s**   | 5           | 6           | 7           | 10          | 13          | 25          |

## BirdNET-Pi Compatibility

BirdNET-PiPy's overlap implementation is designed to be compatible with BirdNET-Pi's behavior.

### Similarities

| Feature | BirdNET-Pi | BirdNET-PiPy |
|---------|------------|--------------|
| Chunk duration | 3.0 seconds | 3.0 seconds |
| Sample rate | 48,000 Hz | 48,000 Hz |
| Step size formula | `chunk_length - overlap` | `chunk_length - overlap` |
| Minimum chunk length | 1.5 seconds | 1.5 seconds |
| Short chunk handling | Zero-padded to 3s | Zero-padded to 3s |
| Very short chunks | Discarded (< 1.5s) | Discarded (< 1.5s) |
| Detection counting | Each chunk = 1 DB row | Each chunk = 1 DB row |
| Deduplication | None | None |
| Overlap values | 0.0 - 2.5 seconds | 0.0 - 2.5 seconds |

### Differences

| Feature | BirdNET-Pi | BirdNET-PiPy |
|---------|------------|--------------|
| **Timestamp granularity** | Recording start time (same for all chunks) | Per-chunk timestamp + group_timestamp |
| **Database schema** | `Date`, `Time` columns | `timestamp`, `group_timestamp` columns |
| **Architecture** | Monolithic Python | Microservices (Flask APIs) |
| **Detection storage** | Direct SQLite insert | API → BirdNet Service → Main → DB |

### Timestamp Handling

**BirdNET-Pi** stores the recording start time for all detections in a recording:
```
Recording: 14:30:25 (9 seconds)
All 3 chunk detections have Time = "14:30:25"
```

**BirdNET-PiPy** stores both per-chunk and recording timestamps:
```
Recording: 14:30:25 (9 seconds, overlap=1.5)
Chunk 0: timestamp = "14:30:25", group_timestamp = "14:30:25"
Chunk 1: timestamp = "14:30:26.5", group_timestamp = "14:30:25"
Chunk 2: timestamp = "14:30:28", group_timestamp = "14:30:25"
...
```

This provides more granular timing data while maintaining compatibility:
- For BirdNET-Pi-style queries: `GROUP BY group_timestamp, common_name`
- For precise timing: use `timestamp`

## Core Algorithm

The chunking algorithm (from `birdnet_service/birdnet_server.py`):

```python
def split_audio(path, chunk_length, sample_rate, total_duration, overlap=0.0, minlen=1.5):
    # Load and normalize audio to target duration
    sig, rate = librosa.load(path, sr=sample_rate, mono=True)

    # Calculate sizes in samples
    chunk_size = int(chunk_length * rate)      # 144,000 samples for 3s
    step_size = int((chunk_length - overlap) * rate)
    minlen_samples = int(minlen * rate)        # 72,000 samples for 1.5s

    chunks = []
    for i in range(0, len(sig), step_size):
        split = sig[i:i + chunk_size]

        # Discard if too short
        if len(split) < minlen_samples:
            break

        # Pad if between minlen and chunk_length
        if len(split) < chunk_size:
            padded = np.zeros(chunk_size, dtype=sig.dtype)
            padded[:len(split)] = split
            split = padded

        chunks.append(split)

    return chunks
```

This matches BirdNET-Pi's `splitSignal()` function behavior.

## Detection Count Impact

Higher overlap means more chunks analyzed, which results in more detections for continuous calls:

**Example: Robin calling continuously for 9 seconds**

| Overlap | Chunks | Robin Detections | Processing Cost |
|---------|--------|------------------|-----------------|
| 0.0     | 3      | 3                | 1x (baseline)   |
| 1.0     | 4      | 4                | 1.3x            |
| 1.5     | 6      | 6                | 2x              |
| 2.0     | 8      | 8                | 2.7x            |

This is expected behavior - users should understand that higher overlap increases both detection coverage and database size.

## Audio Extraction

When a detection occurs, surrounding audio is extracted for the saved clip:

1. **Spectrogram**: Always shows the exact 3-second detection window
2. **Audio clip**: Includes surrounding chunks for context (typically 6-9 seconds)

With overlap, the extraction correctly accounts for overlapping chunk positions:
```python
step_seconds = detection['step_seconds']  # chunk_length - overlap
start_time = chunk_index * step_seconds
end_time = chunk_index * step_seconds + chunk_length
```

## Recommendations

| Use Case | Recommended Overlap |
|----------|---------------------|
| Low-power devices (Pi Zero) | 0.0 (minimize CPU) |
| Standard detection | 0.0 - 1.0 |
| Improved accuracy | 1.5 |
| Maximum coverage | 2.0 |
| Research/analysis | 2.0 - 2.5 |

## References

- BirdNET-Pi source: `server.py` - `splitSignal()` function
- BirdNET-PiPy source: `birdnet_service/birdnet_server.py` - `split_audio()` function
- Tests: `tests/test_split_audio.py`
