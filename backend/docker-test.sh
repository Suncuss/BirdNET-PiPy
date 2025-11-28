#!/bin/bash
# Run tests inside Docker container
# This ensures tests run in the same environment as production

set -e

echo "Running tests in Docker container..."
echo "===================================="

# Build test image if needed
docker build -f Dockerfile.test -t birdnet-test .

# Run tests in container
docker run --rm \
    -v $(pwd):/app \
    -w /app \
    -e PYTHONPATH=/app \
    birdnet-test \
    bash -c "./run-tests.sh $*"

# If coverage was requested, remind about the report
if [[ "$@" == *"coverage"* ]]; then
    echo ""
    echo "Coverage report is available at: backend/htmlcov/index.html"
fi