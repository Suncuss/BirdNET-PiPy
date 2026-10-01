# Changelog

## [Unreleased]

## [0.8.11] - 2026-09-30

- Changed the CSV export to open a window where you pick a time range, show progress while the file is prepared, then download it as a .zip. Large exports no longer time out, and closing the window doesn't stop an export in progress.
- Changed sign-ins on password-protected stations so that signing out ends only that browser's session. Browsers signed in before this update need to sign in once more.
- Changed the BirdNET-Pi audio import to stop at your storage cleanup trigger instead of a fixed 85%. Imports and exports always leave the last 5% of the disk free for recording.
- Removed public API endpoints the app no longer uses: `GET /api/observations/latest`, `/recent` and `/summary` (use `GET /api/dashboard` and `GET /api/dashboard/summary?period=…`), `GET /api/bird/<name>/wikimedia_choice`, and the `average_confidence` and `seasonality` fields of `GET /api/bird/<name>`. Anything that reads them directly, such as a Home Assistant REST sensor, needs updating.
- Removed five owner-only API endpoints the app no longer calls: `GET /api/settings/defaults`, `/api/model/status` and `/api/settings/status`, and `POST /api/migration/audio/skip` and `/spectrogram/skip`.
- Improved the Gallery's photo loading: photos load a few at a time in reading order, with a placeholder until each one arrives.
- Improved the reload after an update or restart: the page reloads as soon as the detection model and recorder are running, instead of after a fixed wait.
- Improved the "System is updating" screen to appear as soon as a page is opened during an update.
- Improved recording playback on the Dashboard and Table: when a recording can't be played, for example because storage cleanup removed it, a message now says so.
- Fixed BirdNET V3.1 saving detections of people talking. It now applies the same human-voice privacy filter as V2.4.
- Fixed the CSV export, storage cleanup and post-import media indexing slowing down on stations with long detection histories.
- Fixed deleting more than 100 selected detections on the Table page. A delete that stops partway now says how many were deleted.
- Fixed the "System is updating" screen never going away for signed-out visitors when public access is turned off.
- Fixed `uninstall.sh --remove-project` (and `--full` after declining to delete data) deleting the `data/` folder, and doing nothing when the project folder is a symlink.

## [0.8.10] - 2026-09-20

- Changed the phone navigation bar to a single swipeable row that highlights the current page.
- Changed the Charts page's Activity Overview to match the Dashboard's row spacing and species limits.
- Improved the Dashboard's Activity Overview to animate height changes, as the Charts page does.
- Fixed Activity Overview species names not lining up with the card heading, and long names losing their first letters instead of ending in "…".
- Fixed the Charts and species pages not releasing their charts when you leave them, so a tab left open for a long time slowly used more memory.

## [0.8.9] - 2026-09-19

- Added quiet hours (Settings → Detection → Quiet Hours): a daily time window during which recording and detection pause. While paused, the status badge reads "Paused until …".
- Added live audio-source reload: changing a source reconnects only that source's recorder and stream, without a restart.
- Changed disabling every audio source to show "Audio Paused" instead of an audio fault, warning and notification.
- Changed all dropdowns to one shared control that looks and works the same in every browser and supports the keyboard. The Charts time-range pickers are now available on phones.
- Changed audio-source edits to wait for Save, with a prompt before unsaved edits are discarded.
- Improved recording, streaming and model status in Settings: it now updates live, and shows a loading placeholder instead of misleading "unavailable" messages.
- Improved station load by checking settings status only while the Settings page is open.
- Fixed simultaneous settings saves from different controls, tabs or devices overwriting each other.
- Fixed stations refusing to start after an update when a saved setting broke a newly added rule. Such values are now repaired.
- Fixed live streaming after updating on stations with the older audio settings format, and in the Home Assistant add-on.
- Fixed Settings showing "undefined new commits" for an available update when opened with an expired login.
- Fixed Settings showing errors and model warnings during an update or restart.
- Fixed the Settings page briefly showing empty defaults, such as "recording is paused", before loading.
- Fixed audio sources saved before the enable/disable toggle existed being shown as disabled while still recording.
- Fixed logging out leaving the browser's live status connection signed in.
- Fixed model changes replacing an explicitly chosen filter threshold.
- Fixed audio queued before a model change not being resampled for the new model.
- Fixed false save conflicts behind a compressing proxy.
- Fixed the setup wizard occasionally opening on stations that were already set up.
- Fixed the Table and Charts species dropdown not reopening after a selection.
- Fixed a source that failed before quiet hours being reported as an audio problem for the whole pause.

