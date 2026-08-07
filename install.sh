#!/bin/bash
# BirdNET-PiPy Unified Installation Script
# Can be run via curl or locally after cloning repository
#
# Remote curl usage:
#   curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash
#
# Local usage (after cloning):
#   cd BirdNET-PiPy && sudo ./install.sh

set -e
set -o pipefail

# Ignore SIGHUP so installation continues if SSH session disconnects
# User can reconnect and tail /var/log/birdnet-pipy-install.log to monitor progress
trap '' HUP

# ============================================================================
# Configuration & Constants
# ============================================================================

REPO_URL="https://github.com/Suncuss/BirdNET-PiPy.git"
REPO_BRANCH="main"
SERVICE_NAME="birdnet-pipy"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# Script detection
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || pwd)"

# Detect if running from git repo (Stage 2) or remotely (Stage 1)
# Must have .git AND BirdNET-specific files to be considered local install
# If BASH_SOURCE[0] is empty or "-", we're piped from stdin (remote mode)
if [ -z "${BASH_SOURCE[0]}" ] || [ "${BASH_SOURCE[0]}" = "-" ]; then
    IS_LOCAL_INSTALL=false
    PROJECT_ROOT=""
elif [ -d "$SCRIPT_DIR/.git" ] && [ -f "$SCRIPT_DIR/docker-compose.yml" ] && [ -f "$SCRIPT_DIR/build.sh" ]; then
    IS_LOCAL_INSTALL=true
    PROJECT_ROOT="$SCRIPT_DIR"
else
    IS_LOCAL_INSTALL=false
    PROJECT_ROOT=""
fi

# Logging setup - use /var/log for persistence across reboots
LOG_FILE="/var/log/birdnet-pipy-install.log"

# Initialize logging (only once, even across re-exec from curl install)
setup_logging() {
    # Skip if already set up (prevents duplicate output when script re-executes itself)
    [ -n "$_BIRDNET_LOGGING" ] && return 0
    export _BIRDNET_LOGGING=1

    # Try /var/log, fall back to /tmp if not writable
    touch "$LOG_FILE" 2>/dev/null || LOG_FILE="/tmp/birdnet-pipy-install.log"

    # Write header (append to preserve history across retries)
    echo "" >> "$LOG_FILE"
    echo "========== Installation started: $(date) ==========" >> "$LOG_FILE"

    # Capture all output: terminal gets colors, log file gets plain text
    # The sed strips ANSI color codes (e.g., \033[0;32m) and carriage returns from the log file
    exec > >(tee >(sed 's/\x1b\[[0-9;]*m//g; s/\r//g' >> "$LOG_FILE")) 2>&1
}

# Initialize logging immediately
setup_logging

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Command-line options
UPDATE_MODE=false
TARGET_BRANCH=""  # Target branch for install/update (default: main for install, current for update)
NO_REBOOT=false   # Skip reboot prompt (for testing)
SKIP_BUILD=false  # Skip Docker image build (for testing)
WEB_PORT=""       # Host port for the web interface (--port; empty = keep existing .env value or default 80)

# ============================================================================
# Logging Functions
# ============================================================================

print_status() {
    echo -e "${GREEN}[INSTALL]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# ============================================================================
# Utility Functions
# ============================================================================

# Check if running as root and using sudo
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run as root (use sudo)"
        print_info "Example: sudo ./install.sh"
        exit 1
    fi

    # Check if running as direct root (not via sudo)
    if [ "$EUID" -eq 0 ] && [ -z "$SUDO_USER" ]; then
        print_error "Please run this script with sudo, not as direct root"
        print_info "Example: sudo ./install.sh"
        exit 1
    fi
}

# Get the actual user (not root when using sudo)
get_actual_user() {
    if [ -n "$SUDO_USER" ]; then
        echo "$SUDO_USER"
    else
        echo "$USER"
    fi
}

# Set global user variables (called once from main after check_root)
init_user_vars() {
    ACTUAL_USER=$(get_actual_user)
    ACTUAL_UID=$(id -u "$ACTUAL_USER")
    ACTUAL_GID=$(id -g "$ACTUAL_USER")
}

# Resolve a command's binary path (checks PATH, then common sbin locations)
_bin() {
    command -v "$1" 2>/dev/null \
        || { [ -x "/usr/sbin/$1" ] && echo "/usr/sbin/$1"; } \
        || { [ -x "/sbin/$1" ] && echo "/sbin/$1"; } \
        || echo "/usr/bin/$1"
}

# Detect platform
detect_platform() {
    # Check if Linux
    if [ "$(uname -s)" != "Linux" ]; then
        print_error "This script only supports Linux"
        print_info "Detected platform: $(uname -s)"
        exit 1
    fi

    # Detect distribution
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID=$ID
        OS_NAME=$NAME
        print_status "Detected platform: $OS_NAME"
    else
        print_warning "Cannot detect OS distribution"
        OS_ID="linux"
    fi

    # Check if Debian-based (for apt-get)
    if ! command -v apt-get &> /dev/null; then
        print_error "This script requires apt-get (Debian/Ubuntu/Raspberry Pi OS)"
        exit 1
    fi

    # Require a 64-bit OS. BirdNET-PiPy ships arm64-only Python wheels
    # (onnxruntime, tflite-runtime), so 32-bit Raspberry Pi OS cannot run it.
    # Reject early with a clear message instead of failing deep in the build
    # (or on the missing Docker repo for 'raspbian' codenames like trixie).
    local arch
    arch=$(dpkg --print-architecture)
    case "$arch" in
        armhf|armel|i386)
            print_error "32-bit OS detected (architecture: $arch)"
            print_info "BirdNET-PiPy requires a 64-bit OS (Raspberry Pi OS 64-bit, Bookworm+)."
            print_info "Reflash with the 64-bit image and re-run the installer."
            exit 1
            ;;
    esac
}

