# Storage Auto-Cleanup

Automatic storage management for BirdNET-PiPy that prevents disk space from filling up by cleaning old detection files.

## Overview

BirdNET-PiPy continuously generates audio recordings and spectrogram images for each bird detection. Over time, this can consume significant disk space. The storage cleanup feature automatically removes old files when disk usage exceeds a threshold, while preserving database records and protecting rare species.

## How It Works

1. **Monitoring**: A background thread checks disk usage every 30 minutes
2. **Trigger**: When usage exceeds 80%, cleanup begins
3. **Target**: Frees space until usage drops to 70%
4. **Protection**: Species with ≤60 recordings are never touched
5. **Preservation**: Database records are kept; only audio and spectrogram files are deleted

### Cleanup Algorithm

```
1. Calculate bytes needed to free (current_used - target_used)
2. Identify protected species (those with ≤60 recordings)
3. Get all detections from non-protected species, ordered by timestamp (oldest first)
4. Accumulate file sizes until target bytes reached
5. Delete audio (.mp3) and spectrogram (.webp) files
6. Database records remain intact
```

### What Gets Deleted

| Item | Deleted? |
|------|----------|
| Audio files (.mp3) | Yes |
| Spectrogram images (.webp) | Yes |
| Database records | No |
| Protected species files | No |

## Configuration

Storage settings can be configured in `data/config/user_settings.json`:

```json
{
  "storage": {
    "auto_cleanup_enabled": true,
    "trigger_percent": 80,
    "target_percent": 70,
    "min_recordings_per_species": 60,
    "check_interval_minutes": 30
  }
}
```

### Settings Explained

| Setting | Default | Description |
|---------|---------|-------------|
| `auto_cleanup_enabled` | `true` | Enable/disable automatic cleanup |
| `trigger_percent` | `80` | Start cleanup when disk usage exceeds this percentage |
| `target_percent` | `70` | Free space until usage drops to this percentage |
| `min_recordings_per_species` | `60` | Protect species with fewer than this many recordings |
| `check_interval_minutes` | `30` | How often to check disk usage |

## Protected Species

Species with fewer recordings than `min_recordings_per_species` (default: 60) are automatically protected. This ensures rare sightings are preserved.

**Example**: If you have:
- American Robin: 500 detections → eligible for cleanup
- Bald Eagle: 4 detections → protected (all files kept)

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
