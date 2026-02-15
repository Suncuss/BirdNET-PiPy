#!/bin/bash

# BirdNET-PiPy Build Script
# Builds and deploys the application using Docker
# NOTE: Frontend is now built inside Docker - no Node.js required on host!
# For frontend development with hot-reload: cd frontend && npm run dev

set -e  # Exit on any error

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Logging setup - append to same log as install.sh for unified history
LOG_FILE="/var/log/birdnet-pipy-install.log"
if touch "$LOG_FILE" 2>/dev/null; then
    echo "" >> "$LOG_FILE"
    echo "========== Build started: $(date) ==========" >> "$LOG_FILE"
    exec > >(tee -a "$LOG_FILE") 2>&1
fi

# Low memory threshold (1GB in KB) - systems with <1GB RAM need special handling
LOW_MEMORY_THRESHOLD_KB=1048576
# Swap size for low-memory builds (2GB)
SWAP_SIZE_MB=2048
SWAP_FILE="/swapfile-birdnet-pipy"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[BUILD]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Detect total RAM in KB
get_total_ram_kb() {
    grep MemTotal /proc/meminfo | awk '{print $2}'
}

# Check if system is low memory (< 1GB)
is_low_memory() {
    local ram_kb=$(get_total_ram_kb)
    [ "$ram_kb" -lt "$LOW_MEMORY_THRESHOLD_KB" ]
}

# Get current swap size in MB
get_swap_size_mb() {
    free -m | awk '/Swap:/ {print $2}'
}

# Create or extend swap for low-memory builds
setup_build_swap() {
    local current_swap=$(get_swap_size_mb)
    local needed_swap=$SWAP_SIZE_MB

    if [ "$current_swap" -ge "$needed_swap" ]; then
        print_status "Sufficient swap already available (${current_swap}MB)"
        return 0
    fi

    print_warning "Low memory detected. Setting up swap for build..."
    print_status "Current swap: ${current_swap}MB, creating ${needed_swap}MB swap file..."

    # Check if we can create swap (need sudo/root)
    if [ "$EUID" -ne 0 ]; then
        print_warning "Cannot create swap without root privileges."
        print_warning "For low-memory systems, run: sudo ./build.sh"
        print_warning "Continuing without additional swap (build may fail)..."
        return 1
    fi

    # Check if swap file already exists
    if [ -f "$SWAP_FILE" ]; then
        # Disable existing swap file first
        swapoff "$SWAP_FILE" 2>/dev/null || true
        rm -f "$SWAP_FILE"
    fi

    # Create swap file (fallocate is fast, dd is slow fallback)
    if fallocate -l "${needed_swap}M" "$SWAP_FILE" 2>/dev/null; then
        print_status "Swap file allocated instantly with fallocate"
    else
        print_warning "fallocate not supported, using dd (this may take a few minutes)..."
        dd if=/dev/zero of="$SWAP_FILE" bs=1M count="$needed_swap" status=progress
    fi
    chmod 600 "$SWAP_FILE"
    mkswap "$SWAP_FILE"
    swapon "$SWAP_FILE"

    print_status "Swap file created and enabled (${needed_swap}MB)"
    return 0
}

# Build images sequentially for low-memory systems
build_sequential() {
    print_status "Building images sequentially (low-memory mode)..."

    # Enable BuildKit for cache mount support (--mount=type=cache in Dockerfile)
    # BuildKit is more memory-efficient with proper cache usage
    export DOCKER_BUILDKIT=1
    print_status "BuildKit enabled for cache mount support"

    # Build order: smallest/fastest first, largest last
    # icecast is tiny, frontend is medium, backend is largest (pip install)
    local services=("icecast" "frontend" "model-server")

    # Note: model-server, api, and main share the same image (backend/Dockerfile)
    # Docker will use cached image for api and main after model-server is built

    for service in "${services[@]}"; do
        print_status "Building $service..."

        # Use --progress=plain for better visibility on slow builds
        # Do NOT use --no-cache - we want layer caching for speed!
        docker compose build --progress=plain "$service"

        # Optional: prune dangling images (not build cache) to free disk space
        docker image prune -f 2>/dev/null || true
    done

    print_status "All unique images built (api/main share backend image)"
}

