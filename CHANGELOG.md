# Changelog

## [Unreleased]

## [0.6.2] - 2026-04-10

- Fixed storage cleanup silently skipping multi-source detection files — cleanup query was missing the `extra` column needed to reconstruct filenames with source suffixes, so those files were never deleted
- Fixed storage cleanup reporting "candidates exhausted" instead of "target reached" when the final deletion crossed the threshold
- Optimized storage cleanup to fetch cleanup candidates once instead of twice
- Redesigned audio source selection UX — pills now open the edit modal on click instead of toggling state, preventing accidental source deactivation; enable/disable toggle moved inside the modal; opacity distinguishes active vs inactive sources
- Auto-test RTSP streams on save/add with inline progress spinner, skipping test when URL unchanged (label-only edits save instantly); same pattern applied to SetupWizard
- Restored keyboard accessibility for source and notification pills
- Reduced backend memory usage by lazy-loading spectrogram dependencies (matplotlib, scipy, Pillow) and shrinking location filter caches
- Added retry logic (3 attempts with backoff) to GHCR image pull before falling back to local build
- Fixed SetupWizard requiring a second click after "Finish anyway" when adding an RTSP source
- Fixed orphaned background monitor surviving shutdown and restarting containers after stop
- Fixed `set -e` dead branches swallowing container start/restart error messages
- Fixed word-splitting regression in install script argument passing (`--branch`, `--no-reboot`)
- Fixed GHCR pull silently succeeding with stale images when compose config returns empty — now falls back to local build
- Fixed special characters in git metadata producing invalid version.json
- Derived GHCR pull image list from compose config instead of hardcoded services
- Changed GHCR image pulls to sequential to avoid network saturation on Raspberry Pi
- Preserved Docker build cache for fallback local builds instead of pruning all layers
- Added Docker space reclamation before update fetch to prevent disk-full failures
- Fixed all shellcheck warnings across install scripts
- Fixed nginx proxy headers using `$host` instead of `$http_host`, dropping the port from upstream requests and breaking audio status indicator
- Fixed Live Feed stream URL producing double-prefixed requests under HA ingress — made stream URLs relative so they resolve via `<base href>` instead of requiring a dedicated sub_filter rule
- Fixed Live Feed showing empty pills for unlabeled RTSP streams — falls back to source ID when label is missing or empty

## [0.6.1] - 2026-04-05

- Enabled multi-language bird name support for BirdNET V3.0 — filled English fallbacks for 5,235 new species in the unified species table and removed the disabled language selector restriction
- Removed 26 unused per-language V2.4 label files — all localization now goes through the unified species table
- Added auto-cleanup trigger percentage display in Settings storage card
- Hot-apply location changes (latitude, longitude, timezone) without requiring a service restart
- Decoupled timezone from TZ environment variable — reads config directly with thread-safe caching
- Fixed settings save status message overlapping the page heading on mobile
- Fixed restart progress timer showing inaccurate elapsed time — was ignoring initial delay and only updating every 20 seconds
- Fixed swap setup in install.sh for low-memory systems using GHCR pulls
- Fixed login modal appearing for unauthenticated guests on the dashboard when live feed public access was disabled — recorder health check was piggybacking on a live-feed-gated endpoint
- Decoupled recorder health from live feed into a dedicated auth-protected endpoint (`/api/recorder/status`), preventing source labels and error details from leaking to anonymous users
- Added recorder health check after login so the navbar indicator appears without a page reload

## [0.6.0] - 2026-04-02

