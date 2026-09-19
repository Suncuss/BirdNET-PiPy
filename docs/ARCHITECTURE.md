# Architecture

BirdNET-PiPy uses a containerized microservices architecture with five Docker containers.

## Container Details

| Container | Port | Technology | Purpose |
|-----------|------|------------|---------|
| **frontend** | 80 | Nginx + Vue.js 3 | Web dashboard, SPA routing, API/stream proxy |
| **api** | 5002 | Flask + Socket.IO | REST API, WebSocket events, database access |
| **model-server** | 5001 | TFLite (V2.4) / ONNX (V3.1) | AI model inference, species detection |
| **main** | - | Python + FFmpeg | Audio recording, analysis orchestration |
| **icecast** | 8888 | Icecast + FFmpeg | Live audio streaming to browsers |

## Container Architecture

```
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│     frontend     │      │       main       │      │     icecast      │
│       :80        │      │                  │      │      :8888       │
├──────────────────┤      ├──────────────────┤      ├──────────────────┤
│ Nginx + Vue.js 3 │      │   Main Loop      │      │ FFmpeg + Icecast │
│ Serves UI        │      │   Recording      │      │   Livestream     │
│ Reverse proxy    │      │ Analysis Pipeline│      │                  │
└────────┬─────────┘      └────────┬─────────┘      └──────────────────┘
         │                         │
         │          ┌──────────────┴──────────────┐
         │          │                             │
         │          ▼                             ▼
         │   ┌─────────────────┐          ┌─────────────────┐
         │   │      api        │          │  model-server   │
         │   │     :5002       │          │     :5001       │
         │   ├─────────────────┤          ├─────────────────┤
         └──▶│ Flask + SocketIO│          │ TFLite V2.4 /   │
             │ WebSocket events│          │ ONNX V3.1 model │
             └─────────────────┘          └─────────────────┘
```

## Audio Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      RASPBERRY PI HOST                           │
│                                                                  │
│   ┌─────────────┐       ┌─────────────────────────────────┐      │
│   │     USB     │       │   PulseAudio or PipeWire        │      │
│   │ Microphone  │──────▶│   (audio server)                │      │
│   └─────────────┘       └───────────────┬─────────────────┘      │
│                                         │                        │
│                              /run/pulse/native                   │
│                                 (socket)                         │
└─────────────────────────────────┬────────────────────────────────┘
                                  │ bind-mount
                    ┌─────────────┴─────────────┐
                    │                           │
                    ▼                           ▼
        ┌───────────────────┐       ┌───────────────────┐
        │  main container   │       │ icecast container │
        │                   │       │                   │
        │  Records audio    │       │  Streams audio    │
        │  for analysis     │       │  to browsers      │
        └───────────────────┘       └───────────────────┘
```

- **RPi OS Desktop**: Uses PipeWire with `pipewire-pulse` compatibility layer
- **RPi OS Lite**: Installs PulseAudio in system-wide mode

## Data Flow

```
 ┌─────────┐     WAV     ┌─────────────┐  detections  ┌───────────┐
 │  main   │────────────▶│ model-      │─────────────▶│   main    │
 │ recorder│   chunks    │ server      │    JSON      │ pipeline  │
 └─────────┘             └─────────────┘              └─────┬─────┘
                                                            │
                         ┌──────────────────────────────────┘
                         │
                         ▼
          ┌──────────────────────────────────────────┐
          │  For each detection:                     │
          │  1. Extract audio clip                   │
          │  2. Generate spectrogram                 │
          │  3. Save to SQLite database              │
          │  4. Broadcast via WebSocket              │
          └──────────────────────────────────────────┘
                         │
                         ▼
          ┌──────────────────────────────────────────┐
          │            Vue.js Dashboard              │
          │                                          │
          │  - Real-time detection feed (WebSocket)  │
          │  - Historical data (REST API)            │
          │  - Audio playback & spectrograms         │
          └──────────────────────────────────────────┘
