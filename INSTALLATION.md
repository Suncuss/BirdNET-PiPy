# BirdNET-PiPy Installation Guide

Complete installation guide for BirdNET-PiPy on Raspberry Pi and Linux systems.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Install](#quick-install)
- [Manual Install](#manual-install)
- [Installation Options](#installation-options)
- [Post-Installation Setup](#post-installation-setup)
- [Troubleshooting](#troubleshooting)
- [Uninstallation](#uninstallation)
- [Advanced Topics](#advanced-topics)

## Prerequisites

### Hardware Requirements

- **Raspberry Pi**: 3B+ or newer (Raspberry Pi 4 recommended)
  - Or any x86_64/ARM64 Linux computer
- **RAM**: Minimum 1GB (2GB+ recommended)
- **Storage**: 8GB+ SD card or storage device
- **USB Microphone**: For audio input
- **Network**: Internet connection for installation

### Software Requirements

- **Operating System**:
  - Raspberry Pi OS (Bullseye or newer)
  - Ubuntu 20.04+ or Debian 11+
  - Other Debian-based distributions
- **User Access**: sudo privileges required

### What Gets Installed

The installer automatically sets up:
- Docker CE (Community Edition)
- Docker Compose plugin
- PulseAudio (system-wide mode)
- BirdNET-PiPy application (all containers)
- Systemd service for auto-start

## Quick Install

The fastest way to install BirdNET-PiPy is using the curl command:

```bash
curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash
```

This single command will:

1. Clone the repository to `/opt/BirdNET-PiPy` (or `~/BirdNET-PiPy` if not root)
2. Install Docker and Docker Compose if needed
3. Configure PulseAudio for audio sharing
4. Build all Docker images
5. Set up systemd service
6. Enable auto-start on boot

**Installation time**: 10-20 minutes depending on your hardware and internet speed.

### After Installation

Start the service:

```bash
sudo systemctl start birdnet-pipy
```

Access the web interface at: **http://localhost:8080**

## Manual Install

If you prefer to review the code before running, follow these steps:

### Step 1: Clone the Repository

```bash
# Clone to your home directory
git clone https://github.com/Suncuss/BirdNET-PiPy.git
cd BirdNET-PiPy
```

### Step 2: Review the Installation Script

```bash
# Review the installer
less install.sh

# Check what it does
sudo ./install.sh --help
```

### Step 3: Run the Installer

```bash
sudo ./install.sh
```

The installer will guide you through the process with status messages.

## Installation Options

The installer supports several command-line options for customization:

```bash
sudo ./install.sh [OPTIONS]
```

### Available Options

| Option | Description |
|--------|-------------|
| `--install-dir DIR` | Custom installation directory (default: `/opt/BirdNET-PiPy`) |
| `--no-docker` | Skip Docker installation (assumes already installed) |
| `--no-pulseaudio` | Skip PulseAudio setup |
| `--no-service` | Skip systemd service installation |
| `--test` | Run tests before building images |
| `--help` | Show help message |

### Examples

**Custom installation directory:**
```bash
sudo ./install.sh --install-dir /home/pi/BirdNET
```

**Skip Docker install (if already installed):**
```bash
sudo ./install.sh --no-docker
```

**Run tests before building:**
```bash
sudo ./install.sh --test
```

**Development install (no service):**
```bash
sudo ./install.sh --no-service
```

## Post-Installation Setup

### 1. Verify Installation

Check that the service is installed:

```bash
sudo systemctl status birdnet-pipy
```

You should see `enabled` but not yet `active (running)`.

### 2. Configure USB Microphone

Plug in your USB microphone and verify it's detected:

```bash
# List audio input devices
arecord -l

# Expected output:
# card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
```

### 3. Start the Service

```bash
sudo systemctl start birdnet-pipy
```

Wait 30-60 seconds for all containers to start, then check status:

```bash
sudo systemctl status birdnet-pipy
```

### 4. Verify Audio is Working

Check PulseAudio sources:

```bash
pactl list sources short
```

You should see your USB microphone listed.

### 5. Access the Web Interface

Open a web browser and navigate to:

```
http://localhost:8080
```

Or from another computer on your network:

```
http://<raspberry-pi-ip>:8080
```

### 6. Test Audio Streaming

The live audio stream is available at:

```
http://localhost:8888/stream.mp3
```

You can play this in any media player or browser.

## Troubleshooting

### Docker Installation Issues

**Problem**: Docker installation fails

**Solutions**:
- Ensure you have a stable internet connection
- Check that your distribution is supported: `cat /etc/os-release`
- Update package lists: `sudo apt-get update`
- Check available disk space: `df -h`

**Problem**: Permission denied when running docker

**Solution**:
```bash
# Add your user to docker group
sudo usermod -aG docker $USER

# Log out and back in, or run:
newgrp docker
```

### PulseAudio Issues

**Problem**: Audio not detected

**Solutions**:
```bash
# Check if PulseAudio is running
pulseaudio --check && echo "Running" || echo "Not running"

# Restart PulseAudio
pulseaudio --kill
pulseaudio --start --daemonize

# Check microphone is detected
arecord -l
```

**Problem**: PulseAudio socket not found

**Solution**:
```bash
# Check socket location
ls -la /run/pulse/native
ls -la /run/user/$(id -u)/pulse/native

# Restart the service
sudo systemctl restart birdnet-pipy
```

### Service Issues

**Problem**: Service won't start

**Solutions**:
```bash
# Check logs
sudo journalctl -u birdnet-pipy -f

# Check Docker is running
systemctl status docker

# Check if containers are running
docker ps

# Verify Docker images are built
docker images | grep birdnet-pipy
```

**Problem**: Service starts but containers crash

**Solutions**:
```bash
# Check container logs
docker compose -f /opt/BirdNET-PiPy/docker-compose.yml logs

# Check disk space
df -h

# Rebuild images
cd /opt/BirdNET-PiPy
sudo docker compose build --no-cache
```

### Frontend Not Accessible

**Problem**: Cannot access http://localhost:8080

**Solutions**:
```bash
# Check if frontend container is running
docker ps | grep frontend

# Check port is listening
sudo netstat -tlnp | grep 8080

# Check firewall
sudo ufw status
```

### Audio Detection Not Working

**Problem**: No bird detections showing up

**Solutions**:
```bash
# Check if audio is being recorded
pactl list sources short

# Check main container logs
docker logs birdnet-pipy-main-1 --tail 100

# Verify settings
cat /opt/BirdNET-PiPy/data/config/user_settings.json
```

### General Debug Steps

1. **Check service status**:
   ```bash
   sudo systemctl status birdnet-pipy
   ```

2. **View live logs**:
   ```bash
   sudo journalctl -u birdnet-pipy -f
   ```

3. **Check all containers**:
   ```bash
   docker ps -a
   ```

4. **Restart everything**:
   ```bash
   sudo systemctl restart birdnet-pipy
   ```

5. **Check disk space**:
   ```bash
   df -h
   ```

## Uninstallation

To completely remove BirdNET-PiPy:

### 1. Stop and Disable Service

```bash
sudo systemctl stop birdnet-pipy
sudo systemctl disable birdnet-pipy
```

### 2. Remove Service File

```bash
sudo rm /etc/systemd/system/birdnet-pipy.service
sudo systemctl daemon-reload
```

### 3. Remove Docker Containers and Images

```bash
cd /opt/BirdNET-PiPy  # Or your installation directory
docker compose down
docker rmi $(docker images | grep birdnet-pipy | awk '{print $3}')
```

### 4. Remove Application Files

```bash
# Be careful with this command!
sudo rm -rf /opt/BirdNET-PiPy
```

### 5. Remove PulseAudio Configuration (Optional)

```bash
# Restore backups if they exist
sudo mv /etc/pulse/system.pa.backup /etc/pulse/system.pa
sudo mv /etc/pulse/daemon.conf.backup /etc/pulse/daemon.conf

# Restart PulseAudio
pulseaudio --kill
pulseaudio --start
```

### 6. Remove Docker (Optional)

Only do this if you don't need Docker for other applications:

```bash
sudo apt-get remove -y docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
sudo apt-get autoremove -y
```

## Advanced Topics

### Custom Docker Compose Configuration

If you need to modify the Docker Compose setup:

```bash
cd /opt/BirdNET-PiPy
nano docker-compose.yml
# Make your changes

# Rebuild and restart
sudo docker compose down
sudo docker compose build
sudo docker compose up -d
```

### Custom PulseAudio Configuration

PulseAudio configuration files are located at:
- `/etc/pulse/system.pa` - Module configuration
- `/etc/pulse/daemon.conf` - Daemon settings

After modifications, restart PulseAudio:

```bash
pulseaudio --kill
pulseaudio --start --daemonize
```

### Running Without Systemd

You can run the service directly without systemd:

```bash
cd /opt/BirdNET-PiPy
./deployment/birdnet-service.sh
```

Press Ctrl+C to stop.

### Development Mode

For development with hot-reload:

```bash
# Frontend (port 5173)
cd frontend/
npm install
npm run dev

# Backend containers
docker compose up -d
```

### Updating BirdNET-PiPy

To update to the latest version:

```bash
cd /opt/BirdNET-PiPy
git pull origin main
sudo docker compose build
sudo systemctl restart birdnet-pipy
```

Or use the update flag (triggers automatic update):

```bash
touch /opt/BirdNET-PiPy/data/flags/update-requested
```

### Network Access from Other Devices

To access BirdNET-PiPy from other devices on your network:

1. Find your Raspberry Pi's IP address:
   ```bash
   hostname -I
   ```

2. Access from other devices using:
   ```
   http://<raspberry-pi-ip>:8080
   ```

3. If you have a firewall, open the required ports:
   ```bash
   sudo ufw allow 8080/tcp
   sudo ufw allow 8888/tcp
   ```

### Monitoring Resource Usage

```bash
# System resources
htop

# Docker container resources
docker stats

# Disk usage
du -sh /opt/BirdNET-PiPy/*
```

### Backup and Restore

**Backup database and audio files**:

```bash
# Create backup directory
mkdir -p ~/birdnet-backup

# Backup data directory
sudo cp -r /opt/BirdNET-PiPy/data ~/birdnet-backup/

# Optional: Create tarball
cd ~/birdnet-backup
tar -czf birdnet-data-$(date +%Y%m%d).tar.gz data/
```

**Restore**:

```bash
# Stop service
sudo systemctl stop birdnet-pipy

# Restore data
sudo cp -r ~/birdnet-backup/data /opt/BirdNET-PiPy/

# Fix permissions
sudo chown -R $USER:$USER /opt/BirdNET-PiPy/data

# Start service
sudo systemctl start birdnet-pipy
```

## Getting Help

If you encounter issues not covered in this guide:

1. Check the [GitHub Issues](https://github.com/Suncuss/BirdNET-PiPy/issues)
2. Review the [CLAUDE.md](CLAUDE.md) technical documentation
3. Open a new issue with:
   - Your platform details (`uname -a`)
   - Installation method used
   - Error messages from `sudo journalctl -u birdnet-pipy -n 100`
   - Output of `docker ps -a`

## Security Considerations

### Script Review

Before running the curl installation, you can review the script:

```bash
curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh > install.sh
less install.sh
sudo bash install.sh
```

### Network Security

The application listens on localhost by default. To expose it to your network:

1. Ensure your Raspberry Pi is behind a firewall
2. Don't expose ports directly to the internet
3. Use a VPN if accessing remotely
4. Consider setting up HTTPS with a reverse proxy (nginx)

### Data Privacy

- Audio recordings are stored locally in `/opt/BirdNET-PiPy/data/audio/`
- Database is local: `/opt/BirdNET-PiPy/data/birdnet.db`
- No data is sent to external services (except BirdNET model inference is local)

## Next Steps

After successful installation:

1. Configure detection sensitivity in the web UI Settings
2. Set up audio recording mode (PulseAudio or HTTP stream)
3. Explore the detection history and spectrograms
4. Set up automated backups of your data directory
5. Consider setting up external access via VPN or reverse proxy

Enjoy your BirdNET-PiPy installation!
