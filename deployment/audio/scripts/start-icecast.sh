#!/bin/bash
# Start Icecast streaming server with FFmpeg audio capture from PulseAudio or RTSP

set -e

# Configuration from environment
ICECAST_PASSWORD="${ICECAST_PASSWORD:-hackme}"
STREAM_BITRATE="${STREAM_BITRATE:-320k}"

# Read RTSP URL from user settings if recording mode is 'rtsp'
SETTINGS_FILE="/app/data/config/user_settings.json"
RTSP_STREAM_URL=""
if [ -f "$SETTINGS_FILE" ]; then
    RECORDING_MODE=$(jq -r '.audio.recording_mode // "pulseaudio"' "$SETTINGS_FILE")
    if [ "$RECORDING_MODE" = "rtsp" ]; then
        RTSP_STREAM_URL=$(jq -r '.audio.rtsp_url // empty' "$SETTINGS_FILE")
    fi
fi

echo "Starting Icecast streaming service..."
echo "  Stream bitrate: $STREAM_BITRATE"

# Determine audio source based on RTSP_STREAM_URL
if [ -n "$RTSP_STREAM_URL" ]; then
    echo "  Audio source: RTSP stream"
    # Hide credentials in log output
    RTSP_DISPLAY_URL=$(echo "$RTSP_STREAM_URL" | sed 's/:[^:@]*@/:***@/')
    echo "  RTSP URL: $RTSP_DISPLAY_URL"
    AUDIO_INPUT="-rtsp_transport tcp -timeout 10000000 -i \"$RTSP_STREAM_URL\""
else
    echo "  Audio source: PulseAudio (default)"

    # Wait for PulseAudio to be available
    echo "Waiting for PulseAudio..."
    MAX_RETRIES=30
    RETRY_COUNT=0
    while ! timeout 1 bash -c "echo > /dev/tcp/localhost/0" 2>/dev/null; do
        # Check if PulseAudio socket exists
        if [ -S "/run/pulse/native" ]; then
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
            echo "ERROR: PulseAudio socket not found after ${MAX_RETRIES} seconds"
            exit 1
        fi
        sleep 1
    done

    # Verify PulseAudio connection
    if [ -S "/run/pulse/native" ]; then
        echo "PulseAudio socket found at /run/pulse/native"
    else
        echo "ERROR: PulseAudio socket not available"
        exit 1
    fi

    PA_SOURCE="default"
    echo "Using PulseAudio source: $PA_SOURCE"
    AUDIO_INPUT="-f pulse -i $PA_SOURCE"
fi

# Start Icecast in background
echo "Starting Icecast server..."
icecast2 -c /etc/icecast2/icecast.xml -b
sleep 2

# Verify Icecast is running
if ! curl -s http://localhost:8888/status-json.xsl > /dev/null 2>&1; then
    echo "ERROR: Icecast failed to start"
    exit 1
fi

echo "Icecast server started on port 8888"

# Start FFmpeg streaming to Icecast
echo "Starting audio stream capture..."
eval exec ffmpeg -hide_banner -loglevel warning \
    $AUDIO_INPUT \
    -codec:a libmp3lame -b:a "$STREAM_BITRATE" \
    -f mp3 -content_type audio/mpeg \
    "icecast://source:${ICECAST_PASSWORD}@localhost:8888/stream.mp3"
