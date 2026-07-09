#!/bin/bash
# BirdNET-PiPy Uninstall Script
# Removes systemd service and Docker images while preserving user data

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="birdnet-pipy"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Logging functions
print_status() {
    echo -e "${GREEN}[UNINSTALL]${NC} $1"
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

# Check if running as root and using sudo
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run as root (use sudo)"
        exit 1
    fi

    # Check if running as direct root (not via sudo)
    if [ "$EUID" -eq 0 ] && [ -z "$SUDO_USER" ]; then
        print_error "Please run this script with sudo, not as direct root"
        print_info "Correct usage:"
        echo "  sudo ./uninstall.sh"
        echo "  sudo ./uninstall.sh --full"
        exit 1
    fi
}

# Show usage
show_usage() {
    echo "BirdNET-PiPy Uninstall Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --keep-images        Keep Docker images (don't remove)"
    echo "  --remove-data        Remove user data directory (WARNING: deletes all recordings and database)"
    echo "  --remove-project     Remove entire project directory"
    echo "  --full               Complete removal (service + images + data + project)"
    echo "  --help               Show this help message"
    echo ""
    echo "Default behavior (no options):"
    echo "  - Removes systemd service"
    echo "  - Removes Docker images"
    echo "  - KEEPS user data (data/ directory)"
    echo "  - KEEPS project files"
    echo ""
    echo "Examples:"
    echo "  # Remove service and images, keep data"
    echo "  sudo ./uninstall.sh"
    echo ""
    echo "  # Remove service only, keep images and data"
    echo "  sudo ./uninstall.sh --keep-images"
    echo ""
    echo "  # Complete removal (WARNING: deletes everything)"
    echo "  sudo ./uninstall.sh --full"
}

# Parse command-line options
KEEP_IMAGES=false
REMOVE_DATA=false
REMOVE_PROJECT=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-images)
            KEEP_IMAGES=true
            shift
            ;;
        --remove-data)
            REMOVE_DATA=true
            shift
            ;;
        --remove-project)
            REMOVE_PROJECT=true
            shift
            ;;
        --full)
            REMOVE_DATA=true
            REMOVE_PROJECT=true
            shift
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

# Confirmation
confirm_uninstall() {
    echo ""
    print_warning "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_warning "BirdNET-PiPy Uninstall"
    print_warning "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    print_info "This will remove:"
    echo "  ✓ Systemd service (/etc/systemd/system/${SERVICE_NAME}.service)"
    echo "  ✓ Sudoers configuration (/etc/sudoers.d/birdnet-pipy)"

    if [ "$KEEP_IMAGES" = false ]; then
        echo "  ✓ Docker images (birdnet-pipy-*)"
    else
        echo "  ✗ Docker images (keeping)"
    fi

    echo "  ✓ Swapfile (/swapfile-birdnet-pipy) if exists"
    echo "  ✓ GPU memory setting (gpu_mem=16 added by install.sh) if exists"
    echo "  ✓ Install logs"

    if [ "$REMOVE_DATA" = true ]; then
        echo "  ✓ User data (data/ directory - recordings and database)"
    else
        echo "  ✗ User data (keeping)"
    fi

    if [ "$REMOVE_PROJECT" = true ]; then
        echo "  ✓ Project directory ($SCRIPT_DIR)"
    else
        echo "  ✗ Project directory (keeping)"
    fi

    echo ""

    if [ "$REMOVE_DATA" = true ]; then
        print_error "WARNING: This will permanently delete all bird recordings and database!"
    fi

    read -p "Continue with uninstall? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Uninstall cancelled"
        exit 0
    fi
}

# Stop and remove systemd service
remove_service() {
    print_status "Removing systemd service..."

    # Check if service exists
    if [ ! -f "$SERVICE_FILE" ]; then
        print_warning "Service file not found, skipping"
        return 0
    fi

    # Stop service if running
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        print_status "Stopping service..."
        systemctl stop "$SERVICE_NAME"
    fi

    # Disable service if enabled
    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        print_status "Disabling service..."
        systemctl disable "$SERVICE_NAME"
    fi

    # Remove service file
    rm -f "$SERVICE_FILE"

    # Reload systemd
    systemctl daemon-reload

    print_status "Systemd service removed"
}

