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

# Validate Icecast password - reject insecure defaults
if [ -z "$ICECAST_PASSWORD" ] || [ "$ICECAST_PASSWORD" = "hackme" ]; then
    ICECAST_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 16)
    log_msg "WARNING: ICECAST_PASSWORD not set or using insecure default."
    log_msg "         Generated random password for this session."
    log_msg "         Set ICECAST_PASSWORD in your environment for a persistent password."
fi

# Icecast refuses to run as root. When this script is started as root (the
# Home Assistant add-on, whose data directory and 0600 settings files are
# root-owned, so the supervisor must keep root to read and write them), let
# Icecast itself drop to the packaged icecast2 account via <changeowner>.
CHANGEOWNER=""
if [ "$(id -u)" = "0" ]; then
    ICECAST_USER="${ICECAST_USER:-icecast2}"
    ICECAST_GROUP="$(id -gn "$ICECAST_USER")"
    CHANGEOWNER="<changeowner><user>${ICECAST_USER}</user><group>${ICECAST_GROUP}</group></changeowner>"
    # Icecast opens its own logs only after dropping privileges.
    chown -R "${ICECAST_USER}:${ICECAST_GROUP}" /var/log/icecast2 2>/dev/null || true
    log_msg "Running as root: Icecast will drop to ${ICECAST_USER}:${ICECAST_GROUP}"
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
        ${CHANGEOWNER}
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

# Python owns publisher lifetimes and polls configuration, including the empty
# initial source list. Icecast stays up while individual sources reconnect.
# A deployment that ships this script without the supervisor (an out-of-date
# add-on wrapper) idles with Icecast up instead of restart-looping.
SUPERVISOR="${STREAM_SUPERVISOR:-/app/stream_supervisor.py}"
if [ ! -f "$SUPERVISOR" ]; then
    log_msg "ERROR: $SUPERVISOR is missing; live streaming stays unavailable until the deployment ships it"
    exec sleep infinity
fi
export ICECAST_PASSWORD STREAM_BITRATE
exec python3 "$SUPERVISOR"