## [0.8.8] - 2026-08-21

- Improved audio capture to be gapless: each source now records through one continuous ffmpeg stream instead of a new process per segment, which lost audio between recordings on slower devices. Set `BIRDNET_CAPTURE_MODE=segment` to go back to the old behavior.
- Fixed the service failing to start after an unclean shutdown left Docker with broken container records. It now repairs them and keeps retrying.
- Fixed the live-stream service running an encoder for disabled audio sources.

## [0.8.7] - 2026-08-16

- Added optional cleanup policies: keep only the last N days of recordings, or cap media at N GB. Both are off by default.
- Improved Dashboard summary and trends loading on large databases. The data they need is built in the background after upgrading.
- Improved storage cleanup's memory use on small devices such as the Pi Zero 2W.
- Improved the species page's Best and Most Recent recordings to list only clips whose files still exist.
- Improved crash safety: recording files are written atomically, and leftovers from a crash are cleaned up by a weekly maintenance task.
- Changed new recording filenames to include a unique suffix, so same-second detections can't collide.
- Fixed Docker build caches mixing between staging and main, which could cause unneeded downloads after a release.

## [0.8.6] - 2026-08-08

- Added an installer option to choose the web port (`--port 8080`) when port 80 is taken, for example by Pi-hole. `--update --port N` changes it on an existing install.
- Added pre-built AMD64 images, so x86 installs no longer build locally.
- Added an update screen for visitors who open the app during an update. It shows the current stage and reloads when the station is back.
- Changed password changes to sign out every other device and invalidate existing share links and audio links. Re-share any link you still need.
- Changed the documented hardware support to Raspberry Pi 5, 4, 3 and Zero 2W.
- Improved update downloads: model files and base layers are reused between releases, and the image no longer includes a compiler or duplicated files.
- Improved the update banner to show the current stage instead of an elapsed-time counter, and kept the web interface reachable while images download or build.
- Improved the message after saving settings to say services are restarting, without a timer.
- Improved the Dashboard on tall desktop screens: Activity Overview shows up to 15 species and Recent Observations shows 8 entries.
- Improved the species page layout on desktop so the distribution chart fills its card.
- Fixed an unreadable `auth.json` (for example after a power cut) being replaced with a config that turned authentication off. It is now written safely and left alone if it can't be read.
- Fixed the settings file and other sensitive files being readable by other local users.
- Fixed several password-change races that could leave old sessions or audio links valid.
- Fixed signed-out visitors being able to see the exact build commit, how many updates the station is behind, and your audio source names.
- Fixed clicking a Dashboard chart cell sometimes leaving the Table stuck on a spinner and then showing "cannot reach the server".
- Fixed slow Table queries overwriting newer results, and deletes right after a restart wrongly reporting a failure.
- Fixed deleting a detection leaving behind copies of its media saved under older filename formats, and storage cleanup skipping some of those files.
- Fixed a stale "System update available" banner flashing just before the page reloads after an update.
- Fixed locally built backend images including a leftover `backend/data` folder when one existed.
- Fixed species photos on the species page cropping out the bird on wide screens.
- Fixed night-time detections showing a sun icon in the weather card.

## [0.8.5] - 2026-07-25

