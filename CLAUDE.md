# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BirdNET-PiPy is a Python-based bird detection system based on the BirdNET model. It's a full-stack application with Vue.js frontend and Python Flask microservices backend, designed for Raspberry Pi deployment.

## Best Practices

Prefer simple, modular code with small focused components.

## Key Technologies

- **Frontend:** Vue.js 3, Vite, TailwindCSS, Chart.js, WaveSurfer.js, Socket.IO
- **Backend:** Flask, TensorFlow Lite, Librosa, SQLite, NumPy, Matplotlib
- **Deployment:** Docker Compose with shared volumes for data persistence

## Architecture

**Microservices Backend:**
- **Model Inference Server** (`backend/model_service/inference_server.py`) - Port 5001: TensorFlow Lite model inference
- **API Server** (`backend/core/api.py`) - Port 5002: REST API and static file serving
- **Main Processing** (`backend/core/main.py`) - Continuous audio recording and analysis pipeline
- **Icecast Streaming** (`deployment/audio/`) - Port 8888: Live audio streaming to browsers

**Frontend:** Vue.js 3 SPA with Composition API, using composables pattern for reusable logic

**Data Flow:** Audio recording → BirdNET analysis → Database storage → API → Frontend visualization

## Development Commands

**Build & Deploy:**
```bash
./build.sh                  # Builds frontend + backend, then deploys
./build.sh --test           # Run tests before building
./build.sh --help           # Show all options
```

**Testing:**
```bash
cd backend && ./docker-test.sh              # Backend tests in Docker
cd frontend && npm run test                 # Frontend tests
```

**Linting:**
```bash
./scripts/lint.sh             # Lint both frontend and backend
./scripts/lint.sh --fix       # Auto-fix issues
```

## File Organization

**Root Level:**
- `build.sh` - Build and deploy script
- `install.sh` / `uninstall.sh` - System installation scripts
- `docker-compose.yml` - Multi-container Docker configuration

**Scripts (`scripts/`):**
- `lint.sh` - Run linters (ESLint + Ruff) in Docker
- `install-tests/` - BATS tests for install/uninstall scripts

**Frontend (`frontend/`):**
- `src/views/` - Page components (Dashboard, Settings, Charts, BirdDetails, LiveFeed, etc.)
- `src/components/` - Reusable UI components
- `src/composables/` - Vue composition functions (useAuth, useFetchBirdData, useMigration, useServiceRestart, etc.)
- `src/services/` - API client configuration
- `src/router/` - Vue Router configuration

**Backend (`backend/`):**
- `core/` - Main application logic (api.py, db.py, main.py, audio_manager.py, auth.py, storage_manager.py, migration.py, birdweather_service.py, weather_service.py, timezone_service.py)
- `model_service/` - TensorFlow Lite model inference with factory pattern
- `config/` - Environment-aware configuration (settings.py, constants.py)
- `tests/` - Test suite (api/, audio/, config/, database/, integration/, model_service/)

**Deployment (`deployment/`):**
- `birdnet-service.sh` - Runtime service management
- `audio/` - Icecast streaming infrastructure

**Documentation (`docs/`):**
- `ARCHITECTURE.md`, `INSTALLATION.md`, `PRIVACY.md`, etc.

## Development Notes

- Services communicate via HTTP APIs through nginx reverse proxy
- Frontend is built inside Docker and served by nginx on port 80
- Nginx proxies `/api/` requests to the API container and `/socket.io/` for WebSockets
- Database and audio files stored in `./data/` directory
- Real-time updates use WebSocket connections via Flask-SocketIO

## Testing Guidelines

**Testing Patterns:**
- All backend tests run in isolated Docker containers
- API tests use real temporary SQLite databases (not mocks)
- External services (Wikimedia API, socketio) are mocked
- Subprocess calls (ffmpeg, curl, sox) are mocked in audio tests
- Frontend uses Vitest with happy-dom

**Before Committing:**
1. Run backend tests: `cd backend && ./docker-test.sh`
2. Run frontend tests: `cd frontend && npm run test`



