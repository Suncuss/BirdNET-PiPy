#!/bin/bash
# BirdNET-PiPy Install Script Test Runner
# Runs install.sh tests in an isolated Docker container with systemd
#
# Usage:
#   ./docker-test-install.sh              # Run all tests
#   ./docker-test-install.sh --keep       # Keep container for debugging
#   ./docker-test-install.sh --unit-only  # Run only unit tests (fast)
#   ./docker-test-install.sh --build-only # Only build the test image

set -e

# Script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Configuration
IMAGE_NAME="birdnet-install-test"
CONTAINER_NAME="birdnet-install-test-$$"
# Per-run volume for the nested Docker's /var/lib/docker — keeps inner image
# layers on a real filesystem (enables overlay2) instead of in the container's
# writable layer, and lets cleanup reclaim them reliably.
DOCKER_VOLUME_NAME="birdnet-install-test-docker-$$"
MIN_FREE_DISK_GB=15

# Parse arguments
KEEP_CONTAINER=false
UNIT_ONLY=false
BUILD_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --keep)
            KEEP_CONTAINER=true
            shift
            ;;
        --unit-only)
            UNIT_ONLY=true
            shift
            ;;
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        --help)
            echo "BirdNET-PiPy Install Script Test Runner"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --keep        Keep container running after tests for debugging"
            echo "  --unit-only   Run only unit tests (no full installation)"
            echo "  --build-only  Only build the test image, don't run tests"
            echo "  --help        Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Run all tests"
            echo "  $0 --unit-only        # Quick unit tests only"
            echo "  $0 --keep             # Keep container for debugging"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[TEST]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Cleanup function
cleanup() {
    if [ "$KEEP_CONTAINER" = true ]; then
        print_warning "Container kept for debugging: $CONTAINER_NAME"
        print_warning "To access: docker exec -it $CONTAINER_NAME bash"
        print_warning "To stop: docker stop $CONTAINER_NAME && docker rm -v $CONTAINER_NAME && docker volume rm $DOCKER_VOLUME_NAME"
    else
        print_status "Cleaning up container..."
        docker stop "$CONTAINER_NAME" 2>/dev/null || true
        docker rm -v "$CONTAINER_NAME" 2>/dev/null || true
        docker volume rm "$DOCKER_VOLUME_NAME" 2>/dev/null || true
    fi
}

# Guard against the failure mode where a run fills the disk: reclaim leftovers
# from previous crashed runs, then refuse to start without headroom. Only stopped
# containers and dangling volumes are removed, so a --keep'd debug container or a
# concurrently-running suite (both still up) survive untouched.
preflight() {
    local stale_containers stale_volumes live_containers avail_kb
    stale_containers=$(docker ps -aq \
        --filter "name=birdnet-install-test-" \
        --filter "status=exited" --filter "status=created" --filter "status=dead")
    if [ -n "$stale_containers" ]; then
        print_warning "Removing stopped install-test containers from previous runs..."
        # shellcheck disable=SC2086  # word splitting over container IDs is intended
        docker rm -f -v $stale_containers >/dev/null 2>&1 || true
    fi
    # dangling=true => not attached to any container, so a volume in use by a
    # kept or concurrent run is never reclaimed out from under it.
    stale_volumes=$(docker volume ls -q \
        --filter "name=birdnet-install-test-docker-" --filter "dangling=true")
    if [ -n "$stale_volumes" ]; then
        print_warning "Removing dangling install-test volumes from previous runs..."
        # shellcheck disable=SC2086
        docker volume rm $stale_volumes >/dev/null 2>&1 || true
    fi

    live_containers=$(docker ps -q --filter "name=birdnet-install-test-")
    if [ -n "$live_containers" ]; then
        print_warning "Other install-test containers are still running (kept or concurrent runs); leaving them untouched."
    fi

    avail_kb=$(df -Pk /var/lib/docker 2>/dev/null | awk 'NR==2 {print $4}')
    [ -n "$avail_kb" ] || avail_kb=$(df -Pk / 2>/dev/null | awk 'NR==2 {print $4}')
    # Fail closed: a non-numeric value would otherwise make the comparison a
    # no-op (test conditions are exempt from set -e), silently skipping the guard.
    if ! [[ "$avail_kb" =~ ^[0-9]+$ ]]; then
        print_error "Could not determine free disk space — aborting rather than risk filling the disk."
        exit 1
    fi
    if [ "$avail_kb" -lt $((MIN_FREE_DISK_GB * 1024 * 1024)) ]; then
        print_error "Less than ${MIN_FREE_DISK_GB}GB free on the Docker disk — aborting so the test run can't fill it."
        exit 1
    fi
}