- Changed "bird" wording to "species", since detections aren't limited to birds. The summary API fields were renamed to match (`mostCommonBird` → `mostCommonSpecies`, `rarestBird` → `rarestSpecies`, and their variants), which breaks anything that reads `/api/observations/summary` or `/api/dashboard` directly.
- Changed BirdNET V3 to the V3.1 model, which is smaller and ships with the app instead of being downloaded on first use.
- Added a weekly database integrity check that alerts on corruption, and a rotating database backup stored next to the database.
- Improved BirdNET V3 location filtering with Geomodel v3.0.3. Settings now warns if location filtering stops working; detection carries on.
- Improved model startup: recordings stay queued while the model service is down, and startup failures are shown in Settings.
- Improved database performance on busy and low-memory stations, including the Dashboard, Gallery and species pages. This fixes a known cause of Dashboard timeouts.
- Improved BirdNET-Pi imports on low-memory devices by checking for duplicates in the database instead of in memory.
- Fixed the update and restart banner reloading too early on slow devices. Slow updates now get up to 30 minutes, and a failed update is reported.
- Fixed species pages appearing blank or incomplete for species the model lists under two scientific names after a taxonomy change.
- Fixed the Dashboard player's spectrogram scrolling in blank columns when playback ended.

## [0.8.4] - 2026-07-12

- Added a Site URL setting (Settings → Personalization) so detection notifications link to the detection's page. On private stations the link includes a 30-day share token.
- Added installer support for freeing unused GPU memory on headless Raspberry Pis with under 1GB of memory, such as the Pi Zero 2W. It never overrides an existing `gpu_mem` setting and is removed by `uninstall.sh`.
- Improved Dashboard responsiveness on busy stations by keeping the weekly, 30-day and all-time summaries cached between detections.
- Improved detection clip creation to use a single ffmpeg step. sox is no longer needed.
- Improved spectrogram rendering, removing matplotlib and scipy from the backend. Images look the same.
- Improved backend memory use, especially on small devices.
- Fixed Docker container logs growing without limit. Container logs are now capped and show warnings and errors; full logs are in `data/logs/` and the in-app log viewer. Set `CONSOLE_LOG_LEVEL=INFO` for verbose container logs.
- Fixed storage cleanup, the CSV export and the non-English species sort using too much memory on stations with long histories.
- Fixed installation on Ubuntu 25.10 and newer, where the service failed to start because `sudo-rs` rejected the installer's sudoers rules.
- Fixed the Dashboard staying on loading spinners when the first settings request failed.
- Fixed the setup wizard reporting "Failed to save settings" when the restart was only slow.
- Fixed the restart banner's timer freezing, and dismissed banners coming back or reloading the page.
- Fixed temporary recording files building up after an interrupted recording.
- Fixed Activity Overview rows getting taller with larger species limits.

## [0.8.3] - 2026-07-05

- Changed the Dashboard's latest observation card and Recent Observations names to open the detection player in place instead of the species page.
- Changed the detection player's scientific name to link to the species page.
- Changed Recent Observations to show Unique species by default.
- Fixed the setup wizard's address search, which the 0.8.2 security policy blocked.
- Fixed Docker build-cache cleanup never freeing space. The cache is now capped at 5GB; set `BUILD_CACHE_LIMIT` to change it.
- Fixed links doing nothing in tabs opened before an update. The app now reloads itself onto the intended page.
- Fixed the Dashboard showing "cannot reach the server" behind the login prompt when public access is off.
- Fixed the Dashboard polling in background tabs and showing stale data when you return.
- Fixed the detection player staying open when you click the species name inside it.
- Fixed the detection player's weather strip showing an empty cell.

## [0.8.2] - 2026-07-02

