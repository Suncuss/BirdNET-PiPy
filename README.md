# BirdNET-PiPy

BirdNET-PiPy is a Python-based bird detection system based on the BirdNET model. It's a full-stack application with Vue.js frontend and Python Flask microservices backend, designed for Raspberry Pi deployment.

## Quick Install

Run this single command on your Raspberry Pi or Linux system:

```bash
curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash
```

This will automatically:
- Install Docker and Docker Compose (if needed)
- Clone the repository
- Configure PulseAudio for audio sharing
- Build all Docker images
- Set up systemd service for auto-start on boot

After installation, start the service:

```bash
sudo systemctl start birdnet-pipy
```

Access the web interface at **http://localhost:8080**


## Features

- Real-time bird sound detection using BirdNET model
- Web-based frontend for viewing detections and spectrograms
- Live audio streaming to browser
- Docker-based deployment for easy setup


## Prerequisites

- Raspberry Pi (3B+ or newer) or compatible Linux system
- Raspberry Pi OS, Ubuntu, or Debian-based distribution
- USB microphone for audio input

## Service Management

After installation, manage the service with these commands:

```bash
# Check status
sudo systemctl status birdnet-pipy

# Stop/start/restart service
sudo systemctl stop birdnet-pipy
sudo systemctl start birdnet-pipy
sudo systemctl restart birdnet-pipy

# Disable auto-start on boot
sudo systemctl disable birdnet-pipy
```

## Audio Configuration

The system uses PulseAudio for audio multiplexing, allowing the microphone to be shared between:
- BirdNET analysis pipeline
- Live audio streaming to browsers

Check audio services:

```bash
# Check if PulseAudio is running
pulseaudio --check && echo "Running" || echo "Not running"

# List available audio sources
pactl list sources short
```

## Architecture

**Microservices Backend:**
- BirdNet Server - TensorFlow Lite model inference
- API Server - REST API and static file serving
- Main Processing - Continuous audio recording and analysis
- Icecast Streaming  - Live audio to browsers

**Frontend:**
- Vue.js 3 SPA with Composition API
- Real-time WebSocket updates
- Interactive spectrograms with WaveSurfer.js
- Detection charts with Chart.js

**Data Flow:**
```
USB Mic → PulseAudio → Docker Containers → AI Analysis → Database → Web UI
```

## License

BirdNET-PiPy is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License** (CC BY-NC-SA 4.0).

This license is compatible with and derived from the upstream projects:
- **BirdNET-Lite** - K. Lisa Yang Center for Conservation Bioacoustics, Cornell Lab of Ornithology
- **BirdNET-Pi** - Patrick McGuire

See [LICENSE](LICENSE) file for full details. In summary, you may use and modify this software freely for non-commercial purposes, provided you:
- Give credit to the original authors
- Share any modifications under the same license

## Credits

This project is built upon:

- **[BirdNET-Lite](https://birdnet.cornell.edu/)** - AI model from K. Lisa Yang Center for Conservation Bioacoustics, Cornell Lab of Ornithology, Cornell University
- **[BirdNET-Pi](https://github.com/mcguirepr89/BirdNET-Pi)** - Original Raspberry Pi implementation by Patrick McGuire

BirdNET-PiPy extends these projects with a modern Vue.js frontend, containerized architecture, and enhanced user interface.