# Show usage
show_usage() {
    echo "BirdNET-PiPy Unified Installation Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --update             Update existing installation (git sync + build + config)"
    echo "  --branch BRANCH      Target branch (default: main for install, current for update)"
    echo "  --port PORT          Host port for the web interface (default: 80, remembered across updates)"
    echo "  --no-reboot          Skip automatic reboot after installation (for testing)"
    echo "  --skip-build         Skip Docker image build (for testing)"
    echo "  --help               Show this help message"
    echo ""
    echo "Examples:"
    echo "  # Quick install with defaults (main branch)"
    echo "  curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash"
    echo ""
    echo "  # Install from staging branch (latest features)"
    echo "  curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash -s -- --branch staging"
    echo ""
    echo "  # Install with the web interface on port 8080 (port 80 already taken)"
    echo "  curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash -s -- --port 8080"
    echo ""
    echo "  # Update existing installation"
    echo "  sudo ./install.sh --update"
}

# ============================================================================
# Prerequisites Installation (Batched for speed)
# ============================================================================

# Install all prerequisites in one batch to minimize apt-get update calls
install_prerequisites() {
    print_status "Checking prerequisites..."

    local packages_to_install=()

    # Git (needed for clone/pull)
    if ! command -v git &> /dev/null; then
        packages_to_install+=("git")
    fi

    # Docker prerequisites (only if Docker not installed)
    if ! command -v docker &> /dev/null; then
        # These are needed to add Docker repository
        packages_to_install+=("ca-certificates" "curl" "gnupg" "lsb-release")
    fi

    # PulseAudio (needed for audio)
    # Skip if PipeWire is installed - it provides PulseAudio compatibility via pipewire-pulse
    # On Desktop Pi OS, pipewire-pulse creates /run/user/$UID/pulse/native socket
    if ! command -v pulseaudio &> /dev/null && ! command -v pipewire &> /dev/null; then
        packages_to_install+=("pulseaudio" "pulseaudio-utils" "alsa-utils")
    fi

    if [ ${#packages_to_install[@]} -gt 0 ]; then
        print_status "Installing prerequisites: ${packages_to_install[*]}"
        apt-get update
        apt-get install -y "${packages_to_install[@]}"
        print_status "Prerequisites installed"
    else
        print_status "All prerequisites already installed, skipping apt-get update"
    fi
}

# ============================================================================
# Stage 1: Clone Repository Logic
# ============================================================================

# Clone repository
clone_repository() {
    print_status "Cloning BirdNET-PiPy repository..."

    # Determine target branch (default: main)
    local branch="${TARGET_BRANCH:-$REPO_BRANCH}"

    # Determine installation directory
    INSTALL_DIR="/home/$ACTUAL_USER/BirdNET-PiPy"

    print_info "Installation directory: $INSTALL_DIR"
    [ "$branch" != "main" ] && print_info "Target branch: $branch"

    # Check if directory already exists
    if [ -d "$INSTALL_DIR" ]; then
        print_warning "Directory already exists: $INSTALL_DIR"

        # Check if it's a git repo
        if [ -d "$INSTALL_DIR/.git" ]; then
            # Verify it's the correct BirdNET-PiPy repo before pulling
            CURRENT_REPO=$(cd "$INSTALL_DIR" && git config --get remote.origin.url 2>/dev/null || echo "")

            if [ "$CURRENT_REPO" = "$REPO_URL" ]; then
                print_status "Existing BirdNET-PiPy repository found, pulling latest changes..."
                cd "$INSTALL_DIR"
                git checkout "$branch"
                git pull origin "$branch" || {
                    print_error "Failed to update repository"
                    exit 1
                }
                chown -R "$ACTUAL_USER:$ACTUAL_USER" "$INSTALL_DIR"
            else
                print_error "Directory exists but contains a different git repository"
                print_error "Expected: $REPO_URL"
                print_error "Found: $CURRENT_REPO"
                print_info "Please remove or rename: $INSTALL_DIR"
                exit 1
            fi
        else
            print_error "Directory exists but is not a git repository"
            print_info "Please remove or rename: $INSTALL_DIR"
            exit 1
        fi
    else
        # Clone fresh (shallow clone for speed - full history not needed)
        git clone --depth 1 -b "$branch" "$REPO_URL" "$INSTALL_DIR" || {
            print_error "Failed to clone repository"
            exit 1
        }
        print_status "Repository cloned to $INSTALL_DIR (branch: $branch)"
        chown -R "$ACTUAL_USER:$ACTUAL_USER" "$INSTALL_DIR"
    fi

    # Validate clone
    validate_clone "$INSTALL_DIR"
}

# Validate cloned repository
validate_clone() {
    local install_dir=$1
    local required_files=(
        "docker-compose.yml"
        "build.sh"
        "deployment/birdnet-service.sh"
        "deployment/audio/pulseaudio/system.pa"
    )

    for file in "${required_files[@]}"; do
        if [ ! -f "$install_dir/$file" ]; then
            print_error "Clone validation failed: missing $file"
            exit 1
        fi
    done

    print_status "Repository validation passed"
}

# Re-execute script from cloned repository
reexec_from_clone() {
    print_status "Re-executing from cloned repository..."
    cd "$INSTALL_DIR"
    chmod +x install.sh

    # Pass through all original arguments
    exec bash install.sh "$@"
}

# ============================================================================
# Stage 2: Docker Installation
# ============================================================================

# Install Docker using official method
install_docker() {
    print_status "Installing Docker..."
    print_info "This may take a few minutes..."

    # Prerequisites (ca-certificates, curl, gnupg, lsb-release) are already
    # installed by install_prerequisites() - no apt-get update needed here

    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/$OS_ID/gpg" | \
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Set up repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/$OS_ID $(lsb_release -cs) stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker Engine
    apt-get update
    apt-get install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin

    print_status "Docker installed successfully"
}

# Add user to docker group
setup_docker_user() {
    if ! groups "$ACTUAL_USER" | grep -q docker; then
        usermod -aG docker "$ACTUAL_USER"
        print_status "Added $ACTUAL_USER to docker group"
        print_warning "IMPORTANT: Log out and back in for docker group to take effect"
        print_warning "Or run: newgrp docker"
    else
        print_status "User $ACTUAL_USER already in docker group"
    fi
}

# ============================================================================
# Application Setup (Ported from deployment/install-service.sh)
# ============================================================================

# Configure PulseAudio for audio multiplexing
# Note: PulseAudio packages are installed by install_prerequisites()
configure_pulseaudio() {
    print_info ""
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_info "PulseAudio Setup (Required for audio recording)"
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Check if user-mode PulseAudio/PipeWire is already available (Desktop Pi OS)
    local user_pulse_socket="/run/user/$ACTUAL_UID/pulse/native"

    if [ -S "$user_pulse_socket" ]; then
        # Desktop Pi OS - user-mode audio already running
        print_status "User-mode PulseAudio/PipeWire detected"
        print_info "Socket found at: $user_pulse_socket"
        print_info "Skipping system-wide PulseAudio configuration (not needed)"

        # Still create pulse-access group for bind mount permissions
        if ! getent group pulse-access > /dev/null; then
            groupadd --system pulse-access
        fi
        usermod -a -G pulse-access,audio "$ACTUAL_USER"

        print_status "PulseAudio setup complete (using existing user-mode audio)"
        return 0
    fi

    # Lite Pi OS - need to configure system-wide PulseAudio
    print_status "No user-mode audio detected, configuring system-wide PulseAudio..."

    # Disable user-mode PulseAudio services to prevent conflicts
    # These services can start when users SSH in and interfere with system-wide mode
    # The user-mode PulseAudio often hangs on headless systems (no desktop/D-Bus services)
    systemctl --global disable pulseaudio.service pulseaudio.socket 2>/dev/null || true
    systemctl --global mask pulseaudio.service pulseaudio.socket 2>/dev/null || true
    print_info "Disabled user-mode PulseAudio services (using system-wide mode instead)"

    # Backup existing configs if present
    if [ -f /etc/pulse/system.pa ]; then
        cp /etc/pulse/system.pa /etc/pulse/system.pa.backup
        print_info "Backed up existing system.pa"
    fi
    if [ -f /etc/pulse/daemon.conf ]; then
        cp /etc/pulse/daemon.conf /etc/pulse/daemon.conf.backup
        print_info "Backed up existing daemon.conf"
    fi

    # Copy our configuration
    cp "$PROJECT_ROOT/deployment/audio/pulseaudio/system.pa" /etc/pulse/system.pa
    cp "$PROJECT_ROOT/deployment/audio/pulseaudio/daemon.conf" /etc/pulse/daemon.conf

    # Create pulse user and group if they don't exist
    if ! getent group pulse > /dev/null; then
        groupadd --system pulse
    fi
    if ! id pulse > /dev/null 2>&1; then
        useradd --system -g pulse -G audio pulse
    fi

    # Create pulse-access group for Docker containers
    if ! getent group pulse-access > /dev/null; then
        groupadd --system pulse-access
    fi

    # Add actual user to pulse-access group
    usermod -a -G pulse-access,audio "$ACTUAL_USER"

    print_status "PulseAudio setup complete (system-wide mode)"
    print_info "PulseAudio will be started by birdnet-service.sh"
}

# Ensure adequate swap on low-memory systems (e.g. Pi Zero 2W with 512MB RAM).
# Swap is needed both for building and running (model inference + Docker containers).
# Idempotent: skips if sufficient swap is already available.
setup_swap() {
    local threshold_kb=1048576  # 1GB
    local needed_mb=2048        # 2GB swap
    local swap_file="/swapfile-birdnet-pipy"

    local ram_kb
    ram_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')

    # Only set up swap on low-memory systems
    if [ "$ram_kb" -ge "$threshold_kb" ]; then
        return 0
    fi

    local current_mb
    current_mb=$(free -m | awk '/Swap:/ {print $2}')

    if [ "$current_mb" -ge "$needed_mb" ]; then
        print_status "Sufficient swap already available (${current_mb}MB)"
        return 0
    fi

    print_status "Low memory detected ($(( ram_kb / 1024 ))MB RAM). Setting up ${needed_mb}MB swap..."

    # Disable existing swap file if present
    if [ -f "$swap_file" ]; then
        swapoff "$swap_file" 2>/dev/null || true
        rm -f "$swap_file"
    fi

    # Create swap file (fallocate is fast, dd is slow fallback)
    if fallocate -l "${needed_mb}M" "$swap_file" 2>/dev/null; then
        print_status "Swap file allocated with fallocate"
    else
        print_info "Using dd to create swap file (this may take a moment)..."
        dd if=/dev/zero of="$swap_file" bs=1M count="$needed_mb" status=progress
    fi

    chmod 600 "$swap_file"
    mkswap "$swap_file"
    swapon "$swap_file"

    print_status "Swap enabled (${needed_mb}MB)"
}

# Marker comment identifying the gpu_mem line we add, so uninstall.sh can
# remove exactly what we wrote. Keep in sync with uninstall.sh.
GPU_MEM_MARKER="# BirdNET-PiPy: headless low-RAM device, reclaim GPU memory for the OS"

# Append gpu_mem=16 to a boot config file. config.txt is section-filtered
# ([pi4], [cm5], ...), so re-open [all] when the file's last section header
# would otherwise scope our setting to one board. Idempotent: any existing
# gpu_mem line (the user's or ours) wins.
apply_gpu_mem_to_config() {
    local cfg="$1"

    if grep -Eq '^[[:space:]]*gpu_mem' "$cfg"; then
        return 0
    fi

    # `|| true` keeps set -e/pipefail from aborting when the file has no section headers
    local last_section
    last_section=$(grep -E '^\[' "$cfg" | tail -1 || true)
    {
        echo ""
        if [ -n "$last_section" ] && [ "$last_section" != "[all]" ]; then
            echo "[all]"
        fi
        echo "$GPU_MEM_MARKER"
        echo "gpu_mem=16"
    } >> "$cfg"
}

# Reclaim GPU memory on headless low-RAM Raspberry Pis (e.g. Pi Zero 2W, 512MB).
# The modern KMS graphics stack and libcamera allocate from ARM memory, so a
# headless station wastes the default 64MB firmware split; gpu_mem=16 returns
# ~48MB (~11% of a Zero 2W's RAM) to Linux. Takes effect at the next reboot.
# Deliberately conservative: skips non-Pi hardware, desktop systems, existing
# gpu_mem settings, and legacy-camera (start_x=1) configs.
# Runs on install and update, so deleting our block gets re-applied; the
# supported opt-out is setting your own gpu_mem value, which is always respected.
setup_gpu_mem() {
    grep -aq "Raspberry Pi" /proc/device-tree/model 2>/dev/null || return 0

    # Only low-memory systems (same threshold as setup_swap)
    local ram_kb
    ram_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    [ "$ram_kb" -lt 1048576 ] || return 0

    # Only headless systems — a desktop may want the GPU split
    [ "$(systemctl get-default 2>/dev/null)" = "multi-user.target" ] || return 0

    local cfg="/boot/firmware/config.txt"
    [ -f "$cfg" ] || cfg="/boot/config.txt"
    [ -f "$cfg" ] || return 0

    if grep -Eq '^[[:space:]]*gpu_mem' "$cfg"; then
        print_status "GPU memory split already configured in $cfg (leaving as is)"
        return 0
    fi

    # Legacy camera stack requires gpu_mem >= 128 — don't break it
    if grep -Eq '^[[:space:]]*start_x[[:space:]]*=[[:space:]]*1' "$cfg"; then
        print_info "Legacy camera stack detected (start_x=1) — keeping default GPU memory split"
        return 0
    fi

    # Propagate append failure (e.g. read-only /boot) so the call-site warning fires
    apply_gpu_mem_to_config "$cfg" || return 1
    print_status "Headless low-memory device: set gpu_mem=16 in $cfg (reclaims ~48MB RAM at next reboot)"
}

# Update a single key in .env without overwriting other settings.
# Uses grep -v + append to avoid sed metacharacter issues.
set_env_var() {
    local key="$1" value="$2"
    local env_file="$PROJECT_ROOT/.env"

    if [ -f "$env_file" ]; then
        grep -v "^${key}=" "$env_file" > "${env_file}.tmp" || true
        mv "${env_file}.tmp" "$env_file"
    fi
    echo "${key}=${value}" >> "$env_file"
}

# Validate a --port value: an integer in 1-65535 that doesn't collide with
# the loopback ports the backend services already publish (see docker-compose.yml).
validate_web_port() {
    local port="$1"
    if ! [[ "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
        print_error "Invalid --port value '$port' (expected a number between 1 and 65535)"
        return 1
    fi
    case "$port" in
        5001|5002|8888)
            print_error "Port $port is already used internally by BirdNET-PiPy services"
            return 1
            ;;
    esac
}

# Record the web port in .env so docker-compose publishes the frontend there.
# .env is untracked, so the choice survives updates (git reset doesn't touch it).
persist_web_port() {
    local port="$1"
    # Warn-only: the port may be held by a service that won't be there after
    # reboot — or by our own still-running frontend during an update.
    if command -v ss >/dev/null 2>&1 \
        && ss -tlnH 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}\$"; then
        print_warning "Port $port appears to be in use; if another service owns it, the web interface will fail to start"
    fi
    set_env_var "BIRDNET_WEB_PORT" "$port"
    print_status "Web interface port set to $port"
}

# Effective web port: this run's --port, else the persisted .env value, else 80.
effective_web_port() {
    local port="$WEB_PORT"
    if [ -z "$port" ] && [ -f "$PROJECT_ROOT/.env" ]; then
        port=$(grep -E '^BIRDNET_WEB_PORT=' "$PROJECT_ROOT/.env" | tail -1 | cut -d= -f2 || true)
    fi
    echo "${port:-80}"
}

# Free disk space before an update fetch/build without removing runnable images.
# This is update-only on purpose: installs can start clean, while updates need to
# preserve existing images for failure recovery if the new pull/build does not finish.
prune_docker_before_update() {
    print_status "Cleaning up Docker artifacts before update..."

    local image_reclaimed
    image_reclaimed=$(docker image prune -f 2>/dev/null \
        | grep -E '^Total( reclaimed space)?:' | awk '{print $NF}') || true
    print_status "Cleanup: reclaimed ${image_reclaimed:-0B} from dangling images"

    # Cap the build cache instead of wiping it (an unfiltered prune removes all
    # unused cache on modern engines): least-recently-used entries go first, so
    # if the pull fails and we fall back to a local build, it still runs warm.
    # Older engines lack --max-used-space; fall back to its pre-buildx-0.17 name
    # --keep-storage, then to an age filter. The summary line differs across
    # versions ("Total:" vs "Total reclaimed space:"), so accept both.
    # Same resolution as build.sh: env var, then .env, then the 5GB default
    local cache_limit="${BUILD_CACHE_LIMIT:-}"
    if [ -z "$cache_limit" ] && [ -n "${PROJECT_ROOT:-}" ] && [ -f "$PROJECT_ROOT/.env" ]; then
        cache_limit=$(grep -E '^BUILD_CACHE_LIMIT=' "$PROJECT_ROOT/.env" | tail -1 | cut -d= -f2 || true)
    fi
    cache_limit="${cache_limit:-5GB}"
    local cache_reclaimed
    cache_reclaimed=$( (docker builder prune --max-used-space="$cache_limit" -f 2>/dev/null \
        || docker builder prune --keep-storage="$cache_limit" -f 2>/dev/null \
        || docker builder prune --filter "until=168h" -f 2>/dev/null) \
        | grep -E '^Total( reclaimed space)?:' | awk '{print $NF}') || true
    print_status "Cleanup: reclaimed ${cache_reclaimed:-0B} from build cache (cap: $cache_limit)"
}

# Try to pull pre-built images from GHCR, fall back to local build.
# Skips pull for unsupported architectures, non-release branches, and
# non-1000 UID systems.
pull_or_build() {
    # -C: fresh installs call this without cd-ing into the repo first, so don't
    # rely on the caller's working directory for git context.
    local repo="Suncuss/BirdNET-PiPy"
    local target_branch="${TARGET_BRANCH:-$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD)}"
    local can_pull=true

    case "$target_branch" in
        main|staging) set_env_var "BIRDNET_CHANNEL" "$target_branch" ;;
        *)
            set_env_var "BIRDNET_CHANNEL" "main"
            print_status "Branch '$target_branch' has no pre-built images, building locally..."
            can_pull=false
            ;;
    esac

    # Short-circuit before any network checks, but after the branch handling so
    # --skip-build still records BIRDNET_CHANNEL and reports the build fallback.
    if [ "$SKIP_BUILD" = true ]; then
        build_application
        return $?
    fi

    # Pre-built images cover ARM64 (Raspberry Pi) and AMD64 via multi-arch
    # manifests; anything else (e.g. 32-bit armv7l) builds locally. Older
    # commits published ARM64-only tags — pulling one of those on AMD64
    # fails with "no matching manifest" and falls back to a local build
    # through the normal pull-failure path.
    local arch
    arch=$(uname -m)
    if [ "$can_pull" = true ] && [ "$arch" != "aarch64" ] && [ "$arch" != "x86_64" ]; then
        print_status "Architecture $arch has no pre-built images, building locally..."
        can_pull=false
    fi

    # Pre-built images are baked with UID/GID 1000 (default Pi user)
    if [ "$can_pull" = true ] && [ "$ACTUAL_UID" != "1000" ]; then
        print_status "Non-standard UID ($ACTUAL_UID), building locally for correct permissions..."
        can_pull=false
    fi

    if [ "$can_pull" = false ]; then
        build_application
        return $?
    fi

    # Check if the image build workflow completed for this commit. Captured here
    # (not at the top) so the skip-build / unsupported-arch / non-1000-UID fast
    # paths above don't run an unused git call that set -e could trip on.
    local commit
    commit=$(git -C "$PROJECT_ROOT" rev-parse HEAD)
    local api_response
    api_response=$(curl -s --connect-timeout 3 --max-time 5 \
        "https://api.github.com/repos/$repo/actions/workflows/build-images.yml/runs?head_sha=$commit&status=completed&per_page=1" 2>/dev/null) || true

    if [[ "$api_response" == *'"conclusion"'*'"success"'* ]]; then
        print_status "Pre-built images available, pulling from registry..."
        cd "$PROJECT_ROOT"
        # Pull each unique image sequentially to avoid saturating the Pi's network.
        # Derive the image list from docker-compose.yml so it stays in sync automatically.
        local -a pull_images
        mapfile -t pull_images < <(sudo -u "$ACTUAL_USER" docker compose config --images | sort -u)
        if [ ${#pull_images[@]} -eq 0 ]; then
            print_warning "Could not resolve image list from docker-compose.yml, falling back to local build..."
            build_application
            return $?
        fi
        local pull_ok=true
        local max_retries=3
        local attempt
        local pull_index=0
        for img in "${pull_images[@]}"; do
            pull_index=$((pull_index + 1))
            # Counters only, not image names: /update-progress is public
            write_update_progress "pull" "Pulling the latest images from GHCR ($pull_index of ${#pull_images[@]})"
            for attempt in $(seq 1 $max_retries); do
                if sudo -u "$ACTUAL_USER" docker pull "$img"; then
                    break
                fi
                if [ "$attempt" -lt "$max_retries" ]; then
                    print_warning "Pull of $img failed (attempt $attempt/$max_retries), retrying in 10s..."
                    sleep 10
                else
                    print_warning "Pull of $img failed after $max_retries attempts"
                    pull_ok=false
                fi
            done
            # Stop pulling remaining images if one failed
            [ "$pull_ok" = true ] || break
        done
        if [ "$pull_ok" = true ]; then
            refresh_version_info
            docker image prune -f >/dev/null 2>&1 || true
            print_status "Images pulled successfully"
            return 0
        fi
        print_warning "Pull failed, falling back to local build..."
    else
        print_status "Pre-built images not ready, building locally..."
    fi

    build_application
}

# Build Docker images
# Optional arg: $1 = space-separated list of services to build
# shellcheck disable=SC2120  # $1 is intentionally optional (services list)
build_application() {
    if [ "$SKIP_BUILD" = true ]; then
        print_status "Skipping Docker image build (--skip-build flag)"
        return 0
    fi

    local services="$1"

    print_status "Building BirdNET-PiPy application..."
    print_status "Building as user $ACTUAL_USER (UID:$ACTUAL_UID, GID:$ACTUAL_GID)..."
    write_update_progress "build" "Building images locally"

    cd "$PROJECT_ROOT"
    chmod +x build.sh

    local build_args=()
    if [ -n "$services" ]; then
        # Convert space-separated to comma-separated for CLI transport
        local csv_services="${services// /,}"
        build_args=(--services "$csv_services")
    fi

    # Forward BUILD_CACHE_LIMIT: sudo's env_reset would strip an operator's override
    if ! sudo -u "$ACTUAL_USER" UID="$ACTUAL_UID" GID="$ACTUAL_GID" \
        BUILD_CACHE_LIMIT="${BUILD_CACHE_LIMIT:-}" ./build.sh "${build_args[@]}"; then
        return 1
    fi
    print_status "Application built successfully"
}

# Generate version.json without building Docker images
refresh_version_info() {
    print_status "Refreshing version info..."
    cd "$PROJECT_ROOT"
    chmod +x build.sh
    if ! sudo -u "$ACTUAL_USER" UID="$ACTUAL_UID" GID="$ACTUAL_GID" ./build.sh --version-only; then
        print_warning "Failed to refresh version info (data/version.json may be stale)"
        return 1
    fi
    print_status "Version info refreshed"
    return 0
}

# Owner-only mode on the config files: they hold RTSP camera credentials,
# Apprise notification URLs and the station coordinates. New writes get 0600
# from the app itself; this repairs installs that predate that. Deliberately
# separate from fix_data_permissions so the update path can call it without
# also running a recursive chown over a data/ directory that can reach tens of
# gigabytes.
fix_config_permissions() {
    chmod 600 "$PROJECT_ROOT"/data/config/*.json 2>/dev/null || true
}

# Fix existing data folder permissions
fix_data_permissions() {
    print_status "Setting up data directory permissions..."

    # Create data and flags directories (mkdir -p handles both)
    mkdir -p "$PROJECT_ROOT/data/flags"

    chown -R "$ACTUAL_USER:$ACTUAL_USER" "$PROJECT_ROOT/data"
    fix_config_permissions

    print_status "Data permissions fixed for user $ACTUAL_USER"
}

# Create systemd service file
create_service_file() {
    print_status "Creating systemd service file..."

    local RUNTIME_SCRIPT="$PROJECT_ROOT/deployment/birdnet-service.sh"

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=BirdNET-PiPy Bird Detection Service
Documentation=https://github.com/Suncuss/BirdNET-PiPy
After=docker.service network.target
Requires=docker.service

# Rate limiting: max 5 restarts in 5 minutes to prevent infinite loops
StartLimitBurst=5
StartLimitIntervalSec=300

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$PROJECT_ROOT
ExecStart=$RUNTIME_SCRIPT
StandardOutput=journal
StandardError=journal

# Auto-restart on any exit (crash recovery + update support)
# After a successful update, the service exits and systemd restarts it with new code
Restart=always
RestartSec=10

# Graceful shutdown (90s for slow systems like Pi Zero)
TimeoutStopSec=90
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF

    print_status "Service file created: $SERVICE_FILE"
}

# Install and enable service
install_service() {
    print_status "Installing systemd service..."

    # Reload systemd daemon
    systemctl daemon-reload

    # Enable service (auto-start on boot)
    systemctl enable "$SERVICE_NAME"

    print_status "Service installed and enabled"
}

# Setup sudoers for passwordless audio operations
# The service runs as non-root but needs sudo for PulseAudio/mount operations
setup_sudoers() {
    print_status "Setting up sudoers for audio operations..."

    local SUDOERS_FILE="/etc/sudoers.d/birdnet-pipy"

    # Create sudoers file with specific permissions for audio operations
    cat > "$SUDOERS_FILE" << EOF
# BirdNET-PiPy sudoers configuration
# Allows the service user to manage PulseAudio without password prompts
# Created by install.sh - remove with: sudo rm $SUDOERS_FILE

# PulseAudio management
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin pulseaudio) --system *
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin pulseaudio) --kill

# Mount operations for PulseAudio socket bind mount
# UID is pinned, not globbed: sudo-rs (Ubuntu 25.10+) rejects wildcards in command arguments
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin mount) --bind /run/user/$ACTUAL_UID/pulse /run/pulse
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin umount) /run/pulse

# Directory operations in /run/pulse
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin mkdir) -p /run/pulse
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin chown) pulse\:pulse-access /run/pulse
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin chmod) 755 /run/pulse
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin rm) -f /run/pulse/native
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin rm) -f /run/pulse/pid

# Enable swap (optional, only if /swapfile-birdnet-pipy exists)
$ACTUAL_USER ALL=(ALL) NOPASSWD: $(_bin swapon) /swapfile-birdnet-pipy

# System update via install.sh --update (with optional --branch)
$ACTUAL_USER ALL=(ALL) NOPASSWD: $PROJECT_ROOT/install.sh --update
$ACTUAL_USER ALL=(ALL) NOPASSWD: $PROJECT_ROOT/install.sh --update --branch *
EOF

    # Sudoers files must be 440 and owned by root
    chmod 440 "$SUDOERS_FILE"
    chown root:root "$SUDOERS_FILE"

    # Validate sudoers syntax. An invalid file must never be left behind, but
    # report what visudo actually said - without it the only visible symptom is
    # birdnet-pipy.service crash-looping on "a terminal is required".
    local visudo_output
    if visudo_output=$(visudo -c -f "$SUDOERS_FILE" 2>&1); then
        print_status "Sudoers configuration created: $SUDOERS_FILE"
    else
        print_error "Sudoers validation failed - removing invalid file"
        printf '%s\n' "$visudo_output" | while IFS= read -r line; do
            print_error "  visudo: $line"
        done
        rm -f "$SUDOERS_FILE"
        print_warning "Audio service will fail to start without these rules"
    fi
}

# ============================================================================
# Update Mode Functions
# ============================================================================

# Record update pipeline state (in_progress/success/failed) for the frontend:
# /api/system/version surfaces it so the restart poll can distinguish a failed
# update (old code restarted) from one still in progress.
write_update_status() {
    write_flag_file "update-status" "$1"
}

# Shared flag-file plumbing: ensure the flags dir exists (kept writable by the
# API container user, which also writes flags here), then remove-then-recreate
# — the existing file may be owned by the API container user while we run as
# root (and vice versa); only the directory needs to be writable. Best-effort:
# a flag write must never fail the update. $1 = flag name, $2 = content.
write_flag_file() {
    local flags_dir="$PROJECT_ROOT/data/flags"
    if [ ! -d "$flags_dir" ]; then
        mkdir -p "$flags_dir" 2>/dev/null || true
        chown "$ACTUAL_USER:$ACTUAL_USER" "$flags_dir" 2>/dev/null || true
    fi
    rm -f "$flags_dir/$1" 2>/dev/null || true
    echo "$2" > "$flags_dir/$1" 2>/dev/null || true
}

# Record a coarse stage for the frontend's update banner. During a native
# update the frontend nginx container is kept running (see perform_update) and
# serves data/flags/update-progress at /update-progress, so the SPA can show
# real stages ("Pulling the latest images from GHCR (2 of 3)") instead of one static
# message for the whole outage. Served UNAUTHENTICATED — callers must
# pass only fixed public-safe strings and counters, never branch names, paths,
# or command output. No-op outside update mode: fresh installs share
# pull_or_build/build_application but have nothing serving the file.
# The banner shows `message`; the boot-time overlay (useUpdateOverlay) also
# checks `timestamp` so a leftover file can't pose as a live update. `stage`
# is on-disk debugging only. $1 = stage id, $2 = human-readable message.
write_update_progress() {
    [ "$UPDATE_MODE" = true ] || return 0
    write_flag_file "update-progress" \
        "$(printf '{"stage":"%s","message":"%s","timestamp":"%s"}' \
            "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
}

# Helper function to restart containers on failure during update
restart_containers_on_failure() {
    write_update_status "failed"
    write_update_progress "failed" "Update failed, restarting the previous version"
    print_status "Restarting containers with current code..."
    cd "$PROJECT_ROOT"
    docker compose up -d || true
}

# Perform system update (called when --update flag is used)
# This handles: git sync, build, and system config updates
# Uses TARGET_BRANCH if specified, otherwise current branch or main
perform_update() {
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_status "BirdNET-PiPy System Update"
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    cd "$PROJECT_ROOT"
    local update_warnings=false

    # Apply a requested port change before any containers are (re)created —
    # including the failure path's fallback docker compose up
    if [ -n "$WEB_PORT" ]; then
        persist_web_port "$WEB_PORT"
    fi

    # Determine target branch: explicit > current > main
    local target_branch="${TARGET_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
    if [ "$target_branch" = "HEAD" ]; then
        target_branch="main"
    fi
    print_status "Target branch: $target_branch"

    write_update_status "in_progress"
    write_update_progress "stopping" "Stopping services"

    # Step 1: Stop containers so Docker artifacts are unused and can be pruned
    # safely — except the frontend: nginx (a few MB) keeps serving the
    # already-loaded SPA and /update-progress through the long pull/build
    # phase, and is recreated with the new image by the post-update service
    # restart. The service list comes from the CURRENT compose file — the same
    # one these containers were created from (git sync happens later). If the
    # selective stop can't run, fall back to the old full teardown: a dark
    # site during the update is the pre-progress-banner baseline, while a
    # backend container left running through git reset would not be safe.
    print_status "Stopping containers (keeping frontend up for update progress)..."
    local stop_services
    stop_services=$(docker compose config --services 2>/dev/null | grep -vx frontend || true)
    # An empty list (config failed) makes rm target all services — the full
    # teardown that case wants anyway.
    # shellcheck disable=SC2086  # word-splitting the service list is intended
    docker compose rm -sf $stop_services || docker compose down || true

    # Step 2: Reclaim Docker disk space before any git/pull/build work
    write_update_progress "cleanup" "Cleaning up disk space"
    prune_docker_before_update

    # Step 3: Fetch target branch with explicit refspec
    # This ensures origin/$target_branch is created even in shallow/single-branch clones
    print_status "Fetching latest code..."
    write_update_progress "fetch" "Fetching the latest code from GitHub"
    if ! git fetch origin "+refs/heads/$target_branch:refs/remotes/origin/$target_branch" 2>&1; then
        print_error "Git fetch failed - branch '$target_branch' may not exist on remote"
        restart_containers_on_failure
        exit 1
    fi

    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "origin/$target_branch")

    if [ "$LOCAL" = "$REMOTE" ]; then
        print_status "Already up to date, no code changes needed"

        # Check if version.json is stale (e.g., previous build failed mid-way)
        # If so, rebuild to fix the version mismatch
        local current_commit_short
        current_commit_short=$(git rev-parse --short HEAD)
        local version_commit
        version_commit=$(grep -o '"commit": *"[^"]*"' "$PROJECT_ROOT/data/version.json" 2>/dev/null | grep -o '"[^"]*"$' | tr -d '"' || true)
        if [ "$current_commit_short" != "$version_commit" ]; then
            print_warning "version.json is stale (shows $version_commit, expected $current_commit_short)"
            print_status "Rebuilding to fix version mismatch..."
            if pull_or_build; then
                print_status "Rebuild successful, version.json updated"
            else
                print_warning "Rebuild failed - version.json may still be stale"
            fi
        fi

        print_status "Refreshing system configurations..."
        write_update_progress "configure" "Refreshing system configuration"
        configure_pulseaudio
        create_service_file
        install_service
        setup_sudoers
        # Same-commit outcome: the frontend's update poll can't see a commit
        # change here, so the explicit success status is its completion signal
        write_update_status "success"
        write_update_progress "restarting" "Restarting services"
        print_status "Restarting containers..."
        docker compose up -d || true
        print_status "Update complete (no code changes)"
        exit 0
    fi

    COMMITS_BEHIND=$(git rev-list --count HEAD.."origin/$target_branch")
    print_status "Update available: $COMMITS_BEHIND commits behind origin/$target_branch"

    # Step 4: Check for local modifications and warn
    if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet HEAD 2>/dev/null; then
        print_warning "Local modifications detected - these will be discarded:"
        git status --short 2>/dev/null | head -10
        print_warning "Note: The install directory is not intended for local customizations"
    fi

    # Step 5: Sync to target branch (checkout + reset)
    print_status "Syncing to origin/$target_branch..."
    # No stage write here: checkout+reset takes seconds, so the banner keeps
    # the fetch stage's message until the pull/build stage replaces it.

    # Check if local branch exists
    if git show-ref --verify --quiet "refs/heads/$target_branch"; then
        # Local branch exists - checkout and reset
        if ! git checkout -f "$target_branch" 2>&1; then
            print_error "Git checkout failed!"
            restart_containers_on_failure
            exit 1
        fi
    else
        # Local branch doesn't exist - create from remote tracking branch
        if ! git checkout -b "$target_branch" "origin/$target_branch" 2>&1; then
            print_error "Git checkout failed - could not create local branch!"
            restart_containers_on_failure
            exit 1
        fi
    fi

    if ! git reset --hard "origin/$target_branch" 2>&1; then
        print_error "Git reset failed!"
        restart_containers_on_failure
        exit 1
    fi

    # Fix ownership of git-tracked files only (skip data/ which has large audio files)
    find "$PROJECT_ROOT" -maxdepth 1 -mindepth 1 -not -name data \
        -exec chown -R "$ACTUAL_USER:$ACTUAL_USER" {} +

    # Step 6: Ensure swap on low-memory systems, then pull or build
    setup_swap || print_warning "Swap setup failed (continuing without swap)"
    setup_gpu_mem || print_warning "GPU memory setup failed (continuing with default split)"
    if ! pull_or_build; then
        print_error "Failed to pull or build images!"
        restart_containers_on_failure
        exit 1
    fi

    # The update itself has landed: the repo is synced and the new images are
    # pulled/built (deployment happens at the post-update service restart).
    # Written BEFORE the config refresh below so an unguarded set -e death in
    # Step 7 cannot get stamped 'failed' by the service wrapper after the
    # update work already succeeded.
    write_update_status "success"

    # Step 7: Update system configurations (root operations)
    print_status "Updating system configurations..."
    write_update_progress "configure" "Updating system configuration"
    configure_pulseaudio
    create_service_file
    install_service
    setup_sudoers
    fix_config_permissions

    # Step 8: Success - exit for systemd restart
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_status "Update complete! Applied $COMMITS_BEHIND commits from origin/$target_branch"
    if [ "$update_warnings" = true ]; then
        print_warning "Update completed with warnings (version metadata refresh failed)"
    fi
    print_status "Exiting to restart service with updated code..."
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    # Last stage the old frontend can serve: the service restart takes it down
    # and birdnet-service.sh clears the progress file once the new stack is up.
    write_update_progress "restarting" "Restarting services with the new version"

    exit 0
}

# ============================================================================
# Validation & Error Handling
# ============================================================================

# Validate installation
validate_installation() {
    print_status "Validating installation..."

    local checks_passed=true

    # Check Docker
    if ! docker --version &> /dev/null; then
        print_error "Docker validation failed"
        checks_passed=false
    fi

    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        print_error "Docker Compose validation failed"
        checks_passed=false
    fi

    # Check audio system (PulseAudio or PipeWire)
    if ! command -v pulseaudio &> /dev/null && ! command -v pipewire &> /dev/null; then
        print_error "Audio system validation failed (no PulseAudio or PipeWire)"
        checks_passed=false
    fi

    # Check systemd service
    if [ ! -f "$SERVICE_FILE" ]; then
        print_error "Systemd service not found"
        checks_passed=false
    fi

    # Check runtime script
    if [ ! -x "$PROJECT_ROOT/deployment/birdnet-service.sh" ]; then
        print_error "Runtime script not executable"
        checks_passed=false
    fi

    # Check Docker images (skip if --skip-build was used)
    if [ "$SKIP_BUILD" != true ]; then
        local image_count
        image_count=$(docker images 2>/dev/null | grep -c "birdnet-pipy" || true)
        if [ "$image_count" -eq 0 ]; then
            print_error "Docker images not built"
            checks_passed=false
        fi
    fi

    if [ "$checks_passed" = true ]; then
        print_status "All validation checks passed!"
    else
        print_error "Some validation checks failed"
        return 1
    fi
}

# Cleanup on error
cleanup_on_error() {
    local exit_code=$?
    echo ""
    print_error "Installation failed with exit code $exit_code"
    print_info "Detailed log saved to: $LOG_FILE (persistent across reboots)"
    echo ""
    print_info "To view the log:"
    echo "  tail -100 $LOG_FILE    # Last 100 lines"
    echo "  less $LOG_FILE         # Full log"
    echo ""
    print_info "TIP: It's safe to re-run the installation command - it will"
    print_info "     pick up where it left off and usually fixes the issue."
    echo ""
    print_info "For help, visit: https://github.com/Suncuss/BirdNET-PiPy/issues"
    print_info "Include the log file when reporting issues"
}

trap cleanup_on_error ERR

# ============================================================================
# Completion Message
# ============================================================================

show_completion_message() {
    echo ""
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_status "BirdNET-PiPy Installation Complete!"
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    print_info "Access the Dashboard after reboot:"
    local hostname
    hostname=$(hostname)
    local ip_addr
    ip_addr=$(hostname -I | awk '{print $1}')
    # Non-default web port (this run's --port or a persisted earlier choice)
    # must appear in the URLs
    local port_suffix=""
    local web_port
    web_port=$(effective_web_port)
    [ "$web_port" != "80" ] && port_suffix=":${web_port}"
    echo "  http://${hostname}.local${port_suffix}"
    [ -n "$ip_addr" ] && echo "  http://${ip_addr}${port_suffix}"
    echo ""
}

# Reboot system after installation
prompt_reboot() {
    if [ "$NO_REBOOT" = true ]; then
        print_status "Reboot skipped (--no-reboot flag)"
        return 0
    fi

    print_status "Rebooting to apply changes..."
    sleep 1
    reboot
}

# ============================================================================
# Main Execution Flow
# ============================================================================

main() {
    print_status "BirdNET-PiPy Installation Script"
    echo ""

    # Parse command-line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --update)
                UPDATE_MODE=true
                shift
                ;;
            --branch)
                TARGET_BRANCH="$2"
                shift 2
                ;;
            --port)
                if ! validate_web_port "${2:-}"; then
                    exit 1
                fi
                WEB_PORT="$2"
                shift 2
                ;;
            --help)
                show_usage
                exit 0
                ;;
            --no-reboot)
                NO_REBOOT=true
                shift
                ;;
            --skip-build)
                SKIP_BUILD=true
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done

    # Platform and permission checks
    detect_platform
    check_root

    # Compute actual user details once (used by all functions below)
    init_user_vars

    # Handle update mode early (before any installation steps)
    if [ "$UPDATE_MODE" = true ]; then
        # Update mode requires running from existing installation
        if [ "$IS_LOCAL_INSTALL" = false ]; then
            print_error "--update requires running from existing installation"
            print_info "Run from: /path/to/BirdNET-PiPy/install.sh --update"
            exit 1
        fi

        # Perform update and exit (never returns)
        perform_update
    fi

    # Install all prerequisites in one batch (git, docker prereqs, pulseaudio)
    # This minimizes apt-get update calls for faster installation
    install_prerequisites

    # Stage 1: Clone if needed (remote execution)
    if [ "$IS_LOCAL_INSTALL" = false ]; then
        print_status "Running in remote mode (clone required)"
        clone_repository
        # Save arguments to pass through (array preserves quoting)
        ARGS=()
        [ -n "$TARGET_BRANCH" ] && ARGS+=(--branch "$TARGET_BRANCH")
        [ -n "$WEB_PORT" ] && ARGS+=(--port "$WEB_PORT")
        [ "$NO_REBOOT" = true ] && ARGS+=(--no-reboot)
        [ "$SKIP_BUILD" = true ] && ARGS+=(--skip-build)
        reexec_from_clone "${ARGS[@]}"
        # Script exits here (exec replaces process)
    fi

    # Stage 2: Local installation (from cloned repo)
    print_status "Running in local mode (installing from: $PROJECT_ROOT)"
    echo ""

    # Record the requested web port before anything builds or starts containers
    if [ -n "$WEB_PORT" ]; then
        persist_web_port "$WEB_PORT"
    fi

    # Docker setup
    if command -v docker &> /dev/null && docker compose version &> /dev/null 2>&1; then
        print_status "Docker and Docker Compose already installed"
        docker --version
    else
        install_docker
    fi
    setup_docker_user

    # PulseAudio configuration (packages already installed by install_prerequisites)
    configure_pulseaudio

    # Application setup
    fix_data_permissions
    setup_swap || print_warning "Swap setup failed (continuing without swap)"
    setup_gpu_mem || print_warning "GPU memory setup failed (continuing with default split)"
    pull_or_build
    chmod +x "$PROJECT_ROOT/deployment/birdnet-service.sh"

    # Service setup
    create_service_file
    install_service
    setup_sudoers

    # Validate installation
    validate_installation

    # Show completion message (skip if --no-reboot since this is likely a test)
    if [ "$NO_REBOOT" != true ]; then
        show_completion_message
    fi

    # Prompt for reboot (user can Ctrl+C to cancel)
    prompt_reboot
}

# Run main function
main "$@"