- Added an "Allow public access" switch (Settings → Security). With it off, everything requires sign-in.
- Added an analysis-window bar under the detection player's spectrogram showing which 3-second slice the model flagged. Click a slice to jump to it.
- Added link previews for shared detection links in apps such as iMessage, Slack and Discord.
- Changed the signed-out view, when authentication is on, to be enforced by the server and limited to recent activity. Older detections need a sign-in or a share link, and recordings are served through short-lived links so they can't be bulk-downloaded.
- Changed the detection Share button to create a link that opens only that detection, even on a private station.
- Changed signed-out visitors to no longer see source labels, the exact build commit, or (with public access off) the station name.
- Changed the detection player's spectrogram to fade filtered frequencies, as the Live Feed does.
- Improved security: the session cookie is marked Secure over HTTPS, the web server sends a Content-Security-Policy header and rate-limits API reads and logins, and internal endpoints require a shared secret.
- Improved API responsiveness on the Pi.
- Fixed audio source names and stream errors, which can include camera URLs, being sent to signed-out Live Feed viewers.
- Fixed the detection player stuttering in the first second on Safari and iOS, and the iPhone ringer switch muting it.

## [0.8.1] - 2026-06-28

- Added the live spectrogram and high-pass/gain filters to the Live Feed on Safari.
- Improved the high-pass and gain sliders on touch screens.
- Improved the Live Feed layout on phones, and centered the filter sliders in their panel.
- Fixed the Live Feed and Dashboard spectrograms scrolling at different speeds depending on the browser and screen.

## [0.8.0] - 2026-06-27

- Added share links for individual recordings, which open a dedicated player page.
- Added high-pass filter and gain controls to the Live Feed.
- Added the Table's page, filters and sort to its URL, so refresh, bookmarks and Back keep your view.
- Changed the shared detection page to a single card with spectrogram, playback and filter controls, confidence, weather and details. The eBird code links to eBird.
- Changed the species page's Recordings to use the same player, and moved downloads to the detection page.
- Changed the Table's info button to open the detection player in place.
- Changed the Live Feed spectrogram to match the detection player's look.
- Changed the Dashboard's latest observation spectrogram to a fixed brightness, like the Live Feed.
- Changed `/api/settings/defaults` to require sign-in.
- Improved dialogs to close consistently with the close button, the backdrop or Escape, except while busy.
- Fixed public API responses including the station's exact coordinates. The signed-in CSV export still includes them.
- Fixed the species page's Recordings showing clips whose audio had been cleaned up.
- Fixed the Live Feed's high-pass and gain controls showing on Safari, where they had no effect.
- Fixed three security advisories in frontend dependencies.

## [0.7.5] - 2026-06-20

- Added an optional "Normalize Recording" setting (Settings → Personalization) that makes faint detection clips easier to hear. It's off by default and doesn't affect detection.
- Added an "Always Include Species" list (Settings → Species Filter) for species the location filter would otherwise hide.
- Added an installer check that stops early on 32-bit operating systems.
- Changed spectrograms to a fixed loudness reference, so quiet detections look dim and loud ones bright.
- Fixed the Live Feed giving up when an RTSP source drops its audio. It now retries, and the stream Test button no longer times out too early.
- Fixed the installer failing when run from outside the cloned repo.
- Fixed the Dashboard's playback spectrogram scrolling blank columns while audio loads.
- Fixed long photographer names wrapping the photo credit onto a second line.

## [0.7.4] - 2026-05-31

- Added the "scroll to top" button to the Gallery.
- Changed Gallery tabs to show a spinner while loading.
- Improved handling of Wikimedia rate limits.
- Fixed Gallery thumbnails sometimes not appearing. Images are now smaller and load as you scroll.
- Fixed custom image choices loading the full-size original in the Gallery. Re-save older choices to fix them.
- Fixed RTSP sources timing out with some IP cameras. ffmpeg now tries TCP first and falls back to UDP.
- Fixed "Most Activity Time" on species pages ignoring the 24-hour clock setting.

## [0.7.3] - 2026-05-27

- Fixed choppy RTSP recordings from sources such as mediamtx.

## [0.7.2] - 2026-05-23

- Improved the Dashboard on slow devices such as the Pi Zero: a failed request no longer hides the whole Dashboard, and the last good data stays on screen.
- Fixed the unit and time-format toggles sometimes not applying.
- Fixed Gallery photos falling back to the placeholder after the first few species.
- Fixed long names making the Observation Summary card taller than the card next to it.
- Fixed the species page's Distribution chart sometimes going blank when resizing the window.