# Function to generate version.json with git information
generate_version_info() {
    print_status "Generating version information..."

    # Ensure data directory exists
    mkdir -p data

    # Gather git information
    COMMIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    COMMIT_DATE=$(git log -1 --pretty=%cI 2>/dev/null || echo "unknown")
    BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    REMOTE_URL=$(git config --get remote.origin.url 2>/dev/null || echo "unknown")
    VERSION=$(node -p "require('./frontend/package.json').version" 2>/dev/null || echo "unknown")
    BUILD_TIME=$(date -Iseconds)

    # Convert SSH URL to HTTPS for display
    if [[ "$REMOTE_URL" == git@github.com:* ]]; then
        REMOTE_URL=$(echo "$REMOTE_URL" | sed 's|git@github.com:|https://github.com/|' | sed 's|\.git$||')
    elif [[ "$REMOTE_URL" == *.git ]]; then
        REMOTE_URL="${REMOTE_URL%.git}"
    fi

    # Write version.json
    cat > data/version.json << EOF
{
    "version": "$VERSION",
    "commit": "$COMMIT_HASH",
    "commit_date": "$COMMIT_DATE",
    "branch": "$BRANCH",
    "remote_url": "$REMOTE_URL",
    "build_time": "$BUILD_TIME"
}
EOF

    print_status "Version info: v$VERSION $COMMIT_HASH ($BRANCH)"
}

# Function to show usage
show_usage() {
    echo "Usage: ./build.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --test        Run backend tests before building"
    echo "  --low-memory  Force low-memory build mode (sequential, no BuildKit)"
    echo "  --help        Show this help message"
    echo ""
    echo "Default: Builds all Docker images (no deployment)"
    echo ""
    echo "Note: Frontend is built inside Docker (no Node.js needed on host)"
    echo "For frontend dev with hot-reload: cd frontend && npm run dev"
    echo ""
    echo "Low-memory mode is auto-enabled on systems with <1GB RAM."
    echo "For Pi Zero 2W, run with sudo to enable automatic swap creation:"
    echo "  sudo ./build.sh"
}

# Parse command line arguments
RUN_TESTS=false
FORCE_LOW_MEMORY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            RUN_TESTS=true
            shift
            ;;
        --low-memory)
            FORCE_LOW_MEMORY=true
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

# Main build process
print_status "Starting BirdNET-PiPy build process..."

# Run tests if requested
if [ "$RUN_TESTS" = true ]; then
    print_status "Running backend tests..."
    cd backend/
    if ./docker-test.sh; then
        print_status "All tests passed!"
    else
        print_error "Tests failed! Aborting build."
        exit 1
    fi
    cd ..
fi

# Generate version.json before Docker build
generate_version_info

# Detect system resources and choose build strategy
RAM_KB=$(get_total_ram_kb)
RAM_MB=$((RAM_KB / 1024))
print_status "Detected RAM: ${RAM_MB}MB"

if is_low_memory || [ "$FORCE_LOW_MEMORY" = true ]; then
    if [ "$FORCE_LOW_MEMORY" = true ]; then
        print_status "Low-memory mode forced via --low-memory flag"
    else
        print_warning "Low memory system detected (<1GB RAM)"
    fi
    print_status "Using low-memory build mode (sequential builds, cache enabled)"

    # Try to set up swap for the build
    setup_build_swap || true

    # Build sequentially
    build_sequential
else
    # Standard parallel build with BuildKit for cache mount support
    export DOCKER_BUILDKIT=1
    print_status "Building Docker images..."
    docker compose build

    # Prune dangling images left behind when 'latest' tag is reassigned
    # (low-memory path already does this between builds)
    docker image prune -f 2>/dev/null || true
fi

if [ $? -eq 0 ]; then
    print_status "Docker images built successfully!"
else
    print_error "Docker build failed!"
    exit 1
fi

print_status "Build process complete!"

# Flush output to prevent buffered Docker logs appearing after script ends
sync
sleep 1
