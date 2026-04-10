# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BirdNET-PiPy is a Python-based bird detection system based on the BirdNET model. It's a full-stack application with Vue.js frontend and Python Flask microservices backend, designed for Raspberry Pi deployment.

## Best Practices

Prefer simple, modular code with small focused components.

## Key Technologies

- **Frontend:** Vue.js 3, Vite, TailwindCSS, Chart.js, WaveSurfer.js, Socket.IO
- **Backend:** Flask, TensorFlow Lite, ONNX Runtime, SQLite, NumPy, Scipy, Matplotlib, Apprise, Paho-MQTT
- **Deployment:** Docker Compose with shared volumes for data persistence

## Architecture

**Microservices Backend:**
- **Model Inference Server** (`backend/model_service/inference_server.py`) - Port 5001: BirdNET model inference (V2.4 TFLite / V3.0 ONNX via factory pattern)
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
- `CHANGELOG.md` - Version history and release notes
- `AGENTS.md` - Symlink to CLAUDE.md
- `internal_docs/` - Internal planning documents (git workflow, version bumping, reviews)

**Scripts (`scripts/`):**
- `lint.sh` - Run linters (ESLint + Ruff) in Docker
- `install-tests/` - BATS tests for install/uninstall scripts

**Frontend (`frontend/`):**
- `src/views/` - Page components (Dashboard, Settings, Charts, BirdDetails, LiveFeed, Detections, BirdGallery, BirdDetectionList, Spectrogram, Table)
- `src/components/` - Reusable UI components (modals, toggles, buttons, alerts, etc.)
- `src/composables/` - Vue composition functions (useAuth, useFetchBirdData, useMigration, useServiceRestart, useAppStatus, useAudioPlayer, useBirdCharts, useChartColors, useChartHelpers, useDateNavigation, useLogger, useSmartCrop, useSystemUpdate, useTableData, useUnitSettings)
- `src/services/` - API client configuration
- `src/router/` - Vue Router configuration

**Backend (`backend/`):**
- `core/` - Main application logic (api.py, api_utils.py, db.py, main.py, audio_manager.py, auth.py, bird_name_utils.py, ha_mode.py, logging_config.py, migration.py, migration_audio.py, notification_service.py, runtime_config.py, storage_manager.py, utils.py, birdweather_service.py, weather_service.py, timezone_service.py)
- `model_service/` - BirdNET model inference with factory pattern (base_model.py, model_factory.py, birdnet_v2_model.py, birdnet_v3_model.py, label_utils.py, inference_server.py)
- `config/` - Environment-aware configuration (settings.py, constants.py)
- `tests/` - Test suite (api/, audio/, config/, database/, fixtures/, integration/, model_service/, notification_service/, scripts/)

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

Three test suites cover backend, frontend, and install scripts. Each has its own README with detailed patterns, fixtures, and examples.

**Before Committing:**
1. Run backend tests: `cd backend && ./docker-test.sh`
2. Run frontend tests: `cd frontend && npm run test`
3. Run install tests (only when `install.sh`, `uninstall.sh`, or `build.sh` change): `cd scripts/install-tests && ./docker-test-install.sh`

**Key Patterns:**
- Backend (pytest, Docker): Real temporary SQLite databases for API/DB tests; mocked subprocess calls (ffmpeg, sox) and external services (Wikimedia, socketio). See `backend/tests/README.md`.
- Frontend (Vitest, happy-dom): Mocked API and composable dependencies; `@vue/test-utils` for component mounting. See `frontend/tests/README.md`.
- Install (BATS, Docker-in-Docker): Debian container with systemd and nested Docker for realistic install/update testing. Slow (~5-10 min). See `scripts/install-tests/README.md`.

## Branch Sync Rules

Before syncing dev to staging or main, always run `./build.sh` first and confirm it passes.
