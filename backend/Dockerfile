# Pin the multi-platform index so upstream base rebuilds do not invalidate every
# BirdNET layer between deliberate dependency updates. This digest contains
# both the AMD64 and ARM64 images built by CI.
FROM python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7 AS python-deps

# Build native wheels in a disposable stage. timezonefinder currently builds
# from source on ARM64, so a compiler is still required during image creation,
# but none of this toolchain needs to ship to stations.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

# Use piwheels for pre-compiled ARM packages. Keep numpy separate so its pinned
# ABI is established before resolving the remaining ML dependencies.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --extra-index-url https://www.piwheels.org/simple \
    numpy==1.26.4 && \
    pip install --extra-index-url https://www.piwheels.org/simple \
    -r requirements.txt

# Use the same pinned multi-platform base for the shipped runtime image.
FROM python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7

# Build arguments for user/group IDs (defaults for fallback)
ARG UID=1000
ARG GID=1000

# Install runtime libraries only; the compiler toolchain stays in python-deps.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    tzdata \
    # PulseAudio client library for audio access via socket
    libpulse0

WORKDIR /app

# Copy only the finished environment; build-essential and intermediate wheel
# caches remain in the discarded python-deps stage.
COPY --from=python-deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create the runtime user before the source copies: COPY --chown bakes
# ownership into each layer, where a trailing chown -R would duplicate all of
# /app into an extra layer shipped with every update. Non-recursive chown:
# WORKDIR created /app root-owned; the copies below own their contents.
RUN groupadd -g ${GID} birdnet && \
    useradd -u ${UID} -g birdnet -m birdnet && \
    chown ${UID}:${GID} /app

# Keep release validation cached across unrelated source edits. Only validator,
# parser, or bundled-asset changes invalidate these memory-intensive gates.
COPY --chown=${UID}:${GID} model_service/label_utils.py \
     model_service/model_assets.py \
     model_service/geomodel_assets.py \
     model_service/birdnet_v3_assets.py \
     ./model_service/
COPY --chown=${UID}:${GID} model_service/models/geomodel ./model_service/models/geomodel
COPY --chown=${UID}:${GID} model_service/models/v3.1 ./model_service/models/v3.1
RUN python -m model_service.geomodel_assets
RUN python -m model_service.birdnet_v3_assets
# Compose bind-mounts the checkout over /app, so runtime loaders repeat the
# authoritative checks against the bytes each service actually reads.

COPY --chown=${UID}:${GID} . .

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Switch to non-root user
USER birdnet

# Set environment variables
ENV BASE_DIR=/app
ENV BIRDNET_SERVICE_PORT=5001
ENV API_PORT=5002

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
