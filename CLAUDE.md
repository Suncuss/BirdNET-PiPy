# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BirdNET-PiPy is a Python-based bird detection system based on the BirdNET model. It's a full-stack application with Vue.js frontend and Python Flask microservices backend, designed for Raspberry Pi deployment.

## Best Practices

- Prefer smaller separate components over larger ones
- Prefere simple and robust design
- Prefer modular code over monolithic code

## Key Technologies

- **Frontend:** Vue.js 3, Vite, TailwindCSS, Chart.js, WaveSurfer.js, Socket.IO
- **Backend:** Flask, TensorFlow Lite, Librosa, SQLite, NumPy, Matplotlib
- **Deployment:** Docker Compose with shared volumes for data persistence

## Architecture

**Microservices Backend:**
- **BirdNet Server** (`backend/birdnet_service/birdnet_server.py`) - Port 5001: TensorFlow Lite model inference
- **API Server** (`backend/core/api.py`) - Port 5002: REST API and static file serving
- **Main Processing** (`backend/core/main.py`) - Continuous audio recording and analysis pipeline
- **Icecast Streaming** (`backend/deployment/audio/`) - Port 8888: Live audio streaming to browsers

**Frontend:** Vue.js 3 SPA with Composition API, using composables pattern for reusable logic

**Audio Architecture:**
```
USB Microphone → PulseAudio (Host) → Docker Containers
                      ↓
    ┌─────────────────┴─────────────────┐
    ↓                                   ↓
Main Container                    Icecast Container
(FFmpeg → WAV → BirdNET)          (FFmpeg → MP3 → Browser)
```

**Data Flow:** Audio recording → BirdNET analysis → Database storage → API → Frontend visualization

## Development Commands

**Build & Deploy (Recommended):**
```bash
# Full build and deploy with one command
./build.sh                  # Builds frontend + backend, then deploys

# Build options
./build.sh --test           # Run tests before building
./build.sh --help           # Show all available options

# Note: Frontend is built inside Docker (no Node.js needed on host)
```
**Testing:**
```bash
# Run all backend tests in Docker (recommended)
cd backend/
./docker-test.sh            # Runs full test suite in Docker container

# Run with coverage report
./docker-test.sh coverage   # Generates coverage report at backend/htmlcov/index.html

# Run specific test files
./docker-test.sh tests/api/test_simple_api.py

# Run frontend tests
cd frontend/
npm run test                # Run all frontend tests
npm run test:watch          # Run tests in watch mode
npm run test:coverage       # Run tests with coverage report
```

## File Organization

- `frontend/src/composables/` - Reusable Vue composition functions
- `backend/birdnet_service/` - AI model service and TensorFlow Lite models
- `backend/core/` - Main application logic and API
- `backend/config/settings.py` - Environment-aware configuration
- `backend/scripts/` - Database and development scripts
- `deployment/` - Production deployment scripts and configuration
  - `birdnet-service.sh` - Runtime service management script
  - `birdnet-pipy.service` - Systemd service template
  - `audio/` - Audio streaming infrastructure (PulseAudio + Icecast)
    - `Dockerfile` - Icecast container image
    - `scripts/start-icecast.sh` - Icecast container entrypoint
    - `icecast.xml` - Icecast streaming server config
    - `pulseaudio/` - PulseAudio system configuration
- `data/` - SQLite database and audio files (created at runtime)


## Git Workflow

**IMPORTANT: Use feature branch workflow for organized development:**

**Daily development workflow:**
```bash
# Work on dev branch (default)
git checkout dev

# Make changes, commit frequently
git add .
git commit -m "feat: description of changes"
git push origin dev

# Repeat for multiple commits...
```

**Milestone/release workflow:**
```bash
# When ready to release (major features complete)
git checkout main
git merge dev
git push origin main

# Switch back to dev for continued work
git checkout dev
```

## Development Notes

- Services communicate via HTTP APIs during development
- Frontend dev server proxies to backend services
- Database and audio files stored in `./data/` directory
- Real-time updates use WebSocket connections via Flask-SocketIO

## Testing Guidelines

**Test Structure:**
- Backend tests: `backend/tests/` (118 tests, 62% coverage)
  - API tests: `backend/tests/api/`
  - Database tests: `backend/tests/database/`
  - Audio tests: `backend/tests/audio/` - HttpStreamRecorder & PulseAudioRecorder
  - Integration tests: `backend/tests/integration/` - main.py pipeline tests
  - Utils tests: `backend/tests/test_utils.py`
  - Test configuration: `backend/tests/conftest.py` (global fixtures)
- Frontend tests: `frontend/tests/` (51 tests)
  - Composable tests: `frontend/tests/composables/`
  - Router tests: `frontend/tests/router/`
  - Test runner: Vitest with happy-dom environment

**Important Testing Patterns:**
- All backend tests run in isolated Docker containers for consistency
- **API tests use REAL temporary SQLite databases** for integration testing (not mocks)
- Each test gets a fresh temporary database, ensuring test independence
- External services (Wikimedia API, socketio) remain mocked
- File system operations use temporary directories
- Subprocess calls (ffmpeg, curl, sox) are mocked in audio tests
- Frontend uses Vitest with happy-dom for Vue component testing

**Before Committing Changes:**
1. Run backend tests: `cd backend && ./docker-test.sh`
2. Run frontend tests: `cd frontend && npm run test`
3. If modifying API endpoints, ensure response formats remain compatible
4. Add new tests for any new functionality
5. Check that mocked dependencies match actual interfaces

## Documentation

For detailed information about specific aspects of the project, refer to the following documentation:

### Project Structure & Architecture
- **[Project Documentation](docs/PROJECT_DOCUMENTATION.md)** - Comprehensive overview of system architecture, backend/frontend structure, API documentation, and deployment details

### Feature Implementations
- **[Authentication](docs/AUTHENTICATION.md)** - Optional password protection for settings and audio stream with bcrypt hashing and 7-day sessions
- **[Settings Implementation](docs/SETTINGS_IMPLEMENTATION.md)** - Dynamic settings management system allowing runtime configuration changes without container restarts
- **[Charts Implementation](docs/CHARTS_IMPLEMENTATION.md)** - Interactive data visualization features including bird activity overview and species detection charts
- **[Overlap Implementation](docs/OVERLAP_IMPLEMENTATION.md)** - Audio chunking with overlap for improved detection, BirdNET-Pi compatible

