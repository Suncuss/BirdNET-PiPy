#!/bin/bash

# BirdNET-PiPy Build Script
# Builds and deploys the application using Docker
# NOTE: Frontend is now built inside Docker - no Node.js required on host!
# For frontend development with hot-reload: cd frontend && npm run dev

set -e  # Exit on any error

# Run from the repo root regardless of the caller's cwd — everything below
# (docker compose, backend/, frontend/, data/) uses paths relative to it.
# readlink -f follows a symlinked script; empty CDPATH keeps the cd literal.
CDPATH='' cd -- "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"

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

# Build cache size cap for post-build cleanup. Resolution order: environment
# variable, then .env (the persistent home — UI-triggered updates have no
# operator shell for an env override to come from), then the 5GB default.
if [ -z "${BUILD_CACHE_LIMIT:-}" ] && [ -f .env ]; then
    BUILD_CACHE_LIMIT=$(grep -E '^BUILD_CACHE_LIMIT=' .env | tail -1 | cut -d= -f2)
fi
BUILD_CACHE_LIMIT="${BUILD_CACHE_LIMIT:-5GB}"

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

# Reclaim Docker disk space: dangling images, then build cache down to
# BUILD_CACHE_LIMIT. Eviction is least-recently-used first, so the newest
# build's layers stay warm for the next rebuild. Older engines lack
# --max-used-space; fall back to its pre-buildx-0.17 name --keep-storage,
# then to an age filter as a last resort. The summary line differs across
# versions ("Total:" vs "Total reclaimed space:"), so accept both.
prune_docker_artifacts() {
    local img_reclaimed
    img_reclaimed=$(docker image prune -f 2>/dev/null \
        | grep -E '^Total( reclaimed space)?:' | awk '{print $NF}')
    print_status "Cleanup: reclaimed ${img_reclaimed:-0B} from dangling images"

    local cache_reclaimed
    cache_reclaimed=$( (docker builder prune --max-used-space="$BUILD_CACHE_LIMIT" -f 2>/dev/null \
        || docker builder prune --keep-storage="$BUILD_CACHE_LIMIT" -f 2>/dev/null \
        || docker builder prune --filter "until=168h" -f 2>/dev/null) \
        | grep -E '^Total( reclaimed space)?:' | awk '{print $NF}')
    print_status "Cleanup: reclaimed ${cache_reclaimed:-0B} from build cache (cap: $BUILD_CACHE_LIMIT)"
}

# Detect total RAM in KB
get_total_ram_kb() {
    grep MemTotal /proc/meminfo | awk '{print $2}'
}

# Check if system is low memory (< 1GB)
is_low_memory() {
    local ram_kb
    ram_kb=$(get_total_ram_kb)
    [ "$ram_kb" -lt "$LOW_MEMORY_THRESHOLD_KB" ]
}

# Get current swap size in MB
get_swap_size_mb() {
    free -m | awk '/Swap:/ {print $2}'
}