## [0.7.1] - 2026-05-21

- Changed the Dashboard summary to load other periods only when selected.
- Improved Gallery tab loading.
- Fixed Dashboard navigation freezing after the 0.7.0 server change.
- Fixed summary stats showing different names for the same species after switching from V2 to V3.
- Fixed the Charts and species pages flashing empty messages or blank charts while loading.
- Fixed Hourly Activity cells on the Charts page not linking to the Table.

## [0.7.0] - 2026-05-18

- Added an "Audio Status" notification (Settings → Notifications) that alerts when recording degrades, stops or recovers. It's off by default.
- Added Hourly Activity links into the Table: clicking an hour or a cell opens the Table filtered to it. The Table gained an Hour filter.
- Changed the API server to gunicorn instead of the Flask development server, and added a `/api/health` endpoint.

## [0.6.10] - 2026-05-12

- Fixed Hourly Activity tooltips ignoring the time-format setting.

## [0.6.9] - 2026-05-12

- Added a "Use 24-hour Clock" setting (Settings → Personalization) for times throughout the app. It defaults to your browser's format.
- Added species-page links to the species names on the Activity Overview bar chart.
- Changed the Charts and Table date pickers to follow the time-format setting.
- Fixed notifications ignoring the Bird Name Language setting.
- Fixed some species showing in English, or appearing twice after switching models, despite the Bird Name Language setting.

## [0.6.8] - 2026-05-08

- Added a "customize image" option on species pages to pick a different Wikimedia photo.
- Added click-to-pause on the live spectrogram.
- Changed the Latest Observation live spectrogram to match the saved image.
- Improved backend memory use.
- Fixed the Live Feed behind HTTPS reverse proxies and Cloudflare tunnels.
- Fixed the Latest Observation spectrogram axis not starting at 0 Hz.
- Fixed the Live Feed with Flask 3.1.3 by updating Flask-SocketIO.
- Fixed 25 Dependabot alerts in frontend dependencies.

## [0.6.7] - 2026-05-03

- Added recency-based recording protection: the newest recordings of each species are kept along with the highest-confidence ones.
- Added log diagnostics for when the system runs out of file descriptors.
- Changed the Dashboard's Latest Observation card to put the image and text side by side, with links to the species page and Table.
- Changed the species page's camera icon to an "Upload custom image" button.
- Changed the Activity Overview to hide the reverse toggle on days without detections.
- Improved the Latest Observation live spectrogram's colors and sharpness.
- Fixed recordings getting stuck in an endless reprocessing loop when a step after analysis failed.

## [0.6.6] - 2026-04-19

- Added a model picker step to the setup wizard and a one-time welcome animation after setup.
- Added a Home Assistant add-on pointer to the README.
- Fixed the setup wizard reopening on existing installs and overwriting the chosen model and filter threshold.

## [0.6.5] - 2026-04-18

- Fixed Pi OS Lite failing to start when PulseAudio left a stale socket behind.

## [0.6.4] - 2026-04-17

- Added in-app updates for the Home Assistant add-on.
- Improved how the app detects that a Home Assistant update has finished.
- Changed Settings in Home Assistant mode to drop the redundant badge and show the source and add-on repo links side by side.

## [0.6.3] - 2026-04-13

- Changed `/api/stream/config` to return relative stream URLs.
- Improved URL handling under Home Assistant ingress.
- Fixed the default bird image being broken on species pages.
- Fixed login error messages disappearing before you could read them.
- Fixed sign-in errors showing as a generic "Connection error".
- Fixed a Settings link that navigated away from the page.

## [0.6.2] - 2026-04-10

