#!/bin/bash
# Start Icecast streaming server with FFmpeg audio capture from multiple sources

set -e

# Logging to file and stdout
LOG_DIR="/app/data/logs"
LOG_FILE="$LOG_DIR/icecast.log"
LOG_MAX_SIZE=$((5 * 1024 * 1024))  # 5 MB

mkdir -p "$LOG_DIR"

log_msg() {
    local msg="[$(date -Iseconds)] $1"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
    # Truncate if file exceeds max size (keep last 1000 lines)
    local size
    size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    if [ "$size" -gt "$LOG_MAX_SIZE" ]; then
        tail -n 1000 "$LOG_FILE" > "$LOG_FILE.tmp" && mv "$LOG_FILE.tmp" "$LOG_FILE"
    fi
}

# Configuration from environment
STREAM_BITRATE="${STREAM_BITRATE:-320k}"
SETTINGS_FILE="/app/data/config/user_settings.json"

# Validate Icecast password - reject insecure defaults
if [ -z "$ICECAST_PASSWORD" ] || [ "$ICECAST_PASSWORD" = "hackme" ]; then
    ICECAST_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 16)
    log_msg "WARNING: ICECAST_PASSWORD not set or using insecure default."
    log_msg "         Generated random password for this session."
    log_msg "         Set ICECAST_PASSWORD in your environment for a persistent password."
fi

# Generate icecast config with enough source slots for multi-source
ICECAST_CONFIG="/tmp/icecast.xml"
cat > "$ICECAST_CONFIG" << EOF
<icecast>
    <location>RPi Audio Stream</location>
    <admin>admin@localhost</admin>

    <limits>
        <clients>100</clients>
        <sources>10</sources>
        <workers>1</workers>
    </limits>

    <authentication>
        <source-password>${ICECAST_PASSWORD}</source-password>
        <relay-password>${ICECAST_PASSWORD}</relay-password>
        <admin-user>admin</admin-user>
        <admin-password>${ICECAST_PASSWORD}</admin-password>
    </authentication>

    <hostname>localhost</hostname>

    <listen-socket>
        <port>8888</port>
    </listen-socket>

    <fileserve>1</fileserve>

    <paths>
        <basedir>/usr/share/icecast2</basedir>
        <logdir>/var/log/icecast2</logdir>
        <webroot>/usr/share/icecast2/web</webroot>
        <adminroot>/usr/share/icecast2/admin</adminroot>
        <alias source="/" destination="/status.xsl"/>
    </paths>

    <logging>
        <accesslog>access.log</accesslog>
        <errorlog>error.log</errorlog>
        <loglevel>3</loglevel>
        <logsize>10000</logsize>
    </logging>

    <security>
        <chroot>0</chroot>
    </security>
</icecast>
EOF

log_msg "Starting Icecast streaming service..."
log_msg "  Stream bitrate: $STREAM_BITRATE"

# Start Icecast in background
log_msg "Starting Icecast server..."
icecast2 -c "$ICECAST_CONFIG" -b
sleep 2

# Verify Icecast is running
if ! curl -s http://localhost:8888/status-json.xsl > /dev/null 2>&1; then
    log_msg "ERROR: Icecast failed to start"
    exit 1
fi

log_msg "Icecast server started on port 8888"

# Track all ffmpeg PIDs for cleanup
declare -a FFMPEG_PIDS=()
RUNNING=true

cleanup() {
    RUNNING=false
    log_msg "Received shutdown signal..."
    for pid in "${FFMPEG_PIDS[@]}"; do
        kill "$pid" 2>/dev/null
    done
}
trap cleanup SIGTERM SIGINT

# Wait for PulseAudio socket (called once if any pulseaudio source exists)
wait_for_pulseaudio() {
    log_msg "Waiting for PulseAudio..."
    local retries=0
    while [ $retries -lt 30 ]; do
        if [ -S "/run/pulse/native" ]; then
            log_msg "PulseAudio socket found at /run/pulse/native"
            return 0
        fi
        retries=$((retries + 1))
        sleep 1
    done
    log_msg "ERROR: PulseAudio socket not found after 30 seconds"
    return 1
}

