#!/bin/bash
# BirdNET-PiPy Service Management Script
# This script is called by systemd to manage the BirdNET-PiPy services

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESTART_FLAG_FILE="$PROJECT_ROOT/data/flags/restart-backend"
UPDATE_FLAG_FILE="$PROJECT_ROOT/data/flags/update-requested"
UPDATE_STATUS_FILE="$PROJECT_ROOT/data/flags/update-status"
UPDATE_PROGRESS_FILE="$PROJECT_ROOT/data/flags/update-progress"
CHECK_INTERVAL=5  # Check for restart and update flags every 5 seconds

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

# Cleanup function for graceful shutdown
cleanup() {
    log_info "Shutting down BirdNET-PiPy services..."

    # Kill the background flag monitor so it cannot race with shutdown
    if [ -n "$MONITOR_PID" ]; then
        kill "$MONITOR_PID" 2>/dev/null || true
        wait "$MONITOR_PID" 2>/dev/null || true
    fi

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

# Function to ensure /run/pulse directory has correct permissions for Docker access
# This fixes GitHub issue #6 where manual PulseAudio setup or race conditions
# could leave /run/pulse with restrictive permissions (700), preventing the
# birdnet user in Docker containers from accessing the socket.
#
# The directory needs to be accessible by:
#   - pulse user (owner) - for PulseAudio daemon
#   - pulse-access group - for authorized users
#   - Docker containers mounting /run/pulse (birdnet user, uid 1000)
#
# We use 755 permissions which allows read/execute for all users, enabling
# Docker containers to traverse the directory and access the socket file.
ensure_pulse_dir_permissions() {
    local pulse_dir="$1"

    if [ ! -d "$pulse_dir" ]; then
        return 0
    fi

    # Set ownership to pulse:pulse-access if possible, otherwise leave as-is
    sudo chown pulse:pulse-access "$pulse_dir" 2>/dev/null || true

    # Always ensure directory is world-readable/executable (755)
    # This allows Docker containers to access the socket inside
    sudo chmod 755 "$pulse_dir"

    log_debug "Ensured permissions on $pulse_dir (755, pulse:pulse-access)"
}

is_pulseaudio_responding() {
    local socket_path="$1"
    PULSE_SERVER="unix:$socket_path" pactl info >/dev/null 2>&1
}

reset_stale_system_pulseaudio() {
    local system_pulse_dir="$1"
    local system_socket="$2"
    local system_pid_file="$system_pulse_dir/pid"

    log_warning "System PulseAudio socket exists but server is not responding; resetting stale runtime files..."

    sudo -n pulseaudio --kill 2>/dev/null || true

    if ! sudo -n rm -f "$system_socket"; then
        log_warning "Failed to remove stale PulseAudio socket $system_socket"
    fi

    if ! sudo -n rm -f "$system_pid_file"; then
        log_warning "Failed to remove stale PulseAudio pid file $system_pid_file"
    fi
}

# Function to ensure PulseAudio socket is available at /run/pulse/native
# This works for both:
#   - Pi OS Desktop: PipeWire provides user socket, we bind-mount it to /run/pulse
#   - Pi OS Lite: No user socket, we start system-wide PulseAudio at /run/pulse
setup_audio_socket() {
    log_info "Setting up audio socket..."

    local user_pulse_dir
    user_pulse_dir="/run/user/$(id -u)/pulse"
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
        # Ensure permissions are correct even if socket already exists
        # This handles cases where PulseAudio was started manually or by another process
        # with restrictive permissions (see GitHub issue #6)
        ensure_pulse_dir_permissions "$system_pulse_dir"
        if is_pulseaudio_responding "$system_socket"; then
            log_info "System PulseAudio is responding"
            return 0
        fi

        reset_stale_system_pulseaudio "$system_pulse_dir" "$system_socket"
    fi

    # Case 3: No socket found - start system-wide PulseAudio (Pi OS Lite)
    log_info "No audio socket found, starting system-wide PulseAudio..."

    # Ensure /run/pulse directory exists with proper permissions for Docker containers
    # The birdnet user (uid 1000) in containers needs read access to the socket
    # /run/pulse is on tmpfs and recreated each boot, so we must always set permissions
    sudo mkdir -p "$system_pulse_dir"
    ensure_pulse_dir_permissions "$system_pulse_dir"

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
    if is_pulseaudio_responding "$system_socket"; then
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

    # Remove any stopped containers from this project. Failures here usually
    # foreshadow `compose up` failing too, so surface them - a swallowed error
    # at this step once left a dead station with no diagnosable journal.
    local output
    if ! output=$(docker compose down --remove-orphans 2>&1); then
        log_warning "Pre-start cleanup failed (continuing):"
        log_warning "$output"
    fi
}

# The Docker daemon can be left holding "ghost" container records after an
# unclean shutdown: metadata dirs whose overlay2 RW layer was lost, which the
# daemon half-loads on every start - `docker ps -a` lists them under our
# compose project, but `docker inspect` fails ("no such object"). Compose
# tries to start them by ID, the daemon errors "No such container", and
# `compose up` aborts with the stack half-started - and `compose down` /
# `docker rm` cannot remove them either. Restarting the daemon does NOT help
# (it re-loads the same broken records); the durable fix is deleting the
# orphaned metadata dirs while the daemon is stopped, which
# docker-ghost-heal.sh does as root.
DOCKER_HEAL_MARKER="$PROJECT_ROOT/data/flags/docker-heal-boot-id"

# Start the Docker daemon if it is not running and wait until it responds.
# Covers a heal that got killed mid-surgery (leaving the daemon stopped) and
# a daemon that is still coming up at boot - without this, every compose
# attempt fails until a human notices Docker itself is down.
ensure_docker_running() {
    docker info >/dev/null 2>&1 && return 0
    log_warning "Docker daemon not responding; attempting to start it..."
    sudo -n systemctl start docker.socket docker.service 2>/dev/null || true
    local waited=0
    until docker info >/dev/null 2>&1; do
        if [ $waited -ge 60 ]; then
            log_error "Docker daemon did not come up after ${waited}s"
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
    log_info "Docker daemon is up"
}

find_ghost_containers() {
    local compose_config project ids id
    # Compose matches containers by project name, so ghosts must be found by
    # that same key - and only under the name compose actually resolves to
    # right now (covering .env, COMPOSE_PROJECT_NAME, top-level `name:`, and
    # moved checkouts). `docker compose config` is the authority on that.
    # Note: this function's stdout is the ghost list, so warnings go to
    # stderr, and unresolvable config fails closed (no ghosts, no surgery).
    if ! compose_config=$(docker compose config 2>/dev/null); then
        log_warning "Cannot resolve Compose configuration; skipping ghost detection" >&2
        return 1
    fi

    project=$(printf '%s\n' "$compose_config" | sed -n 's/^name:[[:space:]]*//p')
    if ! [[ "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        log_warning "Cannot resolve a valid Compose project name" >&2
        return 1
    fi

    if ! ids=$(docker ps -aq --no-trunc \
        --filter "label=com.docker.compose.project=$project" 2>/dev/null); then
        return 1
    fi

    while IFS= read -r id; do
        [ -n "$id" ] || continue
        docker inspect "$id" >/dev/null 2>&1 || printf '%s\n' "$id"
    done <<< "$ids"
}

recover_ghost_containers() {
    local ghosts
    ghosts=$(find_ghost_containers)
    if [ -z "$ghosts" ]; then
        return 1
    fi
    log_warning "Ghost container records detected (listed but not inspectable):"
    log_warning "$ghosts"

    # Cheap path first; rm typically fails for true ghosts.
    echo "$ghosts" | xargs -r docker rm -f 2>/dev/null || true
    if [ -z "$(find_ghost_containers)" ]; then
        log_info "Ghost containers removed"
        return 0
    fi

    # The heal stops the Docker daemon (bouncing every running container), so
    # at most once per boot: if it did not clear the ghosts a human is needed,
    # and systemd's retries must not keep bouncing the daemon.
    local boot_id
    boot_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null)
    if [ -z "$boot_id" ]; then
        log_error "Cannot read boot id; refusing unguarded surgery"
        return 1
    fi
    if [ "$(cat "$DOCKER_HEAL_MARKER" 2>/dev/null)" = "$boot_id" ]; then
        log_warning "Ghost heal already attempted this boot; not doing it again"
        return 1
    fi
    # Fail closed: if the marker cannot be persisted the surgery would repeat
    # on every systemd retry, bouncing the daemon forever - e.g. on a disk
    # that just went read-only, the same failure that makes the heal fail.
    if ! echo "$boot_id" > "$DOCKER_HEAL_MARKER" 2>/dev/null; then
        log_error "Cannot write heal marker $DOCKER_HEAL_MARKER; skipping surgery"
        return 1
    fi

    log_warning "Ghosts survived removal; removing their records with the daemon stopped..."
    # shellcheck disable=SC2086  # ghost IDs are intentionally word-split
    if ! sudo -n "$PROJECT_ROOT/deployment/docker-ghost-heal.sh" $ghosts; then
        log_error "Ghost heal failed (sudoers rule missing? re-run install.sh)"
        return 1
    fi

    ensure_docker_running || return 1

    if [ -n "$(find_ghost_containers)" ]; then
        log_error "Ghost containers still present after heal"
        return 1
    fi
    log_info "Ghost containers healed, Docker daemon responding"
}

# Run `docker compose up -d` (with any extra args); on failure, attempt
# ghost-container recovery and retry once.
compose_up_with_recovery() {
    ensure_docker_running || return 1
    if docker compose up -d "$@"; then
        return 0
    fi
    log_warning "compose up failed, checking for ghost container records..."
    recover_ghost_containers || return 1
    docker compose up -d "$@"
}

# Function to start Docker containers
start_containers() {
    log_info "Starting Docker containers..."
    cd "$PROJECT_ROOT"

    # Clean up orphaned containers first
    cleanup_orphaned_containers

    if compose_up_with_recovery; then
        log_info "Docker containers started successfully"
        # A full stack start means any update is over; drop the stage file so
        # /update-progress doesn't keep serving the last stage between
        # updates. (The banner itself is protected by the dispatch-time
        # reset in the API — this is just hygiene.)
        rm -f "$UPDATE_PROGRESS_FILE" 2>/dev/null || true
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
    if compose_up_with_recovery --force-recreate; then
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
# Delegates to install.sh --update which handles:
# - Git sync (fetch + reset to target branch)
# - Docker image builds
# - System config updates (PulseAudio, systemd, sudoers)
perform_system_update() {
    log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log_info "System update requested, delegating to install.sh..."
    log_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Read target branch from flag content BEFORE deleting flag
    # Flag content is the branch name (e.g., "main" or "staging")
    local target_branch
    target_branch=$(tr -d '\n\r' < "$UPDATE_FLAG_FILE" 2>/dev/null) || true
    rm -f "$UPDATE_FLAG_FILE"

    # Validate branch name against whitelist to prevent command injection
    # Only allow known branch names; default to empty (current branch) if invalid
    case "$target_branch" in
        main|staging)
            log_info "Target branch: $target_branch"
            ;;
        "")
            log_info "No target branch specified, using current branch"
            ;;
        *)
            log_warning "Invalid branch name '$target_branch', ignoring"
            target_branch=""
            ;;
    esac

    # Delegate to install.sh --update (runs as root via sudo)
    # This handles: git sync, build, system configs, exit for restart
    local exit_code=0
    if [ -n "$target_branch" ]; then
        sudo "$PROJECT_ROOT/install.sh" --update --branch "$target_branch" || exit_code=$?
    else
        sudo "$PROJECT_ROOT/install.sh" --update || exit_code=$?
    fi

    if [ $exit_code -eq 0 ]; then
        # install.sh exits with 0 after successful update
        # systemd will restart this service with new code
        exit 0
    else
        # Check if this was a sudo permission failure
        if [ $exit_code -eq 1 ] && ! sudo -n true 2>/dev/null; then
            log_error "Update failed: sudo permission denied"
            log_error "Sudoers may not be configured for install.sh --update"
            log_error "Fix by running: cd $PROJECT_ROOT && sudo ./install.sh"
        else
            # install.sh handles container restart on failure internally
            log_error "Update failed (exit code: $exit_code)"
            log_error "Check logs: /var/log/birdnet-pipy-install.log"
        fi
        # Mark the run failed for the frontend's update poll. install.sh
        # normally writes this itself; this covers it dying before it could
        # (e.g. sudo denied). Remove-then-recreate in case the existing file
        # is root-owned — the flags dir itself is writable by this user.
        # Never overwrite an existing 'success': install.sh stamps it once
        # the new code has landed, so a later config-step death must not be
        # reported as "still on the previous version".
        if [ "$(cat "$UPDATE_STATUS_FILE" 2>/dev/null | tr -d '\n\r')" != "success" ]; then
            rm -f "$UPDATE_STATUS_FILE" 2>/dev/null || true
            echo "failed" > "$UPDATE_STATUS_FILE" 2>/dev/null || true
        fi
        return 1
    fi
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
        local swap_size
        swap_size=$(free -h | grep Swap | awk '{print $2}')
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
