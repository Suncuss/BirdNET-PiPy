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
| **Raspberry Pi** | Pi 5, Pi 4, Pi 3, or Zero 2W |
| **Storage** | 128GB+ SD card (V30) or NVMe SSD |
| **Microphone** | USB microphone |

All of these run the full system — the board mainly changes how responsive the dashboard feels:

| Board | What to expect |
|-------|----------------|
| **Pi 5, Pi 4** | Recommended. Responsive dashboard with headroom for several audio sources. |
| **Pi 3, Zero 2W** | Usable with a single microphone, but slow: pages can take several seconds on the first load after the station has been idle, and updates take considerably longer. Use a fast SD card and stay on the default BirdNET V2.4 model. |

On the smaller boards the installer adapts automatically — it adds a swap file, reclaims unused GPU memory on headless systems (`gpu_mem=16`), and builds images sequentially instead of in parallel.

> **Note:** the Pi 3 and Zero 2W tier is field-tested on the Zero 2W. The Pi 3 is expected to do at least as well — same quad-core processor, higher clock, and more memory — but we have not measured it directly.

**Not supported:** 32-bit-only boards (Pi 2 and earlier, the original Pi Zero and Zero W). BirdNET-PiPy ships arm64-only Python wheels, so the installer stops early on a 32-bit OS.

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

### Microphone Volume

To adjust your microphone gain, run the ALSA mixer from the terminal:

```bash
alsamixer
```

- Press **F6** to select your USB sound card
- Press **F4** to switch to the Capture view
- Use the **arrow keys** to adjust the volume
- Press **Esc** to exit

Changes take effect immediately — no restart required.

### Troubleshooting & Advanced Config

For detailed logs, advanced configuration, and architecture details, see the **[System Administration Guide](../deployment/README.md)**.

### Web Interface

Access the dashboard from any device on the same network:

**Using hostname (mDNS):**
```
http://<hostname>.local
```
For example, if your Pi's hostname is `raspberrypi`, use `http://raspberrypi.local`

**Using IP address:**
```
http://<ip-address>
```
Find your Pi's IP by running `hostname -I` on the Pi.

**From the Pi directly:**
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
