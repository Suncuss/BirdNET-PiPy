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

# Logging setup
LOG_FILE="/tmp/birdnet-pipy-install-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Command-line options
CUSTOM_INSTALL_DIR=""

# ============================================================================
# Logging Functions
# ============================================================================

# Log to file with timestamp
log_to_file() {
    local level=$1
    shift
    local message="$@"
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$level] $message" >> "$LOG_FILE"
}

# Print to console and log
print_status() {
    echo -e "${GREEN}[INSTALL]${NC} $1"
    log_to_file "STATUS" "$1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
    log_to_file "WARNING" "$1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    log_to_file "ERROR" "$1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
    log_to_file "INFO" "$1"
}

# Debug logging (only shown in log file)
log_debug() {
    log_to_file "DEBUG" "$1"
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
        print_info "Correct usage:"
        echo "  sudo ./install.sh"
        echo "  sudo ./install.sh --install-dir /path/to/install"
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

# Get actual user's UID/GID (not root's)
get_actual_uid_gid() {
    ACTUAL_USER=$(get_actual_user)
    ACTUAL_UID=$(id -u $ACTUAL_USER)
    ACTUAL_GID=$(id -g $ACTUAL_USER)
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
        OS_VERSION_ID=$VERSION_ID
        OS_NAME=$NAME
        print_status "Detected platform: $OS_NAME"
    else
        print_warning "Cannot detect OS distribution"
        OS_ID="linux"
        OS_NAME="Unknown Linux"
    fi

    # Check if Debian-based (for apt-get)
    if ! command -v apt-get &> /dev/null; then
        print_error "This script requires apt-get (Debian/Ubuntu/Raspberry Pi OS)"
        exit 1
    fi
}

# Detect host timezone
detect_timezone() {
    if [ -f /etc/timezone ]; then
        TZ=$(cat /etc/timezone)
    elif [ -L /etc/localtime ]; then
        # Extract timezone from symlink (e.g., /usr/share/zoneinfo/America/New_York)
        TZ=$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')
    elif [ -n "$TZ" ]; then
        : # Use existing TZ
    else
        TZ="UTC"
    fi
    export TZ
    print_status "Detected timezone: $TZ"
}

# Show usage
show_usage() {
    echo "BirdNET-PiPy Unified Installation Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --install-dir DIR    Installation directory (default: /home/\$USER/BirdNET-PiPy)"
    echo "  --help               Show this help message"
    echo ""
    echo "Examples:"
    echo "  # Quick install with defaults"
    echo "  curl -fsSL https://raw.githubusercontent.com/Suncuss/BirdNET-PiPy/main/install.sh | sudo bash"
    echo ""
    echo "  # Custom installation directory"
    echo "  sudo ./install.sh --install-dir /home/pi/BirdNET"
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
    if ! command -v pulseaudio &> /dev/null; then
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

# Check if git is available (should be installed by install_prerequisites)
check_git() {
    if ! command -v git &> /dev/null; then
        print_error "Git not installed. This should not happen."
        exit 1
    fi
}

# Clone repository
clone_repository() {
    print_status "Cloning BirdNET-PiPy repository..."

    check_git

    # Determine installation directory
    if [ -n "$CUSTOM_INSTALL_DIR" ]; then
        INSTALL_DIR="$CUSTOM_INSTALL_DIR"
    else
        ACTUAL_USER=$(get_actual_user)
        INSTALL_DIR="/home/$ACTUAL_USER/BirdNET-PiPy"
    fi

    print_info "Installation directory: $INSTALL_DIR"

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
                git checkout $REPO_BRANCH
                git pull origin $REPO_BRANCH || {
                    print_error "Failed to update repository"
                    exit 1
                }
                # Fix ownership after git pull
                get_actual_uid_gid
                chown -R $ACTUAL_USER:$ACTUAL_USER "$INSTALL_DIR"
            else
                print_error "Directory exists but contains a different git repository"
                print_error "Expected: $REPO_URL"
                print_error "Found: $CURRENT_REPO"
                print_info "Use --install-dir to specify a different installation location"
                exit 1
            fi
        else
            print_error "Directory exists but is not a git repository"
            print_info "Please remove or rename: $INSTALL_DIR"
            exit 1
        fi
    else
        # Clone fresh (shallow clone for speed - full history not needed)
        git clone --depth 1 -b $REPO_BRANCH "$REPO_URL" "$INSTALL_DIR" || {
            print_error "Failed to clone repository"
            exit 1
        }
        print_status "Repository cloned to $INSTALL_DIR (shallow clone)"

        # Fix ownership after clone
        get_actual_uid_gid
        chown -R $ACTUAL_USER:$ACTUAL_USER "$INSTALL_DIR"
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

# Check if Docker is installed
check_docker() {
    if command -v docker &> /dev/null; then
        print_status "Docker is already installed"
        docker --version
        return 0
    else
        return 1
    fi
}

# Check if Docker Compose plugin is available
check_docker_compose() {
    if docker compose version &> /dev/null 2>&1; then
        print_status "Docker Compose plugin is available"
        docker compose version
        return 0
    else
        return 1
    fi
}

# Install Docker using official method
install_docker() {
    print_status "Installing Docker..."
    print_info "This may take a few minutes..."

    # Prerequisites (ca-certificates, curl, gnupg, lsb-release) are already
    # installed by install_prerequisites() - no apt-get update needed here

    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/$OS_ID/gpg | \
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
    ACTUAL_USER=$(get_actual_user)

    # Add user to docker group
    if ! groups $ACTUAL_USER | grep -q docker; then
        usermod -aG docker $ACTUAL_USER
        print_status "Added $ACTUAL_USER to docker group"
        print_warning "IMPORTANT: Log out and back in for docker group to take effect"
        print_warning "Or run: newgrp docker"
    else
        print_status "User $ACTUAL_USER already in docker group"
    fi
}

# Verify Docker installation
verify_docker() {
    print_status "Verifying Docker installation..."

    if ! docker --version &> /dev/null; then
        print_error "Docker verification failed"
        exit 1
    fi

    if ! docker compose version &> /dev/null; then
        print_error "Docker Compose plugin verification failed"
        exit 1
    fi

    print_status "Docker verification passed"
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

    # Copy PulseAudio configuration files
    print_status "Configuring PulseAudio for system-wide mode..."

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
    ACTUAL_USER=$(get_actual_user)
    usermod -a -G pulse-access,audio $ACTUAL_USER

    print_status "PulseAudio setup complete"
    print_info "PulseAudio will be started by birdnet-service.sh"
}

# Check if system has low memory and set up swap if needed
setup_build_swap() {
    local ram_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    local ram_mb=$((ram_kb / 1024))
    local swap_mb=$(free -m | awk '/Swap:/ {print $2}')
    local needed_swap=2048
    local swap_file="/swapfile"

    print_status "System RAM: ${ram_mb}MB, Swap: ${swap_mb}MB"

    # Only set up swap for low memory systems (<1GB)
    if [ "$ram_kb" -ge 1048576 ]; then
        return 0
    fi

    print_warning "Low memory system detected (<1GB RAM)"

    if [ "$swap_mb" -ge "$needed_swap" ]; then
        print_status "Sufficient swap already available"
        return 0
    fi

    print_status "Creating ${needed_swap}MB swap file for Docker build..."

    # Remove existing swap file if present
    if [ -f "$swap_file" ]; then
        swapoff "$swap_file" 2>/dev/null || true
        rm -f "$swap_file"
    fi

    # Create swap file
    dd if=/dev/zero of="$swap_file" bs=1M count="$needed_swap" status=progress
    chmod 600 "$swap_file"
    mkswap "$swap_file"
    swapon "$swap_file"

    print_status "Swap file created and enabled"
}

# Build Docker images
build_application() {
    print_status "Building BirdNET-PiPy application..."

    # Set up swap for low-memory systems (we have root here)
    setup_build_swap

    get_actual_uid_gid
    print_status "Building as user $ACTUAL_USER (UID:$ACTUAL_UID, GID:$ACTUAL_GID)..."

    cd "$PROJECT_ROOT"

    # Make build.sh executable if not already
    chmod +x build.sh

    # Run build script as actual user with correct UID/GID
    sudo -u $ACTUAL_USER UID=$ACTUAL_UID GID=$ACTUAL_GID ./build.sh

    if [ $? -eq 0 ]; then
        print_status "Application built successfully"
    else
        print_error "Application build failed!"
        exit 1
    fi
}

# Fix existing data folder permissions
fix_data_permissions() {
    print_status "Setting up data directory permissions..."

    get_actual_uid_gid

    # Create data directory if it doesn't exist
    if [ ! -d "$PROJECT_ROOT/data" ]; then
        mkdir -p "$PROJECT_ROOT/data"
    fi

    # Create flags directory for restart/update triggers
    if [ ! -d "$PROJECT_ROOT/data/flags" ]; then
        mkdir -p "$PROJECT_ROOT/data/flags"
    fi

    # Fix ownership
    chown -R $ACTUAL_USER:$ACTUAL_USER "$PROJECT_ROOT/data"
    print_status "Data permissions fixed for user $ACTUAL_USER"
}

# Make runtime script executable
setup_runtime_script() {
    print_status "Setting up runtime script..."

    RUNTIME_SCRIPT="$PROJECT_ROOT/deployment/birdnet-service.sh"

    if [ ! -f "$RUNTIME_SCRIPT" ]; then
        print_error "Runtime script not found: $RUNTIME_SCRIPT"
        exit 1
    fi

    chmod +x "$RUNTIME_SCRIPT"
    print_status "Runtime script is executable"
}

# Create systemd service file
create_service_file() {
    print_status "Creating systemd service file..."

    ACTUAL_USER=$(get_actual_user)
    RUNTIME_SCRIPT="$PROJECT_ROOT/deployment/birdnet-service.sh"

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=BirdNET-PiPy AI Bird Detection Service
Documentation=https://github.com/Suncuss/BirdNET-PiPy
After=docker.service network.target
Requires=docker.service

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$PROJECT_ROOT
ExecStart=$RUNTIME_SCRIPT
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

# Environment variables
Environment=TZ=$TZ

# Graceful shutdown
TimeoutStopSec=30
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

    # Check PulseAudio
    if ! command -v pulseaudio &> /dev/null; then
        print_error "PulseAudio validation failed"
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

    # Check Docker images
    local image_count=$(docker images | grep -c "birdnet-pipy" || true)
    log_debug "Docker images check: found $image_count BirdNET-PiPy images"

    if [ "$image_count" -eq 0 ]; then
        print_error "Docker images not built"
        # Log all available images for debugging
        log_debug "Available Docker images:"
        docker images | while read line; do
            log_debug "  $line"
        done
        checks_passed=false
    else
        log_debug "Docker images found: $image_count"
        docker images | grep "birdnet-pipy" | while read line; do
            log_debug "  $line"
        done
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

    if [ $exit_code -ne 0 ]; then
        echo ""
        print_error "Installation failed with exit code $exit_code"
        print_info "Detailed log saved to: $LOG_FILE"
        echo ""
        print_info "To view the log:"
        echo "  tail -100 $LOG_FILE    # Last 100 lines"
        echo "  less $LOG_FILE         # Full log"
        echo ""
        print_info "For help, visit: https://github.com/Suncuss/BirdNET-PiPy/issues"
        print_info "Include the log file when reporting issues"
    fi
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
    print_info "Installation directory: $PROJECT_ROOT"
    print_info "Images are built and the systemd service is installed."
    echo ""
    print_info "Installation log saved to: $LOG_FILE"
    echo ""
    print_info "Start the service with:"
    echo "  sudo systemctl start $SERVICE_NAME"
    echo ""
    print_info "Service Management Commands:"
    echo "  sudo systemctl status $SERVICE_NAME    # Check status"
    echo "  sudo systemctl stop $SERVICE_NAME      # Stop service"
    echo "  sudo systemctl restart $SERVICE_NAME   # Restart service"
    echo "  sudo journalctl -u $SERVICE_NAME -f    # View logs"
    echo ""
    print_info "Application Access:"
    echo "  - Frontend: http://localhost:8080"
    echo "  - API: http://localhost:5002"
    echo "  - BirdNet Service: http://localhost:5001"
    echo "  - Live Audio Stream: http://localhost:8888/stream.mp3"
    echo ""
    print_info "Audio Services:"
    echo "  pulseaudio --check && echo Running       # Check PulseAudio"
    echo "  pactl list sources short                 # List audio sources"
    echo ""
    print_info "To trigger a container restart:"
    echo "  touch $PROJECT_ROOT/data/flags/restart-backend"
    echo ""
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
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
            --install-dir)
                CUSTOM_INSTALL_DIR="$2"
                shift 2
                ;;
            --help)
                show_usage
                exit 0
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

    # Install all prerequisites in one batch (git, docker prereqs, pulseaudio)
    # This minimizes apt-get update calls for faster installation
    install_prerequisites

    # Stage 1: Clone if needed (remote execution)
    if [ "$IS_LOCAL_INSTALL" = false ]; then
        print_status "Running in remote mode (clone required)"
        clone_repository
        # Save arguments to pass through
        ARGS=""
        [ -n "$CUSTOM_INSTALL_DIR" ] && ARGS="$ARGS --install-dir $CUSTOM_INSTALL_DIR"
        reexec_from_clone $ARGS
        # Script exits here (exec replaces process)
    fi

    # Stage 2: Local installation (from cloned repo)
    print_status "Running in local mode (installing from: $PROJECT_ROOT)"
    echo ""

    # Detect timezone for Docker containers
    detect_timezone

    # Docker setup
    if ! check_docker || ! check_docker_compose; then
        install_docker
        setup_docker_user
        verify_docker
    else
        print_status "Docker and Docker Compose are already installed, skipping..."
    fi

    # PulseAudio configuration (packages already installed by install_prerequisites)
    configure_pulseaudio

    # Application setup
    fix_data_permissions
    build_application
    setup_runtime_script

    # Service setup
    create_service_file
    install_service

    # Validate installation
    validate_installation

    # Show completion message
    show_completion_message
}

# Run main function
main "$@"
