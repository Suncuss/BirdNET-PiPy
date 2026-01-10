## [Unreleased]

## [0.3.0] - 2026-01-10

- Added smart image cropping - bird photos now crop to center the bird in frame
- Added smooth fade transition when switching between bird images
- Added update channel setting - choose between stable releases or latest development builds
- Added model factory pattern to backend to support different ML models in the future
- Changed Wikimedia image cache expiration from 24 to 48 hours
- Improved update UX - page auto-scrolls to top so you can see progress messages
- Improved update messaging when switching between channels
- Fixed update flow for users ahead of stable tags
- Fixed checkout conflicts with untracked files during updates
- Fixed stable channel updates from detached HEAD state
- Removed redundant "update available" status text
- Removed old `birdnet_service` directory

## [0.2.0] - 2026-01-02

- Added eBird species codes to detections
- Added detection info modal - click a detection to see model info, eBird code, timestamps
- Added model name and version tracking to each detection
- Added flexible `extra` JSON field to database for additional metadata
- Added CSV export for detections from Settings page
- Added batch delete for detections table
- Added release notes display for system updates
- Added auto-save for species filter with restart feedback in modal
- Added `--update` flag to install.sh for updating system configs without full reinstall
- Added privacy policy documentation
- Added retry tip message when installation fails
- Changed default port from 8080 to 80
- Changed species filter to show common names instead of scientific names
- Changed install completion message to show actual hostname and IP address
- Changed reboot message to show success first, then warn about disconnect
- Improved Settings page layout - more compact spacing
- Improved icons and wording in Gallery and BirdDetails
- Improved tab icon sizes for better visibility
- Improved debugging - now logs top 3 model outputs before filtering
- Fixed live feed stream reload to jump to current position
- Fixed pagination button widths in BirdDetails
- Fixed PipeWire audio handling on desktop systems
- Fixed systemd service StartLimit placement
- Removed geolocation from location setup (needs HTTPS)
- Removed internal docs from repository

## [0.1.0] - 2025-11-28

First release.

- Added bird detection using BirdNET TensorFlow Lite model
- Added Dashboard with detection summary, recent observations, and activity charts
- Added Bird Gallery with Wikimedia images
- Added Bird Details page with detection history, charts, and recordings list
- Added Charts view with day/week/month navigation
- Added Live Feed showing detections in real-time via WebSocket
- Added Settings page for recording source, location, confidence threshold
- Added PulseAudio setup for sharing audio between containers
- Added Icecast streaming for browser audio playback
- Added support for USB microphone, HTTP streams, and RTSP cameras
- Added configurable overlap between audio chunks for better detection at boundaries
- Added WebP spectrograms (much smaller than PNG)
- Added mobile-friendly layouts
- Added Safari compatibility
- Added audio playback for bird calls
- Added one-line curl install for Raspberry Pi
- Added Docker Compose deployment with nginx reverse proxy
- Added auto-reboot after installation with countdown
- Added installation logging for troubleshooting
- Added in-app update checking and installation
- Added systemd service with auto-restart
- Added storage usage display and automatic cleanup (keeps top 60 per species)
- Added optional password protection for settings and audio stream
- Added rate limiting on login
- Added test suite for backend (real SQLite databases) and frontend (Vitest)
- Added single build.sh script to build and deploy everything
- Changed audio loading from librosa to scipy for faster startup
- Fixed memory leaks in dashboard audio playback
- Fixed thread hangs with proper timeouts
- Fixed chart timezone issues

---

## Pre-release

### August-November 2025

- Added direct ALSA microphone recording option
- Added HTTP stream recording with atomic file writes
- Added RTSP camera support
- Changed audio architecture from ALSA to PulseAudio for multi-container sharing
- Added Icecast stream to LiveFeed view
- Added auto-detect for host timezone
- Changed spectrogram format from PNG to WebP (87% smaller)
- Added nginx reverse proxy for unified port 80 access
- Improved Docker builds with multi-stage pattern
- Refactored main.py to filesystem-as-queue architecture
- Added thread safety with TFLite interpreter locking
- Added timeouts to prevent thread hangs
- Fixed memory leaks in dashboard audio context
- Added security hardening: input validation, CORS, secure headers
- Expanded test coverage to 62% with real SQLite databases
- Added one-line curl installation script
- Added systemd service with auto-restart

### June-July 2025

- Added structured logging across backend services
- Improved API response sizes for Raspberry Pi
- Improved charts with hourly/daily ticks and grid lines
- Improved spectrogram file sizes

### May-June 2025

- Rebuilt detection distribution with day/week/month tabs
- Added real-time live detection via Socket.IO
- Added FFmpeg + Icecast deployment for browser audio streaming
- Added dynamic settings management with flag-based restarts
- Fixed Safari chart rendering issues
- Fixed Safari dropdown styling
- Fixed SPA routing in Docker

### August 2024

- Added BirdDetails view with per-species charts
- Added audio playback with useAudioPlayback composable
- Added Docker containers for frontend and backend
- Added database queries with confidence tiebreaking
- Added timestamp handling for detection records
- Improved spectrogram styling

### July 2024

- Added Vue.js 3 frontend with Composition API
- Added Dashboard view with detection charts
- Added BirdGallery view for browsing species
- Added Chart.js integration for detection distribution
- Added Wikimedia API integration for bird photos
- Added WebSocket support for live updates

### November 2023

- Created initial project structure
- Added Flask backend with REST API endpoints
- Added SQLite database schema for storing detections
- Added BirdNET TensorFlow Lite model integration
- Added basic audio recording and processing pipeline
- Added spectrogram generation using matplotlib
