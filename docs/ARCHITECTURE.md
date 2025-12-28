# Architecture

BirdNET-PiPy uses a containerized microservices architecture with five Docker containers.

## Container Details

| Container | Port | Technology | Purpose |
|-----------|------|------------|---------|
| **frontend** | 80 | Nginx + Vue.js 3 | Web dashboard, SPA routing, API/stream proxy |
| **api** | 5002 | Flask + Socket.IO | REST API, WebSocket events, database access |
| **birdnet-server** | 5001 | TensorFlow Lite | AI model inference, species detection |
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
         │   │      api        │          │  birdnet-server │
         │   │     :5002       │          │     :5001       │
         │   ├─────────────────┤          ├─────────────────┤
         └──▶│ Flask + SocketIO│          │ TensorFlow Lite │
             │ WebSocket events│          │  BirdNET Model  │
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
 │  main   │────────────▶│ birdnet-    │─────────────▶│   main    │
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