# Stream loop for a single source — runs in background
run_stream_loop() {
    local source_id="$1"
    local source_type="$2"
    local mount_point="/${source_id}.mp3"
    local retry_count=0
    local last_error_log=0

    # Build ffmpeg input args based on source type
    local -a audio_args=()
    local retry_delay=1

    if [ "$source_type" = "rtsp" ]; then
        local rtsp_url="$3"
        local display_url
        display_url=$(echo "$rtsp_url" | sed 's/:[^:@]*@/:***@/')
        log_msg "  [$source_id] RTSP source: $display_url → $mount_point"
        audio_args=(-rtsp_transport tcp -timeout 10000000 -allowed_media_types audio -fflags +genpts+discardcorrupt -use_wallclock_as_timestamps 1 -i "$rtsp_url" -map 0:a:0 -af aresample=async=1:first_pts=0)
        retry_delay=2
    elif [ "$source_type" = "pulseaudio" ]; then
        local device="${3:-default}"
        log_msg "  [$source_id] PulseAudio source: $device → $mount_point"
        audio_args=(-f pulse -i "$device")
        retry_delay=1
    else
        log_msg "  [$source_id] Unknown source type: $source_type, skipping"
        return
    fi

    set +e
    while $RUNNING; do
        local stream_start
        stream_start=$(date +%s)

        ffmpeg -hide_banner -loglevel warning \
            "${audio_args[@]}" \
            -codec:a libmp3lame -b:a "$STREAM_BITRATE" \
            -f mp3 -content_type audio/mpeg \
            "icecast://source:${ICECAST_PASSWORD}@localhost:8888${mount_point}" &
        local pid=$!

        sleep 1
        if kill -0 "$pid" 2>/dev/null; then
            if [ $retry_count -gt 0 ]; then
                log_msg "  [$source_id] Reconnected after $retry_count retries"
            else
                log_msg "  [$source_id] Stream connected"
            fi
            retry_count=0
        fi

        wait "$pid"
        local exit_code=$?
        local duration=$(($(date +%s) - stream_start))

        if ! $RUNNING; then break; fi

        retry_count=$((retry_count + 1))
        local now
        now=$(date +%s)
        if [ $((now - last_error_log)) -gt 30 ]; then
            last_error_log=$now
            if [ $duration -gt 5 ]; then
                log_msg "  [$source_id] Disconnected after ${duration}s (exit $exit_code), reconnecting..."
            else
                log_msg "  [$source_id] Failed (attempt $retry_count), retrying in ${retry_delay}s..."
            fi
        fi

        sleep $retry_delay
    done
}

# Read enabled sources from settings and launch stream loops
NEEDS_PULSE=false
if [ -f "$SETTINGS_FILE" ]; then
    SOURCE_COUNT=$(jq -r '.audio.sources | length // 0' "$SETTINGS_FILE" 2>/dev/null || echo 0)

    if [ "$SOURCE_COUNT" -gt 0 ]; then
        # Check if any pulseaudio source exists
        PA_COUNT=$(jq -r '[.audio.sources[] | select(.type == "pulseaudio" and .enabled == true)] | length' "$SETTINGS_FILE" 2>/dev/null || echo 0)
        if [ "$PA_COUNT" -gt 0 ]; then
            wait_for_pulseaudio || exit 1
        fi

        # Launch a stream loop per enabled source
        for i in $(seq 0 $((SOURCE_COUNT - 1))); do
            ENABLED=$(jq -r ".audio.sources[$i].enabled // true" "$SETTINGS_FILE")
            [ "$ENABLED" = "false" ] && continue

            SID=$(jq -r ".audio.sources[$i].id" "$SETTINGS_FILE")
            STYPE=$(jq -r ".audio.sources[$i].type" "$SETTINGS_FILE")

            if [ "$STYPE" = "rtsp" ]; then
                SURL=$(jq -r ".audio.sources[$i].url" "$SETTINGS_FILE")
                run_stream_loop "$SID" "$STYPE" "$SURL" &
                FFMPEG_PIDS+=($!)
            elif [ "$STYPE" = "pulseaudio" ]; then
                SDEVICE=$(jq -r ".audio.sources[$i].device // \"default\"" "$SETTINGS_FILE")
                run_stream_loop "$SID" "$STYPE" "$SDEVICE" &
                FFMPEG_PIDS+=($!)
            fi
        done

        log_msg "Launched ${#FFMPEG_PIDS[@]} stream(s)"
    else
        log_msg "No audio sources configured, waiting for settings..."
    fi
else
    log_msg "No settings file found, waiting for configuration..."
fi

# If no stream loops were launched, keep the container alive so it doesn't
# restart-loop. Icecast stays running for when sources are added later.
if [ ${#FFMPEG_PIDS[@]} -eq 0 ]; then
    while $RUNNING; do
        sleep 30
    done
else
    wait
fi
log_msg "Shutdown complete"
