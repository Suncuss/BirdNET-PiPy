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

    # Stop Docker containers with timeout
    cd "$PROJECT_ROOT"

    # Try graceful shutdown first (60s timeout for slow systems)
    if ! timeout 60 docker compose down --remove-orphans 2>/dev/null; then
        log_warning "Graceful shutdown timed out, forcing container removal..."
        docker compose kill 2>/dev/null || true
        docker compose down --remove-orphans 2>/dev/null || true
    fi

    # Unmount bind mount if it exists (created for user-mode PulseAudio)
    if mountpoint -q /run/pulse 2>/dev/null; then
        log_info "Unmounting /run/pulse bind mount..."
        sudo umount /run/pulse 2>/dev/null || true
        # Don't try to kill PulseAudio - we were using user-mode PA via bind mount
    else
        # Only try to stop PulseAudio if we started system-wide PA (no bind mount)
        # Check if system-wide PulseAudio is running (pgrep works better than pulseaudio --check for system mode)
        if pgrep -x pulseaudio >/dev/null 2>&1; then
            log_info "Stopping system PulseAudio..."
            sudo pulseaudio --kill 2>/dev/null || true
        fi
    fi

    log_info "Shutdown complete"
    exit 0
}

# Set up signal handlers for graceful shutdown
trap cleanup SIGTERM SIGINT

# Function to ensure PulseAudio socket is available at /run/pulse/native
# This works for both:
#   - Pi OS Desktop: PipeWire provides user socket, we bind-mount it to /run/pulse
#   - Pi OS Lite: No user socket, we start system-wide PulseAudio at /run/pulse
setup_audio_socket() {
    log_info "Setting up audio socket..."

    local user_pulse_dir="/run/user/$(id -u)/pulse"
    local user_socket="$user_pulse_dir/native"
    local system_pulse_dir="/run/pulse"
    local system_socket="$system_pulse_dir/native"

    # Detect Desktop/PipeWire system and wait for user socket if needed
    # On Desktop with auto-login, PipeWire starts after the user session begins
    # We wait for it rather than falling back to system-wide PA (which may not be installed)
    if command -v pipewire &> /dev/null && ! command -v pulseaudio &> /dev/null; then
        # PipeWire-only system (Desktop without PA fallback)
        log_info "PipeWire detected without PulseAudio fallback, waiting for user audio socket..."
        local wait_time=0
        local max_wait=60  # Wait up to 60 seconds for auto-login + PipeWire

        while [ ! -S "$user_socket" ]; do
            if [ $wait_time -ge $max_wait ]; then
                log_error "User audio socket not available after ${max_wait}s"
                log_error "Ensure auto-login is enabled for audio to work on Desktop"
                return 1
            fi
            sleep 2
            wait_time=$((wait_time + 2))
            if [ $((wait_time % 10)) -eq 0 ]; then
                log_info "Waiting for PipeWire socket... (${wait_time}s/${max_wait}s)"
            fi
        done
        log_info "PipeWire socket ready after ${wait_time}s"
    fi

    # Case 1: User-mode socket exists (Pi OS Desktop with PipeWire)
    if [ -S "$user_socket" ]; then
        log_info "User-mode audio socket found at $user_socket"

        # Use bind mount to make /run/pulse an alias for /run/user/1000/pulse
        # This is necessary because symlinks don't work with Docker volume mounts
        # (the symlink target isn't available inside the container)

        # Check if already bind-mounted
        if mountpoint -q "$system_pulse_dir" 2>/dev/null; then
            log_info "Bind mount already exists at $system_pulse_dir"
            return 0
        fi

        # Create mount point if it doesn't exist
        if [ ! -d "$system_pulse_dir" ]; then
            sudo mkdir -p "$system_pulse_dir"
        fi

        # Remove any stale symlink from previous versions
        if [ -L "$system_socket" ]; then
            sudo rm -f "$system_socket"
        fi

        # Bind mount the user pulse directory to /run/pulse
        if sudo mount --bind "$user_pulse_dir" "$system_pulse_dir"; then
            log_info "Bind mounted $user_pulse_dir -> $system_pulse_dir"
            return 0
        else
            log_error "Failed to create bind mount"
            return 1
        fi
    fi

    # Case 2: System socket already exists (system-wide PA already running)
    if [ -S "$system_socket" ]; then
        log_info "System-wide audio socket found at $system_socket"
        return 0
    fi

    # Case 3: No socket found - start system-wide PulseAudio (Pi OS Lite)
    log_info "No audio socket found, starting system-wide PulseAudio..."

    # Ensure /run/pulse directory exists with proper permissions
    if [ ! -d "$system_pulse_dir" ]; then
        sudo mkdir -p "$system_pulse_dir"
        sudo chown pulse:pulse-access "$system_pulse_dir" 2>/dev/null || sudo chmod 777 "$system_pulse_dir"
    fi

    # Start PulseAudio in system mode (requires root privileges)
    sudo pulseaudio --system --daemonize --disallow-exit \
        --disallow-module-loading=false \
        --log-target=syslog 2>/dev/null

    # Wait for PulseAudio socket to be ready
    # Note: pulseaudio --check doesn't work for system-wide PA, so we check the socket directly
    local retries=0
    while [ ! -S "$system_socket" ]; do
        retries=$((retries + 1))
        if [ $retries -ge 20 ]; then
            log_error "PulseAudio socket not created after 10 seconds"
            return 1
        fi
        sleep 0.5
    done

    # Verify PulseAudio is actually responding (not just socket exists)
    if PULSE_SERVER=unix:$system_socket pactl info >/dev/null 2>&1; then
        log_info "System PulseAudio started (socket: $system_socket)"
    else
        log_warning "PulseAudio socket exists but server not responding"
        return 1
    fi
}