# Remove sudoers configuration
remove_sudoers() {
    local sudoers_file="/etc/sudoers.d/birdnet-pipy"

    if [ -f "$sudoers_file" ]; then
        print_status "Removing sudoers configuration..."
        rm -f "$sudoers_file"
        print_status "Sudoers configuration removed"
    else
        print_info "No sudoers configuration found"
    fi
}

# Stop and remove Docker containers
remove_containers() {
    print_status "Stopping and removing Docker containers..."

    cd "$SCRIPT_DIR"

    if command -v docker &> /dev/null && [ -f "docker-compose.yml" ]; then
        # Check if any containers exist
        if docker compose ps -q 2>/dev/null | grep -q .; then
            docker compose down
            print_status "Docker containers removed"
        else
            print_info "No Docker containers found"
        fi
    else
        print_warning "Docker or docker-compose.yml not found, skipping"
    fi
}

# Remove Docker images
remove_images() {
    if [ "$KEEP_IMAGES" = true ]; then
        print_info "Keeping Docker images (--keep-images flag)"
        return 0
    fi

    print_status "Removing Docker images..."

    # Get list of BirdNET images
    IMAGES=$(docker images | grep "birdnet-pipy" | awk '{print $3}' || true)

    if [ -z "$IMAGES" ]; then
        print_info "No BirdNET-PiPy images found"
        return 0
    fi

    # Count images
    IMAGE_COUNT=$(echo "$IMAGES" | wc -l)
    print_status "Found $IMAGE_COUNT BirdNET-PiPy images"

    # Remove images
    echo "$IMAGES" | xargs -r docker rmi 2>/dev/null || {
        print_warning "Some images could not be removed (may be in use)"
        return 0
    }

    print_status "Docker images removed"
}

# Remove swapfile created by build.sh
remove_swapfile() {
    local swap_file="/swapfile-birdnet-pipy"

    if [ ! -f "$swap_file" ]; then
        print_info "No BirdNET swapfile found"
        return 0
    fi

    print_status "Removing swapfile..."

    # Disable swap if active
    if swapon --show 2>/dev/null | grep -q "$swap_file"; then
        swapoff "$swap_file" 2>/dev/null || true
    fi

    rm -f "$swap_file"
    print_status "Swapfile removed: $swap_file"
}

# Marker comment written by install.sh's setup_gpu_mem. Keep in sync with install.sh.
GPU_MEM_MARKER="# BirdNET-PiPy: headless low-RAM device, reclaim GPU memory for the OS"

# Remove our marker comment — and the gpu_mem=16 line we wrote after it — from
# one boot config file. Only the exact pair we wrote is removed: a user-edited
# value after the marker (e.g. raspi-config rewriting it to gpu_mem=128) is
# preserved. Comparisons tolerate trailing CR/whitespace because the FAT boot
# partition is routinely edited from Windows. A bare [all] header left dangling
# at the end of the file by our removal is cleaned up too (an empty trailing
# section has no effect on the firmware).
remove_gpu_mem_from_config() {
    local cfg="$1"

    if ! grep -Fq "$GPU_MEM_MARKER" "$cfg"; then
        return 1
    fi

    local tmp
    tmp=$(mktemp) || return 1
    awk -v marker="$GPU_MEM_MARKER" '
        function trim(s) { sub(/[[:space:]\r]+$/, "", s); return s }
        { raw[NR] = $0 }
        END {
            n = 0
            for (i = 1; i <= NR; i++) {
                if (trim(raw[i]) == marker) {
                    if (i < NR && trim(raw[i + 1]) == "gpu_mem=16") i++
                    continue
                }
                out[++n] = raw[i]
            }
            last = n
            while (last > 0 && trim(out[last]) == "") last--
            if (last > 0 && trim(out[last]) == "[all]") {
                last--
                while (last > 0 && trim(out[last]) == "") last--
                n = last
            }
            for (i = 1; i <= n; i++) print out[i]
        }
    ' "$cfg" > "$tmp" || { rm -f "$tmp"; return 1; }

    # cat (not mv) so permissions and any symlinked boot path stay intact
    cat "$tmp" > "$cfg"
    rm -f "$tmp"

    # Only report success if the marker is actually gone
    if grep -Fq "$GPU_MEM_MARKER" "$cfg"; then
        print_warning "Could not remove the BirdNET gpu_mem entry from $cfg — please remove it manually"
        return 1
    fi
    return 0
}

