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

## Manual Install

If you prefer to review the code first:

```bash
git clone https://github.com/Suncuss/BirdNET-PiPy.git
cd BirdNET-PiPy
sudo ./install.sh
```

## Features

- Real-time bird sound detection using BirdNET AI model
- Web-based frontend for viewing detections and spectrograms
- Live audio streaming to browser
- SQLite database for detection history
- REST API for integration
- Docker-based deployment for easy setup
- Systemd service for auto-start on boot

## Prerequisites

- Raspberry Pi (3B+ or newer) or compatible Linux system
- Raspberry Pi OS, Ubuntu, or Debian-based distribution
- USB microphone for audio input
- Internet connection for installation

## Service Management

After installation, manage the service with these commands:

```bash
# Check status
sudo systemctl status birdnet-pipy

# View live logs
sudo journalctl -u birdnet-pipy -f

# Stop/start/restart service
sudo systemctl stop birdnet-pipy
sudo systemctl start birdnet-pipy
sudo systemctl restart birdnet-pipy

# Disable auto-start on boot
sudo systemctl disable birdnet-pipy
```

## Application Endpoints

- **Frontend**: http://localhost:8080
- **API Server**: http://localhost:5002
- **BirdNet Service**: http://localhost:5001
- **Live Audio Stream**: http://localhost:8888/stream.mp3

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

## Advanced Configuration

### Trigger Container Restart

You can restart containers without rebooting:

```bash
touch data/flags/restart-backend
```

The service monitors this flag and automatically restarts containers.

### Installation Options

The installer supports several options:

```bash
sudo ./install.sh --help
```

Options:
- `--install-dir DIR` - Custom installation directory
- `--no-docker` - Skip Docker installation (if already installed)
- `--no-pulseaudio` - Skip PulseAudio setup
- `--no-service` - Skip systemd service installation
- `--test` - Run tests before building

## Development

For development workflow, see [CLAUDE.md](CLAUDE.md).

### Frontend Development

```bash
cd frontend/
npm install
npm run dev    # Start dev server with hot-reload
npm run test   # Run frontend tests
```

### Backend Testing

```bash
cd backend/
./docker-test.sh           # Run all tests
./docker-test.sh coverage  # Generate coverage report
```

### Manual Build

```bash
./build.sh         # Build all Docker images
./build.sh --test  # Run tests before building
```

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Comprehensive project documentation for developers
- **[INSTALLATION.md](INSTALLATION.md)** - Detailed installation guide
- **[docs/](docs/)** - Additional documentation

## Architecture

**Microservices Backend:**
- BirdNet Server (port 5001) - TensorFlow Lite model inference
- API Server (port 5002) - REST API and static file serving
- Main Processing - Continuous audio recording and analysis
- Icecast Streaming (port 8888) - Live audio to browsers

**Frontend:**
- Vue.js 3 SPA with Composition API
- Real-time WebSocket updates
- Interactive spectrograms with WaveSurfer.js
- Detection charts with Chart.js

**Data Flow:**
```
USB Mic → PulseAudio → Docker Containers → AI Analysis → Database → Web UI
```

## Security

Before running the curl installation, you can review the script:

```bash
# Download and review
curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh > install.sh
less install.sh

# Run after review
sudo bash install.sh
```

## Troubleshooting

**Docker installation fails:**
- Ensure you have a stable internet connection
- Check that your distribution is supported (Debian/Ubuntu/Raspberry Pi OS)

**Audio not detected:**
- Verify USB microphone is connected: `arecord -l`
- Check PulseAudio sources: `pactl list sources short`
- View service logs: `sudo journalctl -u birdnet-pipy -f`

**Service won't start:**
- Check logs: `sudo journalctl -u birdnet-pipy -f`
- Verify Docker is running: `docker ps`
- Ensure data directory has correct permissions

For more help, see [INSTALLATION.md](INSTALLATION.md) or open an issue on GitHub.

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