- Added automatic testing of RTSP streams when saving.
- Changed audio source pills to open the editor instead of toggling the source, to avoid accidental changes.
- Improved image downloads during updates: they are retried, run one at a time, fall back to a local build when needed, and disk space is freed first.
- Improved backend memory use.
- Fixed storage cleanup skipping files from multi-source detections, and reporting the wrong reason when it finished.
- Fixed several install and update script issues, including lost error messages, argument handling, and a background monitor restarting containers after stop.
- Fixed the audio status indicator on stations using a non-standard port.
- Fixed the Live Feed under Home Assistant ingress.
- Fixed the Live Feed showing empty pills for unlabeled RTSP streams.
- Fixed the setup wizard needing a second click after "Finish anyway".
- Fixed keyboard access for source and notification pills.

## [0.6.1] - 2026-04-05

- Added multi-language bird names for BirdNET V3.0.
- Added the auto-cleanup trigger percentage to the Settings storage card.
- Changed location changes to apply without a restart.
- Changed recorder health to a signed-in endpoint (`/api/recorder/status`), so source names and errors aren't shown to guests.
- Fixed a login prompt appearing for guests on the Dashboard when the Live Feed was private.
- Fixed the recorder health indicator needing a reload after login.
- Fixed the restart timer showing the wrong elapsed time.
- Fixed swap setup on low-memory systems.
- Fixed the settings save message overlapping the heading on phones.

## [0.6.0] - 2026-04-02

- Added multi-source audio recording: record from several microphones and RTSP streams at once.
- Added a two-step setup wizard for location and audio sources.
- Added pre-built ARM64 Docker images, so installs and updates download images instead of building locally.
- Added editing of notification services.
- Added a warning pill on every page when audio sources have problems.
- Added a 200-per-page option and a scroll-to-top button to the Table.
- Changed detection filenames to use the source label instead of its ID.
- Improved notification URL handling, including removing duplicates.
- Fixed cropped spectrogram images.
- Fixed several issues moving audio settings to the multi-source format.
- Fixed per-source error details, recorder health starting late, and stale health after a restart.
- Fixed changing only a source's label restarting services.
- Fixed filename collisions when two source labels clean up to the same name.
- Fixed zero-confidence species being kept as candidates when the cutoff is 0.
- Fixed several update script issues, including `.env` settings being overwritten during image downloads.
- Fixed a security advisory in a frontend test dependency.

## [0.5.8] - 2026-03-25

- Added location-based species filtering for BirdNET V3.0, using the bundled geomodel.
- Added a "new species" notification for species never detected before.
- Added localized bird names for BirdNET V3.0 species shared with V2.4.
- Added an All/Unique toggle to the Dashboard's Recent Observations.
- Added recorder status to Settings.
- Added stream URL testing and a redesigned audio source picker.
- Added a species filter threshold setting.
- Added a system logs viewer and a restart services button to Settings.
- Added the timezone to the Location settings.
- Changed RTSP stream changes to save immediately.
- Changed the Settings layout: Location and Audio Source share a card, and Management is collapsible.
- Improved spectrogram generation speed.
- Fixed the V3.0 geomodel threshold being replaced by the V2.4 default.
- Fixed "too many open files" errors.
- Fixed location changes not updating the timezone until a restart.
- Fixed Icecast timestamps not being converted to local time.
- Fixed inconsistent row heights in Bird Activity Overview.
- Fixed the unique species list sometimes showing too few species.
- Fixed Dashboard toggles resetting during a refresh.
- Fixed RTSP label-only edits not being saved.
- Fixed recorder status showing a stale value after recovery.

## [0.5.7] - 2026-03-07

- Added bird names in 26 languages, chosen in Settings.
- Added per-feature access control: Charts, Table and Live Feed can each be public or private.
- Added a station name setting.
- Added a login button in the header when authentication is on.
- Changed the Settings page into collapsible sections.
- Changed the login prompt to keep you on the current page.
- Changed the language selector to be disabled for BirdNET V3, which had no localized names yet.
- Improved Live Feed error messages.
- Fixed RTSP errors with cameras that send video or bad timestamps.
- Fixed Wikimedia image search returning non-bird images.
- Fixed the bird name language setting needing a restart.
- Fixed the Live Feed not showing the login prompt on an auth error.
- Fixed being sent to the wrong page after login.
- Fixed the Docker build cache growing without limit.

