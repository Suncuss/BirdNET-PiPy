# Pin the multi-platform index so upstream base rebuilds do not invalidate every
# BirdNET layer between deliberate dependency updates. This digest contains
# both the AMD64 and ARM64 images built by CI.
FROM python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7 AS python-deps

# Assemble the venv in a disposable stage. Every dependency ships a prebuilt
# ARM64 wheel, so no compiler toolchain is installed; if a future dependency
# starts building from source, pip fails loudly here instead of silently
# requiring one.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .

# Keep numpy separate so its pinned ABI is established before resolving the
# remaining ML dependencies. No piwheels index: it publishes only armv6l and
# armv7l wheels, so it never matched the arm64/amd64 images we build, and
# 32-bit hosts are rejected by install.sh anyway.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install numpy==1.26.4 && \
    pip install -r requirements.txt

# Release gate: validate the bundled V3.1 model and geomodel against their
# pinned manifests (sha256, shapes) on every build. This stage is not shipped;
# the runtime stage copies its marker file, which is what makes BuildKit run
# it. It only re-runs when a validator or a bundled asset changes.
FROM python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7 AS asset-check
COPY --from=python-deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /check
COPY model_service/label_utils.py \
     model_service/model_assets.py \
     model_service/geomodel_assets.py \
     model_service/birdnet_v3_assets.py \
     ./model_service/
COPY model_service/models/geomodel ./model_service/models/geomodel
COPY model_service/models/v3.1 ./model_service/models/v3.1
RUN python -m model_service.geomodel_assets && \
    python -m model_service.birdnet_v3_assets && \
    touch /assets-validated

# Use the same pinned multi-platform base for the shipped runtime image.
FROM python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7

# Build arguments for user/group IDs (defaults for fallback)
ARG UID=1000
ARG GID=1000

# Install runtime libraries only.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    tzdata \
    # PulseAudio client library for audio access via socket
    libpulse0

WORKDIR /app

# Copy only the finished environment; intermediate wheel caches remain in the
# discarded python-deps stage.
COPY --from=python-deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Runtime user. /app is the bind-mount point; WORKDIR created it root-owned.
RUN groupadd -g ${GID} birdnet && \
    useradd -u ${UID} -g birdnet -m birdnet && \
    chown ${UID}:${GID} /app

# The image carries no application code or models: compose bind-mounts the
# backend checkout over /app for every service, and the runtime loaders
# re-validate the bundled models they actually read. So the image changes only
# when dependencies do, and a fresh install doesn't download the models twice.
# That also means a code change no longer changes the image, so it can't make
# compose recreate the containers: build.sh's BIRDNET_BUILD_ID label does
# (docker-compose.yml).
COPY --from=asset-check /assets-validated /opt/assets-validated

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Switch to non-root user
USER birdnet

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
