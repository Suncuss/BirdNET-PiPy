# System Administration & Architecture

This document details the internal architecture, service management, and advanced configuration of BirdNET-PiPy.

## Directory Structure

### Runtime Control (`deployment/`)
- **`birdnet-service.sh`**: The master orchestration script. managed by systemd. It handles:
  - Docker container lifecycle
  - Audio backend detection and startup (PulseAudio vs PipeWire)
  - Auto-updates via git

### Audio Configuration (`deployment/audio/`)
- Includes PulseAudio configs (`system.pa`, `daemon.conf`) for running in system-wide mode on RPi OS Lite.
- Icecast streaming server configuration.

---

For audio architecture details, see **[Audio Architecture](../README.md#audio-architecture)** in the main README.

---

## Service Management

The system runs as a standard systemd service named `birdnet-pipy`.

### Basic Controls

```bash
sudo systemctl start birdnet-pipy    # Start
sudo systemctl stop birdnet-pipy     # Stop
sudo systemctl restart birdnet-pipy  # Restart
sudo systemctl status birdnet-pipy   # Check Status
```

### Viewing Logs

**Service Controller Logs** (Wrapper script output):
```bash
journalctl -u birdnet-pipy -f
```

**Application Logs** (Inner container output):
```bash
cd ~/BirdNET-PiPy
docker compose logs -f [container_name]
# containers: main, api, birdnet-server, frontend, icecast
```

---

## Maintenance Triggers

You can trigger maintenance tasks by touching flag files, avoiding full reboots.

| Trigger File | Action | Description |
|--------------|--------|-------------|
| `data/flags/restart-backend` | **Restart** | Restarts all Docker containers. Useful after config changes. |
| `data/flags/update-requested` | **Update** | Runs `install.sh --update` which syncs code, rebuilds images, and updates system configs. |

**Example:**
```bash
# Trigger an update (content is the target branch)
echo "main" > ~/BirdNET-PiPy/data/flags/update-requested
```

### Update Channels

BirdNET-PiPy supports two update channels, configurable in Settings:

| Channel | Branch | Description |
|---------|--------|-------------|
| **Release** | `main` | Stable releases (default) |
| **Latest** | `staging` | Newest features, may be less stable |

When you trigger an update, the system checks for updates from the configured channel's branch.

### Update Flow Details

When an update is triggered, `install.sh --update` performs:
1. Stops Docker containers
2. Fetches and syncs to the target branch (git fetch + checkout + reset)
3. Rebuilds Docker images
4. Updates system configs (PulseAudio, systemd service, sudoers)
5. Exits for systemd to restart the service

**Manual update (current branch):**
```bash
cd ~/BirdNET-PiPy && sudo ./install.sh --update
```

**Manual update (specific branch):**
```bash
cd ~/BirdNET-PiPy && sudo ./install.sh --update --branch staging
```

**Note:** For existing installations before this feature was added, run `sudo ./install.sh` once to update the sudoers configuration for automatic updates.

---

## Troubleshooting

### Quick Diagnostic Flow

```bash
# 1. Are all containers running?
docker ps

# 2. Is the audio socket available?
ls -la /run/pulse/native

# 3. Check container logs for errors
docker logs main        # Audio recording & BirdNET analysis
docker logs icecast     # Live audio streaming
docker logs api         # REST API
```

### No Audio Being Recorded

```bash
# Verify PulseAudio is running on host
pactl info

# List available audio sources
pactl list sources short
```

### Live Stream Not Working

```bash
# Check if Icecast is receiving audio
curl -s http://localhost:8888/status-json.xsl | grep -o '"listeners":[0-9]*'

# Test stream directly
curl http://localhost:8888/stream.mp3 --max-time 3 -o /dev/null && echo "Stream OK"
```

**Icecast Web Interface:** http://localhost:8888/status.xsl

---

## Icecast Configuration

### Change Stream Bitrate

Set environment variable before starting containers:
```bash
export STREAM_BITRATE=192k  # Default is 128k
docker compose up -d
```

### Change Icecast Passwords

By default, a **random 16-character password** is generated each time the Icecast container starts. This is secure but means the password changes on restart.

To set a **persistent password**, set the environment variable:
```bash
export ICECAST_PASSWORD=your_secure_password
docker compose up -d
```

**Note:** The static `deployment/audio/icecast.xml` file is **not used** at runtime. The startup script generates a secure config dynamically.
