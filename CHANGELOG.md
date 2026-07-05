# Changelog

## [Unreleased]

- Fixed Docker build-cache cleanup never actually reclaiming space after builds and updates — modern Docker silently ignores the age filter the scripts relied on, so stations that build locally accumulated tens of GB of stale cache over time. Cleanup now caps the cache at 5GB (override with `BUILD_CACHE_LIMIT` as an environment variable or `.env` entry), evicting the oldest entries first so recent layers stay warm for fast rebuilds
- Changed the dashboard's latest observation card (image and names) and the recent observations list's bird names to open that detection's player in place when clicked, instead of navigating to the species page; Ctrl/Cmd/middle-click still opens the detection's own page in a new tab. The card's timestamp is now plain text (it previously opened the detections table)
- Changed the detection player's scientific name to link to the species page, matching the common name above it, and added a small link icon next to the common name so the navigation is discoverable
- Fixed the detection modal staying open when clicking the species name inside it — the page behind changed while the modal lingered on top; it now closes on any in-app navigation
- Fixed the setup wizard's address search always failing ("Search failed. Please try again or enter coordinates manually.") — the 0.8.2 security policy blocked the browser's request to the OpenStreetMap geocoding service; it is now explicitly allowed
- Fixed clicks on species and page links doing nothing in browser tabs loaded before an update ("Failed to fetch dynamically imported module" in the console) — the app now recovers by reloading itself onto the intended page, and the web server tells browsers to always revalidate the app shell so a stale build doesn't linger in cache after an update

## [0.8.2] - 2026-07-02

- Added an analysis-window bar under the detection player's spectrogram showing which 3-second slice of the clip the model actually flagged (the rest is context audio around it); click a tile to jump playback there. When the same species also fired in neighboring slices of the same recording, those windows are marked too, so a clip with back-to-back calls doesn't read as one detection surrounded by silence
- Improved API responsiveness on the Pi: the auth configuration is now cached instead of re-read from disk several times per request, hot access checks skip a full settings copy, and signed media links are only minted for logged-out viewers (owners' detection payloads slim down since their session already authorizes playback)
- Added an "Allow public access" switch (Settings → Security): with authentication enabled you can keep a limited public view (dashboard, gallery, and bird pages without login) or turn it off to require sign-in for everything. When off it also overrides the per-feature public toggles, and the station name is no longer shown to logged-out visitors
- Hardened the API so enabling authentication actually keeps detection data private: the logged-out view is now enforced and bounded server-side (it previously left many endpoints open, so a script could rebuild the database even with the Table hidden), and is limited to recent activity — logged-out visitors get a capped, recent window per species and can no longer open or play older detections by guessing or walking permalink URLs (older ones need a login or a share link), and a published Table likewise shows them only the recent window. Login rate-limiting can't be bypassed via a forged forwarding header, the internal detection-broadcast endpoints now require a shared secret, and a default-deny backstop keeps any future endpoint private to logged-out visitors unless explicitly opened
- Closed the last logged-out scraping hole for media: with authentication enabled, detection audio and spectrogram files are served only via short-lived signed links that the dashboard, gallery, and bird pages mint for the clips they show — so a logged-out visitor can still play those clips, but the recordings can no longer be bulk-downloaded by guessing filenames. Signed-in owners are unaffected
- Tightened what logged-out visitors can see further: per-detection source labels (and the internal source id) are stripped from public responses, and the system info endpoints (version, storage, update check) are now part of the limited public view rather than readable behind the login wall
- Fixed recorder health (audio source names and stream error text, which can include camera URLs/credentials) being pushed to logged-out viewers over the live-feed WebSocket when the live feed is public — it now goes only to signed-in owners, matching the authenticated status endpoint
- Hardened the public version info: logged-out visitors now see only the version number, not the exact build commit and branch (which fingerprint the build for known-vulnerability matching); signed-in owners still see full details
- Improved transport hardening: the session cookie is now marked Secure automatically when the station is reached over HTTPS (e.g. behind a TLS proxy or tunnel), so it can't be replayed over a downgraded plain-HTTP hop, while plain-HTTP LAN logins keep working; the web server also sends a Content-Security-Policy header (permitting WebAssembly compilation, which the Live Feed's Safari stream decoder needs) and rate-limits the API read path (with a tighter budget on login attempts), so a scraper can't turn the bounded public view into a bulk download by request volume
- Changed the detection "Share" button to create a scoped share link: the link opens that one detection (its player, spectrogram, and clip) for someone without an account — even on a fully private station — but can't be edited to browse other detections, so sharing one sighting never exposes the rest
- Fixed the detection player stuttering in the first second of playback on Safari and iOS — the audio and the moving playhead would briefly freeze then jump. Playback now feeds the decoded audio straight through Web Audio instead of routing an `<audio>` element, which avoids a Safari startup glitch; the player declares a "playback" audio session so the iPhone ringer switch doesn't mute it, and recovers after a phone call or backgrounding
- Changed the detection player's spectrogram to reflect the high-pass filter the same way the Live Feed does — cut frequencies gently fade instead of being hidden under a heavy black overlay, so the picture matches what the filter does to the audio
- Added rich link previews for shared detection permalinks — pasting one into iMessage, Slack, Discord, etc. now unfurls into a card with the bird's photo, species, confidence, and time. On an authenticated station the card details only what a logged-out visitor could open (recent detections, or any detection via its share link); anything else unfurls as a generic branded card