# Function to clean up orphaned containers/tasks from previous runs
cleanup_orphaned_containers() {
    log_info "Cleaning up any orphaned containers..."
    cd "$PROJECT_ROOT"

    # Remove any stopped containers from this project
    docker compose down --remove-orphans 2>/dev/null || true
}

# Function to start Docker containers
start_containers() {
    log_info "Starting Docker containers..."
    cd "$PROJECT_ROOT"

    # Clean up orphaned containers first
    cleanup_orphaned_containers

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

    # Step 1: Stop containers IMMEDIATELY so frontend can detect update in progress
    # This must happen before any network calls (git fetch) to ensure the frontend
    # sees the service go down within the expected timeout window
    log_info "Stopping Docker containers..."
    docker compose down || true

    # Step 2: Fetch latest and check if update needed
    log_info "Fetching latest code from origin/main..."
    if ! git fetch origin main 2>&1; then
        log_error "Git fetch failed - network issue or invalid remote"
        log_info "Restarting containers with current code..."
        docker compose up -d || true
        rm -f "$UPDATE_FLAG_FILE"
        return 1
    fi

    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)

    if [ "$LOCAL" = "$REMOTE" ]; then
        log_info "Already up to date, no update needed"
        log_info "Restarting containers..."
        docker compose up -d || true
        rm -f "$UPDATE_FLAG_FILE"
        return 0
    fi

    COMMITS_BEHIND=$(git rev-list --count HEAD..origin/main)
    log_info "Update available: $COMMITS_BEHIND commits behind origin/main"

    # Step 3: Sync to latest code (reset to origin/main)
    # Check for local modifications and warn before discarding
    if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet HEAD 2>/dev/null; then
        log_warning "Local modifications detected - these will be discarded by the update:"
        git status --short 2>/dev/null | while read line; do
            log_warning "  $line"
        done
        log_warning "Note: The install directory is not intended for local customizations"
    fi

    # Using reset instead of pull - works even if repo history changes
    log_info "Syncing to origin/main..."
    if ! git reset --hard origin/main 2>&1; then
        log_error "Git reset failed! Restarting containers with current code..."
        docker compose up -d || true
        rm -f "$UPDATE_FLAG_FILE"
        return 1
    fi

    # Step 4: Build new images
    log_info "Running build script..."
    if ! "$PROJECT_ROOT/build.sh"; then
        log_error "Build failed! Restarting containers with previous images..."
        docker compose up -d || true
        rm -f "$UPDATE_FLAG_FILE"
        return 1
    fi

    # Step 5: Exit to trigger service restart
    # systemd (Restart=always) will restart the service with the new code.
    # The new script will start containers with the newly built images.
    log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log_info "Build complete! Applied $COMMITS_BEHIND commits from origin/main"
    log_info "Exiting to restart service with updated code..."
    log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    rm -f "$UPDATE_FLAG_FILE"
    exit 0
}

# Function to enable swap if it exists (for low-memory systems)
enable_swap_if_available() {
    local swap_file="/swapfile-birdnet-pipy"

    # Check if swap file exists
    if [ ! -f "$swap_file" ]; then
        return 0
    fi

    # Check if swap is already enabled for this file
    if swapon --show 2>/dev/null | grep -q "$swap_file"; then
        log_debug "Swap file already enabled: $swap_file"
        return 0
    fi

    # Try to enable the swap file
    if sudo swapon "$swap_file" 2>/dev/null; then
        log_info "Swap enabled: $swap_file"

        # Show swap status for debugging
        local swap_size=$(free -h | grep Swap | awk '{print $2}')
        log_debug "Total swap available: $swap_size"
    else
        log_warning "Failed to enable swap file: $swap_file (may require manual setup)"
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

    # Enable swap if available (for low-memory systems like Pi Zero)
    enable_swap_if_available

    # Setup audio socket (symlink to user PulseAudio or start system-wide)
    setup_audio_socket

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