```

## Settings lifecycle

The API is the only settings writer. Each write validates and merges a partial
update under one transaction lock, then atomically replaces the private JSON
file. GET and successful writes return a content ETag; the browser serializes
its writes and sends `If-Match` to reject changes based on an obsolete revision.
Manual Save sends changed fields. Source and species dialogs save only their
own fields, leaving unrelated form drafts untouched.

Runtime readers load a stable file snapshot. A readable file always loads into
a document that passes every current rule: each value rule in
`core/settings_validation.py` carries its repair (ranges clamp, option lists
and ordering pairs fall back around the value the user set, an invalid
timezone is derived from the coordinates, unusable sources are dropped and the
icecast supervisor skips them the same way), repairs are applied in memory and
logged, and the next save persists them. A test breaks every rule at once and
requires one repair per rule, so a rule cannot be added without one. Only
shape errors (unparseable JSON, wrong types) make a file unreadable: runtime
readers then keep the last good snapshot, API writes and the Settings form are
blocked with the reason shown, and the configuration is never replaced with
defaults. A settings read never persists a migration.

| Change | Takes effect |
|--------|--------------|
| Detection, overlap, location, species lists | Next analysis request |
| Playback normalization and spectrogram preferences | Next generated clip/image |
| Notifications and BirdWeather | Next event; disabled/replaced BirdWeather workers discard queued uploads |
| Storage policy | Next cleanup cycle |
| Display, update channel, access | Next request; browser preferences refresh on entering/focusing Settings |
| Source connection or enabled flag | Only that source's recorder and stream reconnect |
| Recording length | Recorders reconnect; queued WAVs keep their actual duration |
| Source label | No audio reconnection |
| Quiet hours | Next recording-loop tick; live streaming continues |
| Model type | Explicit service restart |

The main loop owns recorders by source ID. The streaming container runs the
standard-library Python `stream_supervisor.py`, which owns one FFmpeg publisher
per source. Both compare the connection configuration and retain unchanged
processes. A replacement starts only after the previous process stops. Failed
stream connections retry independently with bounded backoff. The supervisor
reads only `user_settings.json`; tightened access settings evict anonymous
WebSocket listeners at the API, while an established Icecast listener keeps its
current connection and is re-checked by nginx on its next one.

A save acknowledges persistence. `/api/settings/status` separately compares the
saved model/source configuration with recorder heartbeats, model service status,
and the streaming supervisor's private `data/streaming_status.json` heartbeat.
The API shares the same snapshot through the `settings_status` socket event
with owner sockets that asked for it (`watch_settings_status`, sent by the
Settings page while mounted and again on every reconnection). One monitor per
API worker samples audio once per second and refreshes model health
independently every five seconds while anyone is watching, with at most one
model request in flight; pages that do not show settings status cost nothing.
Model results expire after fifteen seconds, so ongoing audio updates cannot keep
old model health alive. It sends changes, a fresh snapshot for each new watcher,
and a five-second heartbeat. Settings consumes these pushes instead of polling
the REST endpoint; leaving the page, disconnects or fifteen seconds without a
heartbeat clear the browser's status. The REST endpoint remains available for
diagnostics. Each snapshot carries per-source recording and streaming state,
the recorder's error text for a failed source, and the pause in force, all
from one acknowledged revision.
The recorder loop acknowledges settings per source (a change to one source
never invalidates another's state) and broadcasts per-source state, error,
pause and acknowledgement changes on its next two-second pass, retaining a
five-second heartbeat for unchanged status. Failed deliveries retry on the
next pass.
Recorders confirm activity after capturing audio; streams confirm it after
FFmpeg reports advancing output. Missing or old heartbeats mean unknown status,
not success. Pending model changes remain visible across refreshes and repeated
saves. The loaded model continues serving while awaiting restart, retaining its
own location-filter threshold; queued audio is resampled to its sample rate.

The restart boundary for model changes keeps model allocation, sample-rate
selection and process recovery simple on memory-constrained devices. A general
settings event bus or dynamic model replacement is not required for source reload.

The Home Assistant add-on packages `stream_supervisor.py` next to the backend
and starts `start-icecast.sh` as root: Icecast drops to `icecast2` through
`<changeowner>` while the supervisor keeps root, because the add-on's API runs
as root and writes `user_settings.json` with mode 0600 into a root-owned data
directory. A wrapper that ships the script without the supervisor idles with
Icecast up and stream status unavailable rather than restart-looping.

Streaming supervisor tests run independently with:
`python3 -m unittest discover -s deployment/audio/tests -v`.
