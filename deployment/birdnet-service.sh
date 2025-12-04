#!/bin/bash
# BirdNET-PiPy Service Management Script
# This script is called by systemd to manage the BirdNET-PiPy services

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESTART_FLAG_FILE="$PROJECT_ROOT/data/flags/restart-backend"
UPDATE_FLAG_FILE="$PROJECT_ROOT/data/flags/update-requested"
CHECK_INTERVAL=5  # Check for restart and update flags every 5 seconds

# PulseAudio configuration
PULSEAUDIO_CONFIG="$SCRIPT_DIR/audio/pulseaudio"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[BIRDNET-SERVICE]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[BIRDNET-SERVICE]${NC} $1"
}

log_error() {
    echo -e "${RED}[BIRDNET-SERVICE]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[BIRDNET-SERVICE]${NC} $1"
}

# Detect and export timezone if not already set
detect_timezone() {
    if [ -z "$TZ" ]; then
        if [ -f /etc/timezone ]; then
            TZ=$(cat /etc/timezone)
        elif [ -L /etc/localtime ]; then
            TZ=$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')
        else
            TZ="UTC"
        fi
    fi
    export TZ
    log_info "Using timezone: $TZ"
}

# Cleanup function for graceful shutdown
cleanup() {
    log_info "Shutting down BirdNET-PiPy services..."

    # Stop Docker containers
    cd "$PROJECT_ROOT"
    docker compose down

    # Stop PulseAudio
    log_info "Stopping PulseAudio..."
    pulseaudio --kill 2>/dev/null || true

    log_info "Shutdown complete"
    exit 0
}

# Set up signal handlers for graceful shutdown
trap cleanup SIGTERM SIGINT

# Function to ensure PulseAudio/PipeWire is available
start_pulseaudio() {
    log_info "Checking audio server..."

    # Check for user-mode PipeWire/PulseAudio socket first (common on modern systems)
    local user_socket="/run/user/$(id -u)/pulse/native"
    if [ -S "$user_socket" ]; then
        log_info "PipeWire/PulseAudio socket found at $user_socket"
        return 0
    fi

    # Check for system-wide PulseAudio socket
    if [ -S /run/pulse/native ]; then
        log_info "System PulseAudio socket found at /run/pulse/native"
        return 0
    fi

    # No socket found - try to start system PulseAudio
    log_info "No audio socket found, starting system PulseAudio..."

    # Ensure runtime directory exists
    if [ ! -d /run/pulse ]; then
        sudo mkdir -p /run/pulse
        sudo chown pulse:pulse-access /run/pulse 2>/dev/null || sudo chmod 777 /run/pulse
    fi

    # Start PulseAudio in system mode
    pulseaudio --system --daemonize --disallow-exit \
        --disallow-module-loading=false \
        --log-target=syslog 2>/dev/null

    # Wait for PulseAudio to be ready
    local retries=0
    while ! pulseaudio --check 2>/dev/null; do
        retries=$((retries + 1))
        if [ $retries -ge 10 ]; then
            log_error "PulseAudio failed to start after 10 attempts"
            return 1
        fi
        sleep 0.5
    done

    # Verify socket exists
    if [ -S /run/pulse/native ]; then
        log_info "PulseAudio started successfully (socket: /run/pulse/native)"
    else
        log_warning "PulseAudio running but socket not found"
    fi
}

# Function to start Docker containers
start_containers() {
    log_info "Starting Docker containers..."
    cd "$PROJECT_ROOT"
    docker compose up -d

    if [ $? -eq 0 ]; then
        log_info "Docker containers started successfully"
    else
        log_error "Failed to start Docker containers"
        return 1
    fi
}

# Function to restart containers when flag is detected
restart_containers() {
    log_info "Restart flag detected, restarting containers..."

    cd "$PROJECT_ROOT"
    # Use --force-recreate to ensure fresh network connections and avoid nginx DNS cache issues
    docker compose up -d --force-recreate

    if [ $? -eq 0 ]; then
        log_info "Containers restarted successfully"
        # Remove the restart flag
        rm -f "$RESTART_FLAG_FILE"
        log_debug "Restart flag removed"
    else
        log_error "Failed to restart containers"
        return 1
    fi
}

# Function to perform system update
perform_system_update() {
    log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log_info "System update requested"
    log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    cd "$PROJECT_ROOT"

    # Step 1: Fetch latest and check if update needed
    log_info "Fetching latest code from origin/main..."
    if ! git fetch origin main 2>&1; then
        log_error "Git fetch failed - network issue or invalid remote"
        rm -f "$UPDATE_FLAG_FILE"
        return 1
    fi

    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)

    if [ "$LOCAL" = "$REMOTE" ]; then
        log_info "Already up to date, no update needed"
        rm -f "$UPDATE_FLAG_FILE"
        return 0
    fi

    COMMITS_BEHIND=$(git rev-list --count HEAD..origin/main)
    log_info "Update available: $COMMITS_BEHIND commits behind origin/main"

    # Step 2: Stop containers
    log_info "Stopping Docker containers..."
    if ! docker compose down; then
        log_error "Failed to stop containers, aborting update"
        rm -f "$UPDATE_FLAG_FILE"
        return 1
    fi

    # Step 3: Pull latest code
    log_info "Pulling latest code from origin/main..."
    if ! git pull origin main 2>&1; then
        log_error "Git pull failed! Restarting with current code..."
        docker compose up -d
        rm -f "$UPDATE_FLAG_FILE"
        return 1
    fi

    # Step 3.5 & 4: Build using build.sh (generates version.json and rebuilds Docker images)
    log_info "Running build script..."
    if ! "$PROJECT_ROOT/build.sh"; then
        log_error "Build failed! Attempting to restart with previous images..."
        docker compose up -d
        rm -f "$UPDATE_FLAG_FILE"
        return 1
    fi

    # Step 5: Start updated containers
    log_info "Starting updated containers..."
    if docker compose up -d; then
        log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log_info "System update completed successfully!"
        log_info "Applied $COMMITS_BEHIND commits from origin/main"
        log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        rm -f "$UPDATE_FLAG_FILE"
        return 0
    else
        log_error "Failed to start updated containers"
        rm -f "$UPDATE_FLAG_FILE"
        return 1
    fi
}

# Function to monitor both restart and update flags
monitor_flags() {
    while true; do
        # Check update flag first (higher priority)
        if [ -f "$UPDATE_FLAG_FILE" ]; then
            perform_system_update
        # Then check restart flag
        elif [ -f "$RESTART_FLAG_FILE" ]; then
            restart_containers
        fi
        sleep "$CHECK_INTERVAL"
    done
}

# Main execution
main() {
    log_info "BirdNET-PiPy Service Starting..."
    log_info "Working directory: $PROJECT_ROOT"

    # Detect timezone for Docker containers
    detect_timezone

    # Start PulseAudio for audio access
    start_pulseaudio

    # Start Docker containers
    start_containers

    # Start monitoring for restart and update flags in background
    log_info "Starting flag monitor (checking every ${CHECK_INTERVAL}s)..."
    log_info "  - Restart flag: $RESTART_FLAG_FILE"
    log_info "  - Update flag: $UPDATE_FLAG_FILE"
    monitor_flags &
    MONITOR_PID=$!

    log_info "Service running (Monitor PID: $MONITOR_PID)"

    # Wait for the monitor process (this keeps the script running)
    wait $MONITOR_PID
}

# Run main function
main
