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
    "commit": "$COMMIT_HASH",
    "commit_date": "$COMMIT_DATE",
    "branch": "$BRANCH",
    "remote_url": "$REMOTE_URL",
    "build_time": "$BUILD_TIME"
}
EOF

    print_status "Version info: $COMMIT_HASH ($BRANCH)"
}

# Function to show usage
show_usage() {
    echo "Usage: ./build.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --test        Run backend tests before building"
    echo "  --help        Show this help message"
    echo ""
    echo "Default: Builds all Docker images (no deployment)"
    echo ""
    echo "Note: Frontend is built inside Docker (no Node.js needed on host)"
    echo "For frontend dev with hot-reload: cd frontend && npm run dev"
}

# Parse command line arguments
RUN_TESTS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            RUN_TESTS=true
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

# Build Docker images (includes frontend build inside container)
print_status "Building Docker images..."
docker compose build

if [ $? -eq 0 ]; then
    print_status "Docker images built successfully!"
else
    print_error "Docker build failed!"
    exit 1
fi

print_status "Build process complete!"