# Set up cleanup trap
trap cleanup EXIT

preflight

# Build the test image
print_status "Building test image..."
docker build -f "$SCRIPT_DIR/Dockerfile.test" -t "$IMAGE_NAME" "$SCRIPT_DIR"

if [ "$BUILD_ONLY" = true ]; then
    print_status "Build complete. Exiting (--build-only specified)."
    exit 0
fi

# Start the container with systemd
print_status "Starting test container with systemd..."
docker run -d \
    --name "$CONTAINER_NAME" \
    --privileged \
    --cgroupns=host \
    -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    -v "$DOCKER_VOLUME_NAME:/var/lib/docker" \
    -v "$PROJECT_ROOT:/project:ro" \
    -v "$SCRIPT_DIR:/tests:ro" \
    "$IMAGE_NAME"

# Wait for systemd to initialize
print_status "Waiting for systemd to initialize..."
for i in {1..30}; do
    if docker exec "$CONTAINER_NAME" systemctl is-system-running --quiet 2>/dev/null; then
        break
    fi
    # Also accept "degraded" state (some services may fail in container)
    state=$(docker exec "$CONTAINER_NAME" systemctl is-system-running 2>/dev/null || echo "starting")
    if [ "$state" = "running" ] || [ "$state" = "degraded" ]; then
        break
    fi
    if [ $i -eq 30 ]; then
        print_error "Timeout waiting for systemd"
        docker exec "$CONTAINER_NAME" systemctl status || true
        exit 1
    fi
    sleep 1
done
print_status "Systemd is ready (state: $state)"

# Wait for Docker daemon to be ready (inside the container)
print_status "Waiting for Docker daemon..."
for i in {1..30}; do
    if docker exec "$CONTAINER_NAME" docker info &>/dev/null; then
        break
    fi
    if [ $i -eq 30 ]; then
        print_error "Timeout waiting for Docker daemon"
        docker exec "$CONTAINER_NAME" systemctl status docker || true
        exit 1
    fi
    sleep 1
done
print_status "Docker daemon is ready"

# Copy project to writable location in container
print_status "Setting up test environment..."
docker exec "$CONTAINER_NAME" bash -c "
    rm -rf /home/testuser/BirdNET-PiPy
    mkdir -p /home/testuser/BirdNET-PiPy
    # Copy the repo but NOT the runtime data directory — on a live system ./data
    # holds the recordings/spectrogram archive (tens of GB) and copying it can
    # fill the host disk. The install tests need code + .git (for update tests),
    # and a fresh install starts with no data anyway.
    tar -C /project --exclude='./data' --exclude='./frontend/node_modules' --exclude='./internal_docs' -cf - . | tar -C /home/testuser/BirdNET-PiPy -xf -
    chown -R testuser:testuser /home/testuser/BirdNET-PiPy
    chmod +x /home/testuser/BirdNET-PiPy/install.sh /home/testuser/BirdNET-PiPy/build.sh

    # Disable BuildKit cache mounts (don't work in DinD due to overlay issues)
    echo 'export DOCKER_BUILDKIT=0' >> /etc/environment
"

# Run BATS tests
print_status "Running BATS tests..."
echo ""

# Determine which tests to run
if [ "$UNIT_ONLY" = true ]; then
    BATS_FILTER="--filter 'unit:'"
    print_status "Running unit tests only..."
else
    BATS_FILTER=""
    print_status "Running all tests..."
fi

# Run tests
set +e  # Don't exit on test failure
docker exec "$CONTAINER_NAME" bash -c "
    cd /tests
    export PROJECT_DIR=/home/testuser/BirdNET-PiPy
    export BATS_LIB_PATH=/usr/lib
    bats $BATS_FILTER test_install.bats
"
TEST_EXIT_CODE=$?
set -e

echo ""
if [ $TEST_EXIT_CODE -eq 0 ]; then
    print_status "All tests passed!"
else
    print_error "Some tests failed (exit code: $TEST_EXIT_CODE)"
fi

exit $TEST_EXIT_CODE