# Create or extend swap for low-memory builds
setup_build_swap() {
    local current_swap
    current_swap=$(get_swap_size_mb)
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
        print_warning "Run 'sudo ./install.sh' once to provision swap for this system."
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
# Optional args: space-separated service names to build (default: all)
build_sequential() {
    print_status "Building images sequentially (low-memory mode)..."

    # Enable BuildKit for cache mount support (--mount=type=cache in Dockerfile)
    # BuildKit is more memory-efficient with proper cache usage
    export DOCKER_BUILDKIT=1
    print_status "BuildKit enabled for cache mount support"

    # Build order: smallest/fastest first, largest last
    # icecast is tiny, frontend is medium, backend is largest (pip install)
    local all_services=("icecast" "frontend" "model-server")

    # Note: api and main share model-server's image (no build: directive)

    # Filter to requested services if specified, preserving the build order.
    # Args are pre-validated against all_services by the CLI parsing.
    local services=()
    if [ $# -gt 0 ]; then
        local requested=" $* "
        for svc in "${all_services[@]}"; do
            if [[ "$requested" == *" $svc "* ]]; then
                services+=("$svc")
            fi
        done
    else
        services=("${all_services[@]}")
    fi

    for service in "${services[@]}"; do
        print_status "Building $service..."

        # Use --progress=plain for better visibility on slow builds
        # Do NOT use --no-cache - we want layer caching for speed!
        if ! docker compose build --progress=plain "$service"; then
            print_error "Docker build failed for $service!"
            exit 1
        fi

        # Reclaim space between builds — matters most on small SD cards
        prune_docker_artifacts
    done

    print_status "All requested images built"
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
    VERSION=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' frontend/package.json 2>/dev/null | head -1)
    VERSION="${VERSION:-unknown}"
    BUILD_TIME=$(date -Iseconds)

    # Convert SSH URL to HTTPS for display
    if [[ "$REMOTE_URL" == git@github.com:* ]]; then
        REMOTE_URL=$(echo "$REMOTE_URL" | sed 's|git@github.com:|https://github.com/|' | sed 's|\.git$||')
    elif [[ "$REMOTE_URL" == *.git ]]; then
        REMOTE_URL="${REMOTE_URL%.git}"
    fi

    # Write version.json — escape values so special chars in git metadata
    # (e.g. double quotes in branch names) don't produce invalid JSON.
    json_escape() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
    if ! cat > data/version.json << EOF
{
    "version": "$(json_escape "$VERSION")",
    "commit": "$(json_escape "$COMMIT_HASH")",
    "commit_date": "$(json_escape "$COMMIT_DATE")",
    "branch": "$(json_escape "$BRANCH")",
    "remote_url": "$(json_escape "$REMOTE_URL")",
    "build_time": "$(json_escape "$BUILD_TIME")"
}
EOF
    then
        print_error "Failed to write data/version.json (permission issue?)"
        exit 1
    fi

    print_status "Version info: v$VERSION $COMMIT_HASH ($BRANCH)"
}

# Function to show usage
show_usage() {
    echo "Usage: ./build.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --test                Run backend tests before building"
    echo "  --low-memory          Force low-memory build mode (sequential builds)"
    echo "  --services SVC,...    Build only specified services (comma-separated)"
    echo "  --version-only        Only generate version.json, skip Docker build"
    echo "  --help                Show this help message"
    echo ""
    echo "Default: Builds all Docker images (no deployment)"
    echo ""
    echo "Environment:"
    echo "  BUILD_CACHE_LIMIT     Docker build cache kept after cleanup (default: 5GB;"
    echo "                        set as an env var or a .env entry)"
    echo ""
    echo "Note: Frontend is built inside Docker (no Node.js needed on host)"
    echo "For frontend dev with hot-reload: cd frontend && npm run dev"
    echo ""
    echo "Low-memory mode is auto-enabled on systems with <1GB RAM."
    echo "(install.sh provisions swap on such systems; builds reuse it)"
    echo ""
    echo "Valid services for --services: model-server, icecast, frontend"
}

# Parse command line arguments
RUN_TESTS=false
FORCE_LOW_MEMORY=false
BUILD_SERVICES=""
SELECTED_SERVICES=()
VERSION_ONLY=false

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
        --services)
            if [ -z "${2:-}" ] || [[ "${2:-}" == --* ]]; then
                print_error "--services requires a comma-separated value"
                show_usage
                exit 1
            fi
            # Convert comma-separated to space-separated
            BUILD_SERVICES="${2//,/ }"
            if [ -z "${BUILD_SERVICES// }" ]; then
                print_error "--services cannot be empty"
                show_usage
                exit 1
            fi
            shift 2
            ;;
        --version-only)
            VERSION_ONLY=true
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

# Validate and normalize selected services
if [ -n "$BUILD_SERVICES" ]; then
    read -r -a SELECTED_SERVICES <<< "$BUILD_SERVICES"
    for svc in "${SELECTED_SERVICES[@]}"; do
        case "$svc" in
            model-server|icecast|frontend)
                ;;
            *)
                print_error "Unknown service in --services: $svc"
                show_usage
                exit 1
                ;;
        esac
    done
fi

# Main build process
print_status "Starting BirdNET-PiPy build process..."

# Handle --version-only: just generate version.json and exit
if [ "$VERSION_ONLY" = true ]; then
    generate_version_info
    print_status "Version info generated (--version-only mode)"
    exit 0
fi

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

# Detect system resources and choose build strategy
RAM_KB=$(get_total_ram_kb)
RAM_MB=$((RAM_KB / 1024))
print_status "Detected RAM: ${RAM_MB}MB"

if [ ${#SELECTED_SERVICES[@]} -gt 0 ]; then
    print_status "Selective build requested: ${SELECTED_SERVICES[*]}"
fi

if is_low_memory || [ "$FORCE_LOW_MEMORY" = true ]; then
    if [ "$FORCE_LOW_MEMORY" = true ]; then
        print_status "Low-memory mode forced via --low-memory flag"
    else
        print_warning "Low memory system detected (<1GB RAM)"
    fi
    print_status "Using low-memory build mode (sequential builds, cache enabled)"

    # Try to set up swap for the build
    setup_build_swap || true

    # Build sequentially (with optional service filter)
    build_sequential "${SELECTED_SERVICES[@]}"
else
    # Standard parallel build with BuildKit for cache mount support
    export DOCKER_BUILDKIT=1
    if [ ${#SELECTED_SERVICES[@]} -gt 0 ]; then
        print_status "Building Docker images: ${SELECTED_SERVICES[*]}"
        if ! docker compose build "${SELECTED_SERVICES[@]}"; then
            print_error "Docker build failed!"
            exit 1
        fi
    else
        print_status "Building Docker images..."
        if ! docker compose build; then
            print_error "Docker build failed!"
            exit 1
        fi
    fi

    # Prune images orphaned by the tag reassignment and cap the build cache
    # (low-memory path already does this between builds)
    prune_docker_artifacts
fi

print_status "Docker images built successfully!"

# Generate version.json after successful build so it reflects what's actually running
generate_version_info

print_status "Build process complete!"

# Flush output to prevent buffered Docker logs appearing after script ends
sync
sleep 1
