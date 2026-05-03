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

## Repository Layout

```
frontend/src/
  views/         # Page components
  components/    # Reusable UI (modals, toggles, alerts, etc.)
  composables/   # Vue composition functions (use*)
  services/      # API client (axios)
  utils/         # Shared helpers and constants
  router/        # Vue Router config
backend/
  core/          # App logic (API, DB, recording, notifications, HA mode)
  model_service/ # Inference (V2.4 TFLite / V3.0 ONNX via factory pattern)
  config/        # Settings and constants
  tests/         # pytest suite
deployment/      # Runtime service scripts, Icecast streaming
scripts/         # lint.sh, install-tests/ (BATS)
docs/            # ARCHITECTURE, INSTALLATION, PRIVACY
internal_docs/   # Planning notes (workflow, reviews, design docs) — gitignored, do not commit
```

`AGENTS.md` is a symlink to this file.

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

## Git Hygiene

Never bypass `.gitignore` (no `git add -f`, no explicit-path force-staging) without explicit user approval. If a file genuinely needs to be in the repo, change the ignore rule instead of overriding it for one file — silently force-adding leaves a tracked file behind that the ignore pattern can't clean up later.
