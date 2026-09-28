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
# Hard memory cap (RAM+swap combined): a runaway test OOMs its own
# container instead of filling the host's 8GB swapfile and thrashing
# the machine into a multi-hour lockout. (2026-08-16 incident: an
# unbounded loop in a review probe container grew to ~2GB RSS
# overnight, exhausted swap, and froze the box for 9 hours until the
# kernel OOM killer fired. The full suite peaks well under this cap.)
#
# BOTH layers are needed: Raspberry Pi OS ships with the memory cgroup
# controller DISABLED, so Docker silently discards --memory there
# ("WARNING: No memory limit support" in docker info). The in-container
# ulimit -v (RLIMIT_AS, no cgroups required) is the fallback that
# actually bites on such hosts; --memory takes over where the
# controller exists (CI, or after cgroup_enable=memory cgroup_memory=1
# is added to /boot/firmware/cmdline.txt and the host rebooted).
#
# /app/data is a fresh in-memory tmpfs for every run. Every data path is
# hard-wired under /app/data (config/settings.py BASE_DIR), and modules open
# the DB, logs and flags there at import time, so without this the suite read
# and wrote the host's backend/data: results depended on leftover settings a
# clean checkout (or CI) doesn't have. tests/conftest.py refuses to run
# without it. mode=1777: the tmpfs is root-owned and --user must write it.
docker run --rm \
    --user "$(id -u):$(id -g)" \
    --memory=4g --memory-swap=4g \
    -e HOME=/tmp \
    -v "$(pwd):/app" \
    --tmpfs /app/data:rw,mode=1777 \
    -w /app \
    -e PYTHONPATH=/app \
    "$IMAGE" \
    bash -c 'ulimit -v 6291456; exec ./run-tests.sh "$@"' run-tests "$@"

# The stream supervisor (deployment/audio) has its own unittest suite; it
# loads backend modules by path, so it runs from a copy of the repo layout
# (read-only mounts) along with the full backend suite. It spawns
# subprocesses, so it gets the same two memory guards as the run above.
if [ $# -eq 0 ]; then
    echo ""
    echo "Running stream supervisor tests..."
    docker run --rm \
        --user "$(id -u):$(id -g)" \
        --memory=4g --memory-swap=4g \
        -e HOME=/tmp \
        -v "$(pwd):/src/backend:ro" \
        -v "$(pwd)/../deployment:/src/deployment:ro" \
        -w /src \
        "$IMAGE" \
        bash -c 'ulimit -v 6291456; exec python -m unittest discover -s deployment/audio/tests'
fi

# If coverage was requested, remind about the report
if [[ "$*" == *"coverage"* ]]; then
    echo ""
    echo "Coverage report is available at: backend/htmlcov/index.html"
fi