## [0.8.1] - 2026-06-28

- Fixed the Live Feed and Dashboard playback spectrograms scrolling at different speeds across browsers and displays — they advanced a fixed step per animation frame, so speed tracked the refresh rate (e.g. Safari vs Chrome, or 60 Hz vs 120 Hz screens) and a given call rendered wider or narrower per screen. Both now scroll at a fixed rate in real time, so audio features keep a consistent size on any display
- Added the live spectrogram and high-pass/gain filters to the Live Feed on Safari, which couldn't show them before — Safari can't tap a live stream through Web Audio the normal way, so the audio is now decoded in-browser and fed through the same graph (it falls back to plain playback if the decoder can't load)
- Improved the high-pass and gain sliders for touch — the thumb and track are larger on phones and tablets so they're easier to grab and harder to miss, while the desktop slider is unchanged
- Polished the high-pass/gain filter panels on the Live Feed and detection player — the sliders now sit vertically centered in the grey panel instead of low (the slider thumb was poking into the panel's bottom padding), and the Live Feed's live spectrogram is a bit shorter on small screens
- Tightened the Live Feed layout on phones — smaller gaps, padding, and slider thumb plus a slightly shorter spectrogram, so the first detection shows without scrolling as far; desktop spacing is unchanged

## [0.8.0] - 2026-06-27

- Fixed the public detection/observation/recording API responses leaking the station's exact coordinates — latitude/longitude are now stripped at the data layer so these endpoints stay private-by-default while share permalinks keep working without login. The authenticated CSV export still includes coordinates
- Changed `/api/settings/defaults` to require authentication, since it carries the default station coordinates and is only used as an authenticated-load fallback
- Added shareable permalinks to individual recordings — a "Share" button copies a deep link that opens a dedicated player page (spectrogram, audio player, download), so you can point others at a specific detection instead of just the species
- Changed the species page's Recordings grid to use this same custom player instead of the browser's default audio bar, so playback and sharing are consistent everywhere; per-clip download moved to the detail page
- Fixed the bird detail page's Recordings grid showing dead players and placeholder spectrograms for detections whose audio had been cleaned up — such records are now skipped so the grid only shows playable clips
- Changed the shared detection player page to a single-card layout — a framed spectrogram with time axis, unified playback and high-pass/gain controls, a confidence score, and weather plus detection metadata inline, with the eBird code now linking out to that species' eBird page
- Changed the Detections table's per-row info button to open the full detection player in an in-place modal instead of a small info modal, so you keep your place in the table; ⌘/Ctrl/middle-click still opens it in a new tab
- Added the current page, filters, and sort to the Detections table's URL, so a refresh, bookmark, or Back button restores the exact view instead of snapping back to page 1
- Improved modal dismissal consistency — viewer, settings, confirmation, and workflow dialogs now close via the close button, backdrop, or Escape when safe, while saving/testing/processing states still block accidental dismissal
- Added live high-pass filter and gain controls to the Live Feed, matching the detection player — filter out low-frequency rumble (which also clears from the live spectrogram) and boost quiet audio, all non-destructively while listening
- Changed the Live Feed spectrogram to match the detection player's look — same green palette, 0–12 kHz range, and contrast — so the live and recorded views read as one instrument
- Changed the Dashboard's Latest Observation spectrogram to a fixed brightness window (matching the Live Feed) instead of auto-gaining to the loudest sound, so brightness stays steady during playback rather than fluctuating
- Fixed the Live Feed's high-pass and gain controls showing on Safari, where they had no effect — Safari doesn't route the live stream through Web Audio (the same reason the live spectrogram is unavailable there), so the controls are now hidden with a note that audio still plays
- Updated frontend dependencies (form-data, ws, js-yaml) to clear three Dependabot security advisories

## [0.7.5] - 2026-06-20

- Fixed the Dashboard's live playback spectrogram scrolling through blank columns while audio is still loading or buffering — the canvas now only advances while real audio is playing
- Added an early installer check that stops on 32-bit OSes with a clear "reflash with the 64-bit image" message — BirdNET-PiPy is arm64-only, and previously the install aborted partway through with a blank web UI
- Fixed the installer aborting when run from a directory other than the cloned repo, and restored the dev-branch "building locally" detection that a `--skip-build` shortcut had bypassed
- Added an optional "Normalize Recording" toggle (Settings → Personalization) that loudness-normalizes saved detection clips so faint or distant birds are easier to hear. It runs after BirdNET analysis so detection is unaffected, applies to new recordings only, and is off by default
- Added an "Always Include Species" list (Settings → Species Filter) that reports the listed species even when the location filter rates them unlikely for your coordinates
- Fixed long photographer names wrapping the "Photo by …" image attribution onto a second line — the name now truncates with an ellipsis in gallery cards, bird detail pages, and the image picker
- Fixed the Live Feed giving up with "Could not start audio playback" when an RTSP audio source drops mid-stream (some cameras periodically end their audio track) — the player now retries with backoff and self-heals instead of forcing a manual restart. Also fixed the stream "Test" button timing out before the backend probe could answer, and showing a generic "Test request failed" instead of a timeout-specific message
- Changed spectrograms to use an absolute full-scale dBFS reference instead of per-clip auto-gain, so loudness is comparable across recordings — quiet detections render dim and loud ones bright, instead of every clip being peak-normalized to its own maximum

## [0.7.4] - 2026-05-31

- Changed Bird Gallery tab switches to show a loading spinner while an uncached tab's query runs, instead of leaving the previous tab's cards on screen until it resolves. Revisiting a cached tab is still instant
- Added the "scroll to top" button to the Bird Gallery (previously only on the Detections table); the bottom-right status indicators now yield the corner so they no longer overlap it
- Fixed Bird Gallery thumbnails intermittently not appearing — the gallery now serves Wikimedia's smaller thumbnail and loads card images lazily as they near the viewport, instead of fanning out a lookup for all ~200 species when the Species Catalog opens
- Fixed saved "customize image" choices still loading the full-resolution original in the gallery — a choice now stores and serves a thumbnail (re-save older choices to shrink them)
- Hardened the Wikimedia image proxy against rate limiting — a 429 surfaces the upstream `Retry-After` instead of a 500, concurrent misses for the same species share one fetch, and gallery lookups skip Wikimedia for species that already have a custom image
- Added a contact URL to the Wikimedia API `User-Agent` per Wikimedia's policy, keeping the app in the 200 req/min identified tier rather than the 10 req/min "unidentified" tier
- Fixed the "Most Activity Time" on a bird's detail page ignoring the "Use 24-hour Clock" preference and always showing 24-hour time
- Fixed RTSP audio sources (e.g. some IP cameras) timing out when added or recorded even though the stream plays in VLC — ffmpeg now prefers TCP with UDP fallback instead of forcing TCP, with longer connection-test timeouts for slow handshakes

## [0.7.3] - 2026-05-27

- Fixed RTSP audio recordings being choppy from well-behaved producers such as mediamtx restreaming a local capture — an `aresample` ffmpeg filter (added earlier to handle IP cameras with non-monotonic timestamps) was injecting silence and warping samples in response to ordinary network jitter, and has been removed from the recorder and live stream

## [0.7.2] - 2026-05-23

- Improved dashboard resilience on slow devices such as the Raspberry Pi Zero, where API requests routinely exceed the frontend's timeout — a failed `/settings` request no longer hides the whole dashboard, a failed refresh keeps the last-good data on screen, request timeouts are sized per endpoint, and navigation no longer blocks on an `/auth/status` roundtrip
- Fixed the metric/imperial unit and time-format toggles in Settings silently failing to apply when the settings store hadn't loaded — they now propagate their change directly
- Consolidated frontend settings handling — `/settings` is now fetched once into a shared store that feeds the unit and time-format composables, replacing several independent fetch sites
- Fixed Bird Gallery cards intermittently falling back to the placeholder after the first ~8-9 species — the image worker pool added in 0.7.1 fired too many concurrent Wikimedia hits and tripped the burst throttle, so image loads are now serialized
- Fixed the Dashboard's Observation Summary card growing taller than the adjacent Latest Observation card at narrow widths when long bird names wrapped — names now truncate to a single line (full name on hover, click still opens the species page)
- Fixed the Distribution chart on bird detail pages occasionally rendering blank when the window was resized quickly — competing resize handlers were racing and latching a 0-width canvas, and now defer to Chart.js's built-in resize handling

## [0.7.1] - 2026-05-21

- Sped up Bird Gallery tab loading — the Species Catalog drops its per-species API fan-out, sightings are computed in one query instead of three table scans, results are cached, and card images load in the background without blocking the tab switch
- Changed Dashboard Summary to load only the visible Today tab up front and lazy-load 7-Day, 30-Day, and All Time on selection, keeping the initial payload small
- Fixed dashboard navigation freezing after the 0.7.0 gunicorn+gevent migration — the dashboard's sequential SQLite queries blocked the single event loop, stalling concurrent requests; DB work now runs on a dedicated thread executor with short-TTL caching
- Fixed dashboard summary stats (Most Common, Rarest, Most Active Hour) showing inconsistent species names across periods after a V2→V3 upgrade — each species now resolves to one canonical name, with alphabetical tie-breaks so low-activity picks no longer flap
- Fixed the Charts page flashing empty-state messages during the initial fetch, a stale chart leaking on a failed refetch, and a mount race that left the trends canvas blank — loading, error, and empty are now distinct states
- Fixed the bird detail page flashing "No recordings available" and a blank distribution chart during the initial fetch — each now shows a spinner until its data loads, and a slow image lookup no longer stalls the others
- Fixed Hourly Activity heatmap cells not deep-linking into the Table on the Charts page

## [0.7.0] - 2026-05-18

- Added an "Audio Status" notification trigger (Settings → Notifications): when an Apprise URL is configured and the toggle is on, audio-pipeline degradation and recovery are pushed as notifications — one alert on degrade/stop (with the affected source and last ffmpeg error), an escalation if it worsens to fully stopped, and one recovery alert. Flapping streams are debounced (10-min cooldown) and startup never alerts. Off by default; the Notifications section subtitle is broadened to "Detection and system status alerts"
- Made the Hourly Activity heatmap a drill-down into the Table: clicking an hour label filters the Table to that day/hour, clicking a cell also filters by species. Adds a desktop "Hour" dropdown and an `hour` (0–23) param on `/api/detections`. Clearing filters now also strips the `date`/`hour`/`species` URL params, so a shared "cleared" view stays cleared
- Upgraded the frontend build to Vite 7 and `@vitejs/plugin-vue` 6, dropping the no-longer-needed `esbuild >=0.25.0` override
- Replaced the Werkzeug dev server with gunicorn + a single gevent WebSocket worker for the API container, dropping the `allow_unsafe_werkzeug` override. The single worker is intentional: live detections fan out via in-process `socketio.emit` (no Redis queue), so extra workers would silently drop Live Feed broadcasts — heavy maintenance jobs now cooperatively yield to keep it responsive. Added an unauthenticated `/api/health` route with a docker-compose healthcheck, and raised the nginx `/socket.io/` proxy timeout to 3600s so idle Live Feed sockets aren't reaped. Local `python -m core.api` still uses the threading dev server

## [0.6.10] - 2026-05-12

- Fixed Hourly Activity bar chart and heatmap tooltips still showing raw 24-hour labels regardless of the time-format toggle — they now run through the same `formatHourLabel` helper the x-axes already use, so 12-hour users see "2 PM" and 24-hour users see "14:00" consistently between axis and hover (follow-up on #49)

## [0.6.9] - 2026-05-12

- Extended the time-format preference to the Charts and Table date pickers — 12-hour users still see MM/DD/YYYY, 24-hour users now see ISO YYYY-MM-DD instead of the hardcoded US layout. The Table's From/To row also stretches edge-to-edge on mobile so the To picker's right edge lines up with the Species input below instead of clumping left (follow-up on #49)
- Added a "Use 24-hour Clock" toggle in Settings → Personalization that drives every time-of-day display across the app — Recent Detections list, Latest Observation timestamp, Table, Most Active Hour summary, and the Hourly Activity bar chart and heatmap x-axes. Defaults to the browser's locale on first run; the setting is only persisted once the user explicitly flips it, so existing installs aren't migrated and the toggle reflects what the OS already shows. Fixes #49, where the Hourly Activity bar chart hardcoded 12-hour AM/PM regardless of OS setting while sibling charts and lists deferred to the browser locale — producing a mix of 12h and 24h labels on the same Dashboard. Also fixes an `Intl.DateTimeFormat` quirk where `hour12: false` on `en-US` rendered midnight as "24:30" instead of "00:30" (now uses explicit `hourCycle: 'h23'`)
- Fixed Apprise notifications ignoring the Bird Name Language setting — title and body always rendered the English string straight off the model output; they now follow the user's chosen language via the same scientific-name lookup the web UI uses (#47)
- Fixed inconsistent Bird Name Language rendering across the web UI and duplicate-species rows on the Dashboard. ~17% of V2 species (e.g. "Eurasian Blackbird" for Turdus merula, vs the species table's canonical "Common Blackbird") missed the English-keyed translation and rendered in English on the Activity Overview, Charts, and Heatmap; the same species emitted under different English names by V2 vs V3 also appeared as two rows after a model switch — one translated, one not. Bird-name routes now resolve any known English variant (canonical, label_en, label_en_uk) to a stable scientific name at the API boundary, aggregations group by that key, and `/api/bird/<any-english-variant>` serves the combined V2+V3 history (#48)
- Added a WebSocket handshake regression test that exercises the real Flask-SocketIO test client instead of mocking `socketio` — would have caught the 0.6.8 Live Feed outage where Flask-SocketIO 5.5.1 crashed on Flask 3.1.3's read-only `RequestContext.session` (b6b0f26)
- Made species names on the Bird Activity Overview's Total Detections bar chart clickable — y-axis labels now link to each species's detail page on both the Dashboard and Charts views, and middle-click / "open in new tab" / keyboard focus all work as on any other text link. Implemented as an HTML overlay over the Chart.js canvas (canvas-rendered text can't be hyperlinks) with the overlay font matched to Chart.js's tick font so the labels don't render wider than they used to

## [0.6.8] - 2026-05-08

- Added a "customize image" modal on bird detail pages — pick a different Wikimedia thumbnail per species; the choice persists across redeploys as a sidecar and the gallery is live-patched on apply without a reload. Wikimedia rate-limits (429) now surface as a friendly retry-later message
- Added click-to-pause on the live spectrogram canvas — clicking pauses playback (preserving position); a suspended AudioContext is also resumed on play, so backgrounded tabs no longer render silent visuals
- Refined the Latest Observation live spectrogram to match the saved PNG — uses matplotlib's actual `Greens_r` ramp and per-playback rolling-peak dBFS normalization, with a midtone gamma lift and light analyser smoothing for a soft noise floor
- Reduced backend memory usage by ~100 MB across the three Python processes — multi-language species table now uses columnar arrays with lazy per-language loading (active per-process footprint drops from ~21 MB to ~4 MB), shared strings are interned, and the inference server no longer reads the multi-language CSV
- Fixed Live Feed breaking behind HTTPS-terminating reverse proxies and Cloudflare tunnels — inner nginx was overwriting `X-Forwarded-Proto` with `http`, causing Engine.IO to reject the browser's `https://` origin on `/socket.io/` POSTs; the header is now passed through verbatim
- Fixed the dashboard's Latest Observation spectrogram axis starting above 0 Hz — live canvas and saved PNG now align at 0 Hz
- Bumped Flask-SocketIO to 5.6.1 for Flask 3.1.3 compatibility
- Bumped frontend dependencies to clear 25 Dependabot alerts

## [0.6.7] - 2026-05-03

- Fixed audio recordings getting stuck in an infinite reprocess loop when post-analysis steps (audio extraction, spectrogram generation, BirdWeather upload, etc.) raised — the same WAV would be re-collected on the next scan and retried forever, spamming logs with duplicate "Bird detected" lines and amplifying the FD pressure that caused the failure. The processing loop now isolates per-file and per-detection failures and always removes the WAV in a `finally` block (#46)
- Added file descriptor exhaustion diagnostics — when an EMFILE/ENFILE error is detected anywhere in the recording or processing pipeline, the next log line dumps the FD limit, current FD count, a sample of open FDs with their `/proc/self/fd` targets, and active child PIDs (catches zombie ffmpeg/sox processes holding pipes via leaked refs). Rate-limited per stage. Errno detection walks `__cause__`/`__context__`/`args` plus urllib3-style `.reason`, so EMFILE buried inside a `requests.ConnectionError(MaxRetryError(...))` chain is caught
- Added recency-based recording protection — the latest N recordings per species are now retained alongside the existing top-N-by-confidence rule via union, so frequent recent activity isn't lost when its confidences fall below the top-N cut
- Hid the Bird Activity Overview reverse toggle on days with no detections, since reversing an empty list is a no-op
- Replaced the camera icon on bird detail pages with an upload arrow that animates open on hover to reveal "Upload custom image"
- Redesigned the dashboard's Latest Observation card — bird image and text stack now sit side-by-side instead of vertically; the scientific name is shown again as a link to the bird's detail page, and the timestamp and confidence link to the Table view; long species names wrap to a second line instead of being clipped mid-word; a thin vertical divider separates the bird identity area from the spectrogram, which sits visually centered between the divider and the card edge
- Polished the Latest Observation live spectrogram rendering — palette now matches the static spectrogram's `Greens_r` style (light background, dark green peaks), the canvas renders at 2× internal resolution for sharper downsampled output, and each new column is drawn as a horizontal gradient from the previous frame's intensities so time-axis transitions are continuous rather than stepped

## [0.6.6] - 2026-04-19

- Added a model picker step to the setup wizard and a one-time welcome animation after setup completes
- Fixed setup wizard silently reopening on existing installs and overwriting the chosen model and species filter threshold
- Added a Home Assistant add-on pointer in the README (alexbelgium's hassio-addons repo)

## [0.6.5] - 2026-04-18

- Fixed Pi OS Lite boot failing when a stale PulseAudio socket was left behind after the daemon died — the service now probes the existing socket with `pactl info` and resets stale runtime files before starting system-wide PulseAudio, rather than booting containers that later crash in ffmpeg with "No such process" (#42)

## [0.6.4] - 2026-04-17

- Added in-app update support for the Home Assistant addon — the Settings update card now checks the addon repo for new versions and triggers Supervisor to install them, replacing the "go to the Add-on Store" instruction
- Replaced the brittle "interpret dispatch errors" approach to detecting HA update completion with a poll of `/system/version` every 10 seconds; the page auto-reloads once the new addon container reports its version, with a 10-minute fallback message. Real backend errors (slug lookup, entity not ready) are surfaced immediately instead of waiting out the timeout
- Cleaned up Settings in HA mode: dropped the redundant "HA mode" badge and addon-repo link, kept the source-repo and addon-repo links side-by-side

## [0.6.3] - 2026-04-13

- Fixed silent regression where the default bird placeholder image was broken on individual bird detail pages (`/bird/:name`) in standard (non-HA) deployments — path resolution dropped the route segment, producing 404s that nginx's `error_page` masked by returning `index.html` as image bytes
- Fixed login error messages flashing and disappearing — the global 401 interceptor was racing with the auth endpoint's own error handling and clearing `error.value` before the user could read it
- Fixed `<a href="#system-updates">` in Settings that would have navigated away from the page under the new `<base href>` — replaced with a button and imperative scroll
- Unified deployment base-path handling via a single `<base href>` contract — the frontend declares `BASE` once from `index.html`, and axios/socket.io/router all derive from it; removes five parallel URL-shape mechanisms that had produced double-prefix bugs under HA ingress
- Set Vite `base: './'` so built `<script>`/`<link>` tags resolve via `<base href>`, enabling the HA addon to use a single nginx rewrite (down from seven `sub_filter` rules)
- Migrated internal auth calls from `fetch` to the central axios client — server error messages now surface properly instead of being mapped to generic "Connection error"
- Backend `/api/stream/config` now returns relative stream URLs (no leading slash); the frontend no longer strips the slash client-side

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
