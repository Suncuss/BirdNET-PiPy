#!/bin/bash
# Start Icecast streaming server with FFmpeg audio capture from PulseAudio

set -e

# Configuration from environment
ICECAST_PASSWORD="${ICECAST_PASSWORD:-hackme}"
STREAM_BITRATE="${STREAM_BITRATE:-128k}"

echo "Starting Icecast streaming service..."
echo "  Stream bitrate: $STREAM_BITRATE"
echo "  PulseAudio source: default"

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

# Always use default PulseAudio source for streaming
PA_SOURCE="default"

echo "Using PulseAudio source: $PA_SOURCE"

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

# Start FFmpeg streaming to Icecast (output to stdout)
echo "Starting audio stream capture..."
exec ffmpeg -hide_banner -loglevel warning \
    -f pulse -i "$PA_SOURCE" \
    -codec:a libmp3lame -b:a "$STREAM_BITRATE" \
    -f mp3 -content_type audio/mpeg \
    "icecast://source:${ICECAST_PASSWORD}@localhost:8888/stream.mp3"
