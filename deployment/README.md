# Deployment Scripts

This directory contains deployment and runtime management scripts for BirdNET-PiPy.

## Current Installation Method

**⚠️ IMPORTANT: The installation process has been simplified!**

Use the unified installer from repository root:

### Quick Install (Recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash
```

### Manual Install

```bash
git clone https://github.com/Suncuss/BirdNET-PiPy.git
cd BirdNET-PiPy
sudo ./install.sh
```

For detailed installation instructions, see [INSTALLATION.md](../INSTALLATION.md).

## Directory Contents

### Installation Scripts

- **`install-service.sh`** - Legacy wrapper (deprecated)
  - Now redirects to root `install.sh` for backwards compatibility
  - **For new installations, use `../install.sh` instead**

### Runtime Scripts

- **`birdnet-service.sh`** - Service management script
  - Called by systemd to manage Docker containers
  - Handles PulseAudio startup
  - Monitors restart and update flags
  - Manages graceful shutdown

### Systemd Service

- **`birdnet-pipy.service`** - Systemd service template
  - Installed to `/etc/systemd/system/birdnet-pipy.service` during installation
  - Enables auto-start on boot
  - Manages the `birdnet-service.sh` runtime script

### Audio Configuration

- **`audio/`** - Audio infrastructure
  - `Dockerfile` - Icecast streaming container
  - `icecast.xml` - Icecast server configuration
  - `pulseaudio/system.pa` - PulseAudio module configuration
  - `pulseaudio/daemon.conf` - PulseAudio daemon settings
  - `scripts/start-icecast.sh` - Icecast container entrypoint

## Legacy Scripts (Deprecated)

The following installation workflow is now deprecated:

```bash
# OLD METHOD (still works but not recommended)
cd BirdNET-PiPy
sudo ./deployment/install-service.sh
```

This will show a deprecation notice and redirect to the unified installer.

## Installation Options

The unified installer supports several options:

```bash
sudo ./install.sh --help
```

Available options:
- `--install-dir DIR` - Custom installation directory
- `--no-docker` - Skip Docker installation
- `--no-pulseaudio` - Skip PulseAudio setup
- `--no-service` - Skip systemd service installation
- `--test` - Run tests before building

## Service Management

After installation, manage the service with:

```bash
# Start service
sudo systemctl start birdnet-pipy

# Stop service
sudo systemctl stop birdnet-pipy

# Restart service
sudo systemctl restart birdnet-pipy

# View status
sudo systemctl status birdnet-pipy

# View logs
sudo journalctl -u birdnet-pipy -f

# Enable/disable auto-start
sudo systemctl enable birdnet-pipy
sudo systemctl disable birdnet-pipy
```

## Trigger Mechanisms

The runtime script (`birdnet-service.sh`) monitors flag files for special operations:

### Container Restart

Trigger container restart without rebooting:

```bash
touch ../data/flags/restart-backend
```

The service monitors this flag and automatically restarts Docker containers.

### System Update

Trigger automatic update from GitHub:

```bash
touch ../data/flags/update-requested
```

The service will:
1. Fetch latest code from origin/main
2. Stop containers
3. Pull new code
4. Rebuild images
5. Restart with new version

## Audio Architecture

```
USB Microphone
    ↓
PulseAudio Server (Host)
    ↓ (socket: /run/pulse/native)
    ├─► Main Container (FFmpeg → WAV → BirdNet AI)
    └─► Icecast Container (FFmpeg → MP3 → Browser)
```

### PulseAudio Configuration

The system uses PulseAudio in system-wide mode to share audio between:
- BirdNET analysis pipeline (continuous recording)
- Live audio streaming to browsers (Icecast)

Configuration files:
- `/etc/pulse/system.pa` - Module loading and source configuration
- `/etc/pulse/daemon.conf` - Daemon settings (sample rate, format, etc.)

These are copied from `audio/pulseaudio/` during installation.

## Container Architecture

The system runs 5 Docker containers:

1. **birdnet-server** (port 5001) - TensorFlow Lite model inference
2. **api** (port 5002) - REST API and static file serving
3. **main** - Continuous audio recording and analysis
4. **icecast** (port 8888) - Live audio streaming
5. **frontend** (port 8080) - Vue.js web interface

All containers share:
- `/app/data` - Database and audio files
- `/run/pulse` - PulseAudio socket (main and icecast only)
- `TZ` - Timezone environment variable

## Troubleshooting

### Service Won't Start

```bash
# Check logs
sudo journalctl -u birdnet-pipy -f

# Check Docker is running
systemctl status docker

# Verify containers
docker ps -a
```

### Audio Issues

```bash
# Check PulseAudio
pulseaudio --check && echo "Running"

# List audio sources
pactl list sources short

# Restart PulseAudio
pulseaudio --kill
pulseaudio --start --daemonize
```

### Container Issues

```bash
# View container logs
docker compose logs -f

# Rebuild containers
cd /opt/BirdNET-PiPy  # or your install dir
sudo docker compose build --no-cache
sudo docker compose up -d
```

## Development Notes

For development and testing:

```bash
# Run service script directly (no systemd)
./birdnet-service.sh

# Stop with Ctrl+C
```

This is useful for debugging as you can see all output directly.

## Documentation

- **[../README.md](../README.md)** - Project overview and quick start
- **[../INSTALLATION.md](../INSTALLATION.md)** - Complete installation guide
- **[../CLAUDE.md](../CLAUDE.md)** - Development documentation
- **[../docs/](../docs/)** - Additional technical documentation

## Migration from Legacy Install

If you previously used `deployment/install-service.sh`, no changes are needed. The wrapper will redirect to the new unified installer automatically.

For complete reinstall using the new method:

1. Stop and remove old installation:
   ```bash
   sudo systemctl stop birdnet-pipy
   sudo systemctl disable birdnet-pipy
   sudo rm /etc/systemd/system/birdnet-pipy.service
   ```

2. Backup your data:
   ```bash
   cp -r data ~/birdnet-backup
   ```

3. Run new installer:
   ```bash
   cd ..
   sudo ./install.sh
   ```

4. Restore data:
   ```bash
   cp -r ~/birdnet-backup/* data/
   ```

## Getting Help

For issues or questions:

1. Check the [Installation Guide](../INSTALLATION.md)
2. View the [GitHub Issues](https://github.com/Suncuss/BirdNET-PiPy/issues)
3. Open a new issue with logs and system details