# Remove the gpu_mem=16 setting added by install.sh (identified by marker).
# The default GPU memory split returns at the next reboot.
remove_gpu_mem_setting() {
    local cfg removed=false
    for cfg in /boot/firmware/config.txt /boot/config.txt; do
        [ -f "$cfg" ] || continue
        if remove_gpu_mem_from_config "$cfg"; then
            print_status "GPU memory setting removed from $cfg (default split returns at next reboot)"
            removed=true
        fi
    done

    if [ "$removed" = false ]; then
        print_info "No BirdNET GPU memory setting found"
    fi
}

# Remove installation log
remove_install_log() {
    local log_file="/var/log/birdnet-pipy-install.log"

    if [ -f "$log_file" ]; then
        rm -f "$log_file"
        print_status "Install log removed: $log_file"
    fi

    # Also remove the copy in data directory if it exists
    if [ -f "$SCRIPT_DIR/data/install.log" ]; then
        rm -f "$SCRIPT_DIR/data/install.log"
        print_status "Install log copy removed: $SCRIPT_DIR/data/install.log"
    fi
}

# Remove user data
remove_data() {
    if [ "$REMOVE_DATA" = false ]; then
        print_info "Keeping user data (data/ directory)"
        return 0
    fi

    print_warning "Removing user data directory..."

    if [ -d "$SCRIPT_DIR/data" ]; then
        # Final confirmation
        print_error "This will permanently delete all recordings and database!"
        read -p "Are you absolutely sure? Type 'DELETE' to confirm: " -r
        if [ "$REPLY" != "DELETE" ]; then
            print_info "Data removal cancelled, keeping data directory"
            return 0
        fi

        rm -rf "$SCRIPT_DIR/data"
        print_status "User data removed"
    else
        print_info "No data directory found"
    fi
}

# Remove project directory
remove_project() {
    if [ "$REMOVE_PROJECT" = false ]; then
        print_info "Keeping project directory"
        return 0
    fi

    print_warning "Removing project directory..."

    # Safety check - don't remove if we're in a critical directory
    if [[ "$SCRIPT_DIR" == "/" ]] || [[ "$SCRIPT_DIR" == "/home" ]] || [[ "$SCRIPT_DIR" == "/root" ]]; then
        print_error "Safety check failed: refusing to remove $SCRIPT_DIR"
        exit 1
    fi

    # Final confirmation
    print_error "This will permanently delete the entire project at: $SCRIPT_DIR"
    read -p "Are you absolutely sure? Type 'DELETE' to confirm: " -r
    if [ "$REPLY" != "DELETE" ]; then
        print_info "Project removal cancelled"
        return 0
    fi

    # Move up one directory before removing
    cd /
    rm -rf "$SCRIPT_DIR"
    print_status "Project directory removed"
}

# Show completion message
show_completion() {
    echo ""
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    print_status "BirdNET-PiPy Uninstall Complete"
    print_status "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    if [ "$REMOVE_PROJECT" = false ]; then
        print_info "Project directory preserved at: $SCRIPT_DIR"

        if [ "$REMOVE_DATA" = false ]; then
            print_info "User data preserved at: $SCRIPT_DIR/data"
        fi

        echo ""
        print_info "To reinstall later:"
        echo "  cd $SCRIPT_DIR"
        echo "  sudo ./install.sh"
    fi

    echo ""
    print_status "Thank you for using BirdNET-PiPy!"
}

# Main execution
main() {
    print_status "BirdNET-PiPy Uninstall Script"
    echo ""

    check_root
    confirm_uninstall

    echo ""
    remove_service
    remove_sudoers
    remove_containers
    remove_images
    remove_swapfile
    remove_gpu_mem_setting
    remove_install_log
    remove_data
    remove_project

    show_completion
}

# Run main
main
