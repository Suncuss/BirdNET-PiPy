# BirdNET-PiPy Installation Guide

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Install](#quick-install)
- [Post-Installation](#post-installation)
- [Uninstallation](#uninstallation)

---

## Prerequisites

### Hardware

| Component | Requirement |
|-----------|-------------|
| **Raspberry Pi** | Model 4 or newer (Pi 5 recommended), 2GB+ RAM |
| **Storage** | 128GB+ SD card (V30) or NVMe SSD |
| **Microphone** | USB microphone |

### Software

- **OS:** Raspberry Pi OS or Raspberry Pi OS Lite (64-bit, Bookworm+)

### Installed Components

The installer automatically sets up:

- Git
- PulseAudio (system-wide on Lite)
- Docker
- BirdNET-PiPy containers
- Systemd service for auto-start

---

## Quick Install

Run this command to install BirdNET-PiPy:

```bash
curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash
```

> **Installation time:** 10–30 minutes depending on hardware and network speed.

### Review Script First

```bash
curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh > install.sh
less install.sh
sudo bash install.sh
```

---

## Post-Installation

The system reboots automatically after installation.

### Verify Installation

Check that the service is running:

```bash
sudo systemctl status birdnet-pipy
```

You should see `active (running)` in the output.

View system service logs:

```bash
journalctl -u birdnet-pipy -f
```

### Troubleshooting & Advanced Config

For detailed logs, advanced configuration, and architecture details, see the **[System Administration Guide](deployment/README.md)**.

### Web Interface

Open your browser and navigate to:

```
http://<raspberry-pi-ip>
```

Or from the Pi directly:

```
http://localhost
```

---

## Uninstallation

To remove BirdNET-PiPy:

```bash
cd ~/BirdNET-PiPy
./uninstall.sh
```

---

**Enjoy BirdNET-PiPy!**