- Added multi-source audio recording — record from multiple microphones and RTSP streams simultaneously (#22)
- Added 2-step SetupWizard replacing LocationSetupModal — guides through location and audio source configuration on first use
- Added pre-built Docker image support — install pulls ARM64 images from GHCR on release branches for faster setup, falls back to local build for non-ARM64 platforms, non-standard UIDs, or non-release branches
- Added GitHub Actions CI workflow for building and pushing Docker images to GHCR
- Added edit support for notification services with pill-based URL management
- Added global recorder health warning pill — amber FAB appears on all pages (except Settings) when audio sources are degraded or stopped, with 24-hour dismiss and priority over the update indicator
- Added auto-expanded error details on Settings page when audio sources have issues
- Added 200 per-page option and scroll-to-top button in Table view
- Added location filter probability logging for top detections
- Added CLI script to regenerate buggy spectrograms
- Changed detection filenames to use source label instead of source ID
- Improved notification URL parsing: round-trip verification falls back to custom editor when parsers lose query params, and duplicate URLs are deduplicated on save
- Improved location context: replaced mutable `last_probabilities` with immutable `LocationContext`, moved probability logging to caller
- Centralized recorder state strings as shared constants
- Refactored LiveFeed stream state derivation to use computed properties
- Fixed spectrogram generation producing cropped images (restored `bbox_inches='tight'`)
- Fixed several audio sources migration issues: missing default Local Mic on fresh installs, microphone not preserved during migration, migration skipped when defaults already set the sources key, and migrated RTSP sources getting generic labels
- Fixed per-source audio error details lost in multi-stream setup
- Fixed service restart triggered when only audio source label changes
- Fixed filename collisions when different source labels sanitize to identical strings
- Fixed recorder health broadcast failing on first attempt, causing 60s startup delay
- Fixed health cache not refreshed after restart; kept Icecast alive with no active sources
- Fixed NaN values in model logs and improved system logs modal UX
- Fixed inconsistent percentage rounding in location probability logs
- Improved chunk-level logging: raw model top-3 now includes location filter probabilities for easier debugging
- Optimized model post-processing with NumPy partial sort and masking instead of full Python sort over all species
- Fixed zero-confidence species leaking into candidates when cutoff is 0.0
- Fixed security vulnerability in happy-dom (GHSA-6q6h-j7hj-3r64)
- Fixed `set_env_var` creating duplicate keys when the target key is the only line in the env file
- Fixed `.env` overwrite during GHCR pull — now preserves existing settings like `ICECAST_PASSWORD`
- Fixed `BIRDNET_CHANNEL` not sanitized on non-release branches, breaking docker compose builds
- Fixed GHCR pull check never matched due to JSON whitespace in image inspect
- Fixed parallel build race caused by duplicate build directives

## [0.5.8] - 2026-03-25

- Added location-based species filtering (geomodel) for BirdNET V3.0 — bundled geomodel filters detections by geographic probability with thread-safe caching
- Added "new species" notification trigger — alerts when a species is detected that has never been seen before
- Added unified species lookup table merging V2.4 labels (27 languages), V3.0 taxonomy, and eBird codes — enables localized bird names for V3.0 (~6K overlapping species)
- Added unique species toggle (All/Unique) to Dashboard recent observations — both lists fetched in a single API call for instant switching
- Added recorder health status to Settings — real-time recording state surfaced via WebSocket
- Added stream URL testing with card-style audio source selector and edit modal
- Added configurable species filter threshold in Settings UI
- Added system logs viewer with per-service file logging, accessible via modal in Settings
- Added restart services button in Settings Management section
- Added timezone display in Location settings section
- Added pulsing red dot indicator on active audio source pill when recorder is running
- Added immediate persist for RTSP stream add/edit/delete — modal "Test & Save" now saves to backend without requiring a second Save click
- Redesigned audio source UI with card grid, labels, and test-and-add flow
- Merged Location and Audio Source into a single Settings card
- Combined detection sliders into responsive 3-column grid
- Converted Management section to collapsible, repositioned above Data
- Simplified filter_by_location to single filter-then-sort pass
- Improved spectrogram generation performance — skip PNG encode/decode by passing raw NumPy arrays directly
- Improved recorder health UX: cleaner errors, clipboard copy, restart state feedback
- Improved log polling efficiency with AbortController and fixed formatter duplication
- Fixed V3.0 geomodel default threshold (0.15) being silently overridden by the V2.4 default (0.03) on fresh or upgraded installs
- Fixed subprocess pipe leaks and raised FD limit to prevent "too many open files" (#35)
- Fixed location change not re-applying timezone until manual restart — now triggers full service restart
- Fixed Icecast UTC timestamps not converted to local time, causing incorrect sorting
- Fixed consistent row height in Bird Activity Overview when species limit exceeds 10
- Fixed unique species query returning too few results when one species dominates recent detections — falls back to unbounded query when pre-fetch window is insufficient
- Fixed user toggle selections (activity overview, recent observations) resetting during in-flight dashboard fetches
- Fixed input validation and thread safety in model service: guard sensitivity ≤ 0, validate inference payloads, type-check settings before merge, add thread locks to shared caches
- Fixed RTSP label-only edits not tracked as unsaved changes, causing silent data loss
- Fixed recorder health status broadcasting stale pre-restart value after automatic recovery

## [0.5.7] - 2026-03-07

- Added localized bird name support — display common names in 26 languages using BirdNET model labels, configurable in Settings
- Added granular per-feature access control — Charts, Table, and Live Feed can each be set public or private independently
- Added configurable station name for multi-system identification
- Added login button in header when authentication is enabled but user is not logged in
- Fixed RTSP stream handling: skip video streams, regenerate audio timestamps, and discard corrupt packets to prevent non-monotonic DTS errors
- Fixed Wikimedia image search returning non-bird images (eggs, skeletons) by excluding irrelevant terms
- Fixed bird name language setting not taking effect until service restart (stale lru_cache)
- Fixed language selector available for BirdNET v3 which has no localized labels — now disabled with explanation
- Fixed LiveFeed auth error not showing login modal when 401 is discovered via stream probe
- Fixed stale auth redirect causing navigation to wrong page after login
- Fixed Docker build cache growing unbounded — now prunes cache older than 7 days after builds
- Changed Settings page layout: reorganized into logical collapsible sections with extracted ToggleSwitch component
- Changed auth settings UI: replaced blockquote-style border with subtle background panel, added inline disclosure for per-feature access toggles, moved Change Password outside panel
- Changed login modal to stay on the current page instead of redirecting to Dashboard
- Improved LiveFeed error messages with specific diagnostics (stream unavailable vs server down vs decode error) and consistent console logging

## [0.5.6] - 2026-03-04

- Added Home Assistant add-on lifecycle support with restart resilience
- Added HA addon repository link on Settings page in HA mode
- Added source commit display in HA mode, hidden manual update check
- Fixed HA lifecycle provider detection fallback
- Fixed HA ingress stream config and default bird placeholder URLs

## [0.5.5] - 2026-03-02

- Added notification system via Apprise with guided service picker, built-in test, and immediate autosave
- Added notification triggers: every detection (with per-species cooldown), first of day, and rare species
- Added hot-apply settings — most settings take effect immediately without a service restart, with runtime cache and change classification
- Added species limit selector (10/20/30/All) to Bird Activity Overview heatmap, defaulting to top 10
- Added selective Docker rebuild during updates — only rebuilds images whose inputs changed; added `--services` and `--version-only` flags to `build.sh`
- Changed Bird Activity Overview to show all species with dynamic chart height and smooth animated transitions
- Changed recordings sort dropdown to pill-shaped toggle
- Changed version display format to version(commit hash)
- Fixed multiple notification issues: API returning 500 for malformed payloads, URL masking crash, Home Assistant defaulting to HTTPS, MQTT silently disabled due to missing dependency, placeholders using unresolvable `.local` hostnames, and generic test error messages
- Fixed build pipeline: Docker build failures not detected, stale version.json kept on write failure, update loop stuck on "update available" after failed build
- Fixed species filter modal not closing after successful hot-save
- Fixed inference shape mismatch crash by skipping stale audio files
- Fixed GitHub repository link to use remote URL from version info
- Removed incorrect `docker logs` commands from deployment README

## [0.5.4] - 2026-02-19

- Added consolidated Dashboard API into a single `/api/dashboard` endpoint, reducing 5–6 concurrent requests to 1
- Added tab visibility handling — polling pauses when tab is hidden and resumes on focus
- Added keep-alive caching for Dashboard and Gallery — navigating between pages restores state instantly without a full reload
- Added 3-state loading pattern on Dashboard to prevent false empty states before first fetch
- Added fetch race guard to prevent stale responses from overlapping requests overwriting newer data
- Changed bar charts to update in-place instead of destroy/rebuild on each poll cycle
- Changed dashboard activity overview from two DB queries to one
- Fixed bird image not retrying after a failed Wikimedia fetch
- Fixed chart animation not playing on keep-alive reactivation; prevented double animation from rapid page switching
- Fixed polling starvation when API latency exceeds the poll interval
- Fixed ghost polling continuing after keep-alive deactivation during an in-flight fetch

## [0.5.3] - 2026-02-16

- Added eBird species link to bird details page
- Added sort toggle to Bird Activity Overview (replaced in later release by showing all species)

## [0.5.2] - 2026-02-15

- Fixed version displaying as "unknown" on Pi deployments (build.sh used node which isn't on the host)

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