## [0.5.6] - 2026-03-04

- Added Home Assistant add-on support.
- Added the add-on repository link and source commit to Settings in Home Assistant mode.
- Fixed Home Assistant ingress stream settings and the default bird image.

## [0.5.5] - 2026-03-02

- Added notifications via Apprise, with a service picker and built-in test.
- Added notification triggers: every detection (with a per-species cooldown), first of the day, and rare species.
- Added hot-apply: most settings now take effect without restarting services.
- Added a species limit (10/20/30/All) to Bird Activity Overview.
- Added selective rebuilds during updates, and `--services` and `--version-only` flags for `build.sh`.
- Changed Bird Activity Overview to grow with the number of species.
- Changed the recordings sort control to a toggle.
- Changed the version display to version(commit).
- Fixed several notification issues, including MQTT not working and unclear test errors.
- Fixed build and update failures going unnoticed.
- Fixed the species filter dialog not closing after saving.
- Fixed a crash when analyzing stale audio files.
- Fixed the GitHub link in Settings.

## [0.5.4] - 2026-02-19

- Added page caching, so going back to the Dashboard or Gallery is instant.
- Changed the Dashboard to load from a single API request (`/api/dashboard`).
- Changed the Dashboard to pause updates while its tab is hidden.
- Changed charts to update in place instead of redrawing.
- Fixed the Dashboard briefly showing empty states before loading.
- Fixed older responses overwriting newer data.
- Fixed bird images not retrying after a failed fetch.
- Fixed chart animations when returning to a page.
- Fixed polling problems when the API is slow or after leaving the page.

## [0.5.3] - 2026-02-16

- Added an eBird link to species pages.
- Added a sort toggle to Bird Activity Overview (later replaced by showing all species).

## [0.5.2] - 2026-02-15

- Fixed the version showing as "unknown" on Pi installs.

## [0.5.1] - 2026-02-15

- Added custom bird image uploads in the Gallery.
- Added a GitHub repository link and the version number to Settings.
- Fixed a misleading download banner when switching models.
- Fixed custom image credit alignment in Gallery cards.

## [0.5.0] - 2026-02-13

- Added BirdNET V3.0 model support (11K species), downloaded on first use. If the download fails, the app keeps running and retries on the next restart.
- Added a Table link to the navigation bar.
- Changed "Bird Gallery" to "Gallery" in the navigation.
- Fixed unused Docker images building up on the Pi after each rebuild.
- Fixed an invalid model type in settings crashing the service.
- Fixed a security advisory in axios.

## [0.4.0] - 2026-02-05

- Added BirdNET-Pi migration: import past detections and audio, and generate spectrograms, from Settings.
- Added BirdWeather uploads of detections and audio.
- Added weather data from Open-Meteo to detections, shown in the detection details.
- Added automatic update checks with a dismissible button on the Dashboard.
- Added a metric/imperial unit setting.
- Added offline timezone detection from coordinates.
- Added a warning for unsaved changes on the Settings page.
- Added a `--branch` option to `install.sh`.
- Changed location setup to be required before detection starts.
- Changed recording filenames to use dashes instead of colons in times.
- Changed latitude and longitude inputs to two decimal places.
- Changed date pickers to look the same in every browser, with checks against future or reversed dates.
- Fixed being able to turn on authentication without a password through the API.
- Fixed the Dashboard not loading when authentication is on and you're not signed in.
- Fixed the spectrogram resetting during playback, and the live spectrogram not starting on the Dashboard.
- Fixed services restarting when settings didn't change.
- Fixed shutdown handling and PulseAudio socket permissions.
- Fixed BirdNET-Pi audio import missing files with different timestamp separators, and parallel imports when leaving and returning to the page.
- Fixed date pickers on phones, including iOS zooming in.
- Fixed the location check rejecting coordinates at 0° latitude or longitude.
- Fixed an audio queue cleanup error when the buffer is full.

## [0.3.2] - 2026-01-17

