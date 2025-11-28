#!/bin/bash
# BirdNET-PiPy Installation Script
# Sets up the complete BirdNET-PiPy system including Docker build and systemd service

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="birdnet-pipy"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
RUNTIME_SCRIPT="$SCRIPT_DIR/birdnet-service.sh"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
print_status() {
    echo -e "${GREEN}[INSTALL]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[INSTALL]${NC} $1"
}

print_error() {
    echo -e "${RED}[INSTALL]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INSTALL]${NC} $1"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run as root (use sudo)"
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

# Check prerequisites
check_prerequisites() {
    print_status "Checking prerequisites..."

    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed!"
        print_info "Please install Docker first: https://docs.docker.com/engine/install/"
        exit 1
    fi

    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        print_error "Docker Compose is not installed!"
        print_info "Please install Docker Compose plugin"
        exit 1
    fi

    print_status "Prerequisites check passed"
}

# Build Docker images
build_application() {
    print_status "Building BirdNET-PiPy application..."

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

# Create systemd service file
create_service_file() {
    print_status "Creating systemd service file..."

    ACTUAL_USER=$(get_actual_user)

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=BirdNET-PiPy AI Bird Detection Service
Documentation=https://github.com/yourusername/BirdNET-PiPy
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
# Environment=ENABLE_AUDIO_STREAM=true

# Graceful shutdown
TimeoutStopSec=30
KillMode=mixed

[Install]
WantedBy=multi-user.target
EOF

    print_status "Service file created: $SERVICE_FILE"
}

# Fix existing data folder permissions
fix_data_permissions() {
    print_status "Fixing data directory permissions..."

    get_actual_uid_gid

    if [ -d "$PROJECT_ROOT/data" ]; then
        chown -R $ACTUAL_USER:$ACTUAL_USER "$PROJECT_ROOT/data"
        print_status "Data permissions fixed for user $ACTUAL_USER"
    else
        print_info "No data directory to fix (will be created on first run)"
    fi
}

# Make runtime script executable
setup_runtime_script() {
    print_status "Setting up runtime script..."

    if [ ! -f "$RUNTIME_SCRIPT" ]; then
        print_error "Runtime script not found: $RUNTIME_SCRIPT"
        exit 1
    fi

    chmod +x "$RUNTIME_SCRIPT"
    print_status "Runtime script is executable"
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

# Install PulseAudio for audio multiplexing
install_pulseaudio() {
    print_info ""
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_info "PulseAudio Setup (Required for audio recording)"
    print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    print_status "Installing PulseAudio..."

    apt-get update
    apt-get install -y pulseaudio pulseaudio-utils alsa-utils

    # Copy PulseAudio configuration files
    print_status "Configuring PulseAudio for system-wide mode..."

    # Backup existing configs if present
    if [ -f /etc/pulse/system.pa ]; then
        cp /etc/pulse/system.pa /etc/pulse/system.pa.backup
    fi
    if [ -f /etc/pulse/daemon.conf ]; then
        cp /etc/pulse/daemon.conf /etc/pulse/daemon.conf.backup
    fi

    # Copy our configuration
    cp "$SCRIPT_DIR/audio/pulseaudio/system.pa" /etc/pulse/system.pa
    cp "$SCRIPT_DIR/audio/pulseaudio/daemon.conf" /etc/pulse/daemon.conf

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

# Display completion message
show_completion_message() {
    echo ""
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_status "✨ BirdNET-PiPy Installation Complete (not started)!"
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    print_info "Images are built and the systemd service is installed but not started."
    print_info "Start it manually when you're ready:"
    echo "  sudo systemctl start $SERVICE_NAME"
    print_info "or run the runtime script directly:"
    echo "  $RUNTIME_SCRIPT"
    echo ""
    print_info "Service will auto-start on boot (enabled). Disable with:"
    echo "  sudo systemctl disable $SERVICE_NAME"
    echo ""
    print_info "Service Management Commands:"
    echo "  sudo systemctl status $SERVICE_NAME    # Check status"
    echo "  sudo systemctl stop $SERVICE_NAME      # Stop service"
    echo "  sudo systemctl start $SERVICE_NAME     # Start service"
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

# Main installation process
main() {
    print_status "Starting BirdNET-PiPy Installation..."
    echo ""

    # Run installation steps
    check_root
    detect_timezone
    check_prerequisites
    install_pulseaudio
    build_application
    fix_data_permissions
    setup_runtime_script
    create_service_file
    install_service

    # Intentionally do not start containers or the systemd service here
    show_completion_message
}

# Run main installation
main
