# Audio Architecture

Audio configuration for BirdNET-PiPy's PulseAudio and Icecast streaming setup.

## Architecture Overview

PulseAudio running on the host multiplexes microphone access between Docker containers:

```
USB Microphone
    ↓
PulseAudio Server (Host)
    ↓ (socket: /run/pulse/native)
    ├─► Main Container (FFmpeg → WAV → BirdNet)
    └─► Icecast Container (FFmpeg → MP3 → Browser)
```

## Files

- `icecast.xml` - Icecast server configuration (mounted into Docker container)
- `pulseaudio/system.pa` - System-wide PulseAudio configuration
- `pulseaudio/daemon.conf` - PulseAudio daemon settings

## Setup

PulseAudio is installed and configured automatically by `deployment/install-service.sh`.

The Icecast streaming container runs automatically as part of the Docker Compose stack.

## Testing

### Check PulseAudio
```bash
# Verify PulseAudio is running
pulseaudio --check && echo "Running" || echo "Not running"

# List audio sources
pactl list sources short

# Test recording
parecord --channels=1 --rate=48000 test.wav
```

### Check Icecast Stream
```bash
# Check Icecast status
curl http://localhost:8888/status-json.xsl

# Test audio stream
curl http://localhost:8888/stream.mp3 --max-time 3 -o test.mp3

# Access from frontend
http://localhost:8080 → Settings → View live stream
```

## Configuration

### Change Stream Bitrate

Set environment variable before starting containers:
```bash
export STREAM_BITRATE=192k  # Default is 128k
docker compose up -d
```

### Change Icecast Passwords

Edit `deployment/audio/icecast.xml`:
```xml
<authentication>
    <source-password>your_new_password</source-password>
    <admin-password>your_admin_password</admin-password>
</authentication>
```

Then set the environment variable to match:
```bash
export ICECAST_PASSWORD=your_new_password
docker compose restart icecast
```

## Troubleshooting

### No audio detected
```bash
# List audio devices
arecord -l

# Check USB microphone
lsusb | grep -i audio
```

### Stream not working
```bash
# Check Icecast container
docker logs icecast

# Verify PulseAudio socket
ls -la /run/user/$(id -u)/pulse/native
```

### Icecast Web Interface

- **Status page**: http://localhost:8888/status.xsl
- **Admin panel**: http://localhost:8888/admin/ (user: `admin`, password: `hackme`)

## Security Notes

⚠️ **Change default passwords in production**

Default credentials:
- Source password: `hackme`
- Admin password: `hackme`