- Improved Live Feed error handling and status messages for network errors, stream end and buffering.
- Added stream connection logging in the Icecast container.
- Changed the Live Feed to hide the stream description on phones.
- Fixed toggle buttons getting cut off on phones in Settings.

## [0.3.1] - 2026-01-10

- Added a Detection Trends chart.
- Changed default bird images to WebP for smaller files.
- Improved chart navigation and label spacing.
- Fixed chart control alignment on phones.
- Fixed smart cropping for portrait bird images.

## [0.3.0] - 2026-01-10

- Added smart cropping to center the bird in its photo, and a fade when switching images.
- Added an update channel setting: stable releases or the latest development builds.
- Changed the Wikimedia image cache from 24 to 48 hours.
- Improved update messages, including when switching channels.
- Fixed updates for installs ahead of the latest stable release, on a detached HEAD, or with untracked files.

## [0.2.0] - 2026-01-02

- Added eBird species codes, model name and version to detections.
- Added a detection details window with model info, eBird code and timestamps.
- Added CSV export of detections from Settings.
- Added batch delete to the detections table.
- Added release notes to system updates.
- Added auto-save to the species filter.
- Added an `--update` flag to `install.sh` for updating system configuration without a full reinstall.
- Added a privacy policy.
- Changed the default port from 8080 to 80.
- Changed the species filter to show common names.
- Changed the install completion message to show the hostname and IP address.
- Improved the Settings, Gallery and species page layouts.
- Fixed the live feed reload not jumping to the current position.
- Fixed PipeWire audio on desktop systems.
- Fixed the systemd service's restart limit setting.
- Removed geolocation from location setup, since it needs HTTPS.

## [0.1.0] - 2025-11-28

First public release.

- Added a one-line install for Raspberry Pi.
- Added in-app update checks and installation.
- Added storage usage display and automatic cleanup (keeps the top 60 recordings per species).
- Added optional password protection for settings and the audio stream, with login rate limiting.
- Added an automatic reboot after installation, and an installation log.
- Changed audio loading from librosa to scipy for faster startup.
- Fixed memory leaks in Dashboard audio playback.
- Fixed thread hangs with proper timeouts.

---

## Pre-release

### August-November 2025

- Added PulseAudio for sharing audio between containers.
- Added Icecast streaming for browser audio playback.
- Added an nginx reverse proxy so everything is on port 80.
- Added support for USB microphones, HTTP streams and RTSP cameras.
- Added configurable overlap between audio chunks for better detection at boundaries.
- Added Docker Compose deployment with a systemd service.
- Added a single `build.sh` script to build and deploy everything.
- Added a test suite for the backend and frontend.
- Added input validation, CORS and secure headers.
- Changed spectrograms from PNG to WebP for smaller files.

### June-July 2025

- Added structured logging across backend services.
- Improved API response sizes for the Raspberry Pi.
- Improved charts with hourly and daily ticks and grid lines.
- Improved spectrogram file sizes.

### May-June 2025

- Added the Charts view with day, week and month navigation.
- Added real-time detections via Socket.IO.
- Added FFmpeg and Icecast for browser audio streaming.
- Added settings management with restarts only when needed.
- Added phone-friendly layouts.
- Fixed Safari chart rendering and dropdown styling.
- Fixed page routing in Docker.

### August 2024

- Added the species page with detection history and charts.
- Added a paginated recordings section with sort options.
- Added audio playback for bird calls.
- Added Docker containers for the frontend and backend.
- Added a Settings page for recording source, location and confidence threshold.
- Improved spectrogram styling.

### July 2024

- Added the Vue.js 3 frontend.
- Added the Dashboard with a detection summary, recent observations and activity charts.
- Added the Bird Gallery with Wikimedia images.
- Added Chart.js charts for detection distribution.
- Added WebSocket support for live updates.

### November 2023

- Created the project.
- Added a Flask backend with REST API endpoints.
- Added a SQLite database for detections.
- Added BirdNET TensorFlow Lite model integration.
- Added basic audio recording and processing.
- Added spectrogram generation using matplotlib.
