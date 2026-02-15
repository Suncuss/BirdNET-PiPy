# Changelog

## [Unreleased]

## [0.5.1] - 2026-02-15

- Added custom bird image upload support in Gallery
- Added GitHub repository link to Settings system section
- Added version number display alongside commit hash in Settings
- Fixed misleading download banner when switching models
- Fixed custom image attribution height alignment in gallery cards
- Fixed lint warnings in AppButton and BirdGallery

## [0.5.0] - 2026-02-13

- Added BirdNET V3.0 model support (ONNX, 11K species, 32kHz) with auto-download and settings UI
- Added graceful fallback when V3 model download fails (API stays up, retries on next restart)
- Added Table link to navigation bar
- Changed "Bird Gallery" to "Gallery" in navigation
- Refactored model service: shared post-processing, centralized label parsing, single-source-of-truth constants
- Fixed dangling Docker images accumulating on Pi after each rebuild
- Fixed invalid model type in settings crashing the service instead of falling back gracefully
- Fixed axios CVE by upgrading to 1.13.5

## [0.4.0] - 2026-02-05

- Added BirdNET-Pi migration - import historical detections, audio files, and generate spectrograms via Settings
- Added BirdWeather integration - upload detections and audio to birdweather.com
- Added weather data integration - attaches current weather from Open-Meteo API to detections
- Added weather display in Detection Info modal (temperature, humidity, wind, precipitation, cloud cover, pressure)
- Added automatic update checking with dismissible FAB on dashboard (desktop/tablet only)
- Added metric/imperial unit toggle in Settings (Advanced → Display)
- Added offline timezone detection from coordinates using timezonefinder
- Added date picker validation in Table view (no future start dates, end date must follow start)
- Added PrimeVue DatePicker for consistent cross-browser date styling
- Added unsaved changes detection on Settings page with confirmation modal
- Added Open-Meteo attribution link in Detection Info modal
- Added `--branch` option to install.sh for installing from non-main branches
- Changed location setup to be required before detection starts (removed "Skip for now")
- Changed audio/spectrogram filenames to use dashes instead of colons in timestamps (better compatibility)
- Changed lat/long inputs to limit to 2 decimal places (sufficient for species filtering)
- Simplified install.sh
- Moved dev scripts to `scripts/` folder for cleaner root directory
- Improved migration modal instructions with clearer 3-step process
- Fixed authentication bypass that allowed enabling auth without a password via API
- Fixed dashboard not loading when authentication is enabled but user isn't logged in
- Fixed spectrogram canvas resetting during audio playback
- Fixed live spectrogram display not initializing in Dashboard
- Fixed unnecessary service restart when settings didn't actually change
- Fixed shutdown signal handling before threads are created (issue #6)
- Fixed PulseAudio socket permissions for Docker access (issue #6)
- Fixed BirdNET-Pi audio import matching files with underscores vs colons in timestamps
- Fixed database migration to prevent parallel imports when navigating away and returning
- Fixed date pickers displaying incorrectly on mobile in Table view
- Fixed iOS zoom on date picker inputs
- Fixed location check to support coordinates at 0° latitude/longitude
- Fixed audio queue cleanup error when buffer is full

## [0.3.2] - 2026-01-17

- Fixed toggle buttons getting cut off on mobile in Settings page
- Improved Live Feed error handling - detects network errors, stream end, and buffering issues
- Added visual error feedback with amber pulsing status message
- Added stream connection/disconnection logging in Icecast container
- Improved Live Feed status messages - focused on audio state
- Hidden stream description on mobile for cleaner layout
- Refactored: DRY improvements for detection filtering, normalization, and file deletion
- Refactored: Shared audio player composable for Table and Dashboard views
- Refactored: Shared ffmpeg helpers in audio recorders

## [0.3.1] - 2026-01-10

- Added Detection Trends chart showing bird activity over configurable time ranges
- Added reusable AppButton component for consistent button styling
- Changed default bird images to WebP format for smaller file sizes
- Fixed chart control alignment on mobile devices
- Fixed smart cropping for portrait-oriented bird images
- Improved chart navigation and label spacing

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

First public release.

- Added one-line curl install for Raspberry Pi
- Added in-app update checking and installation
- Added storage usage display and automatic cleanup (keeps top 60 per species)
- Added optional password protection for settings and audio stream
- Added rate limiting on login
- Added auto-reboot after installation with countdown
- Added installation logging for troubleshooting
- Changed audio loading from librosa to scipy for faster startup
- Fixed memory leaks in dashboard audio playback
- Fixed thread hangs with proper timeouts

---

## Pre-release

### August-November 2025

- Added PulseAudio architecture for multi-container audio sharing
- Added Icecast streaming for browser audio playback
- Added nginx reverse proxy for unified port 80 access
- Added support for USB microphone, HTTP streams, and RTSP cameras
- Added configurable overlap between audio chunks for better detection at boundaries
- Added Docker Compose deployment with systemd service
- Added test suite for backend and frontend
- Added single build.sh script to build and deploy everything
- Changed spectrogram format from PNG to WebP (87% smaller)
- Improved Docker builds with multi-stage pattern
- Refactored main.py to filesystem-as-queue architecture
- Added thread safety with TFLite interpreter locking
- Added security hardening: input validation, CORS, secure headers
- Expanded test coverage to 62% with real SQLite databases

### June-July 2025

- Added structured logging across backend services
- Improved API response sizes for Raspberry Pi
- Improved charts with hourly/daily ticks and grid lines
- Improved spectrogram file sizes

### May-June 2025

- Added Charts view with day/week/month navigation
- Added real-time live detection via Socket.IO
- Added FFmpeg + Icecast deployment for browser audio streaming
- Added dynamic settings management with flag-based restarts
- Added mobile-friendly layouts
- Fixed Safari chart rendering and dropdown styling
- Fixed SPA routing in Docker

### August 2024

- Added BirdDetails view with per-species detection history and charts
- Added paginated recordings section with sort options
- Added audio playback for bird calls
- Added Docker containers for frontend and backend
- Added Settings page for recording source, location, confidence threshold
- Improved spectrogram styling

### July 2024

- Added Vue.js 3 frontend with Composition API
- Added Dashboard with detection summary, recent observations, and activity charts
- Added Bird Gallery with Wikimedia images
- Added Chart.js integration for detection distribution
- Added WebSocket support for live updates

### November 2023

- Created initial project structure
- Added Flask backend with REST API endpoints
- Added SQLite database schema for storing detections
- Added BirdNET TensorFlow Lite model integration
- Added basic audio recording and processing pipeline
- Added spectrogram generation using matplotlib
