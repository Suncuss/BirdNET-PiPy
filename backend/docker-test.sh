#!/bin/bash
# Run tests inside Docker container
# This ensures tests run in the same environment as production

set -e

echo "Running tests in Docker container..."
echo "===================================="

# Tag the test image per-branch so concurrent worktrees (e.g. parallel agents)
# don't race on one shared 'birdnet-test' tag. Same branch reuses its image
# (cache-friendly); different branches/worktrees build independent images.
BRANCH=$(git branch --show-current 2>/dev/null || true)
[ -z "$BRANCH" ] && BRANCH=$(git rev-parse --short HEAD 2>/dev/null || echo local)
# Sanitize to a valid Docker tag ([a-zA-Z0-9_.-]); e.g. feature/x -> feature-x
TAG=$(printf '%s' "$BRANCH" | tr -c 'a-zA-Z0-9_.-' '-')
IMAGE="birdnet-test:${TAG}"
echo "Test image: ${IMAGE}"

# Build test image if needed
docker build -f Dockerfile.test -t "$IMAGE" .

# Run tests in container as the host user so pytest caches, coverage
# output, and test artifacts on the bind mount stay host-owned (root-run
# containers used to leave files the host can't modify or clean up).
# HOME points at /tmp because the image has no home directory for an
# arbitrary --user uid (matplotlib and friends want a writable HOME).
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -v "$(pwd):/app" \
    -w /app \
    -e PYTHONPATH=/app \
    "$IMAGE" \
    bash -c "./run-tests.sh $*"

# If coverage was requested, remind about the report
if [[ "$@" == *"coverage"* ]]; then
    echo ""
    echo "Coverage report is available at: backend/htmlcov/index.html"
fi