# Storage Auto-Cleanup

Automatic storage management for BirdNET-PiPy that prevents disk space from filling up by cleaning old detection files.

## Overview

BirdNET-PiPy continuously generates audio recordings and spectrogram images for each bird detection. Over time, this can consume significant disk space. The storage cleanup feature automatically removes old files when disk usage exceeds a threshold, while preserving database records and keeping the best recordings for each species.

## How It Works

1. **Monitoring**: A background thread checks disk usage every 30 minutes
2. **Trigger**: When usage exceeds 85%, cleanup begins
3. **Target**: Frees space until usage drops to 80%
4. **Protection**: For EVERY species, the top 60 recordings by confidence are always kept
5. **Preservation**: Database records are kept; only audio and spectrogram files are deleted
6. **Safety**: If disk is full with non-BirdNET data, cleanup stops when BirdNET candidates are exhausted (won't delete everything trying to reach an impossible target)

### Cleanup Algorithm

```
1. Calculate bytes needed to free (current_used - target_used)
2. For each species, identify recordings beyond top 60 by confidence
3. Get these "beyond top 60" detections, ordered by timestamp (oldest first)
4. SAFETY CHECK: Estimate if target is achievable with available data
5. Accumulate file sizes until target bytes reached
6. Delete audio (.mp3) and spectrogram (.webp) files
7. Database records remain intact
8. Stop when target reached OR candidates exhausted (whichever first)
```

### What Gets Deleted

| Item | Deleted? |
|------|----------|
| Audio files (.mp3) beyond top 60/species | Yes |
| Spectrogram images (.webp) beyond top 60/species | Yes |
| Top 60 recordings per species (by confidence) | No |
| Database records | No |

## Configuration

Storage settings can be configured in `data/config/user_settings.json`:

```json
{
  "storage": {
    "auto_cleanup_enabled": true,
    "trigger_percent": 85,
    "target_percent": 80,
    "keep_per_species": 60,
    "check_interval_minutes": 30
  }
}
```

### Settings Explained

| Setting | Default | Description |
|---------|---------|-------------|
| `auto_cleanup_enabled` | `true` | Enable/disable automatic cleanup |
| `trigger_percent` | `85` | Start cleanup when disk usage exceeds this percentage |
| `target_percent` | `80` | Free space until usage drops to this percentage |
| `keep_per_species` | `60` | Keep top N recordings per species by confidence |
| `check_interval_minutes` | `30` | How often to check disk usage |

## Per-Species Protection

For EVERY species, the top N recordings by confidence are always protected (`keep_per_species`, default: 60). This ensures your best recordings are never deleted.

**Example**: If you have:
- American Robin: 500 detections → keeps top 60 by confidence, 440 eligible for cleanup
- Bald Eagle: 4 detections → all 4 kept (fewer than 60)

## Storage Locations

Files are stored in the `data/` directory:

```
data/
├── audio/
│   └── extracted_songs/    # Detection audio clips (~270 KB each)
├── spectrograms/           # Spectrogram images (~30 KB each)
└── db/
    └── birds.db            # Database (preserved)
```

## Logging

Cleanup activity is logged to the main application log:

```
Storage monitor started (auto_cleanup_enabled=True, trigger_percent=80, ...)
Disk usage check (percent_used=75.3, trigger_percent=80)
Disk usage exceeded threshold, starting cleanup (percent_used=82.1)
Starting storage cleanup (bytes_to_free_gb=12.5)
Storage cleanup completed (files_deleted=1523, bytes_freed_gb=12.8)
```

## Disabling Auto-Cleanup

To disable automatic cleanup:

1. Edit `data/config/user_settings.json`
2. Set `"auto_cleanup_enabled": false`
3. Restart the service

```json
{
  "storage": {
    "auto_cleanup_enabled": false
  }
}
```

## Manual Cleanup

Currently, cleanup runs automatically based on disk usage thresholds. Manual cleanup via API is not yet implemented.

## Impact on UI

After cleanup, affected detections will show:
- Database record: Still visible in detection lists
- Audio player: "File not found" or silent
- Spectrogram: Placeholder or missing image

## Best Practices

1. **Set appropriate thresholds**: Adjust `trigger_percent` based on your disk size
2. **Monitor rare species**: Check `min_recordings_per_species` covers your rare sightings
3. **Regular backups**: Export important data before relying on cleanup
4. **Review logs**: Check cleanup logs periodically to understand deletion patterns

## Troubleshooting

### Cleanup Not Running
- Check `auto_cleanup_enabled` is `true`
- Verify disk usage exceeds `trigger_percent`
- Check application logs for errors

### Too Many Files Deleted
- Increase `min_recordings_per_species` to protect more species
- Decrease `trigger_percent` to start cleanup earlier (more gradual)
- Increase `target_percent` to delete less per cleanup cycle

### Protected Species Still Losing Files
- Verify the species has fewer than `min_recordings_per_species` detections
- Check database to confirm actual count

## Technical Details

### Files Modified
- `backend/core/storage_manager.py` - Core cleanup logic
- `backend/core/db.py` - Database queries for species counts and candidates
- `backend/core/main.py` - Background thread integration
- `backend/config/settings.py` - Default configuration

### Thread Safety
The storage monitor runs in a dedicated background thread and uses the shared `stop_flag` for graceful shutdown. Database operations use connection pooling with proper isolation.

### Resource Usage
- CPU: Minimal (periodic disk check)
- Memory: Low (streams candidates, doesn't load all at once)
- I/O: Burst during cleanup, minimal otherwise
