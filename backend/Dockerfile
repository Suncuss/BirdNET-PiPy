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

# Use piwheels for pre-compiled ARM packages. Keep numpy separate so its pinned
# ABI is established before resolving the remaining ML dependencies.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --extra-index-url https://www.piwheels.org/simple \
    numpy==1.26.4 && \
    pip install --extra-index-url https://www.piwheels.org/simple \
    -r requirements.txt

# Prune bundled models out of the per-release source layer. They ship in the
# dedicated COPY layers below instead, so a routine source change pushes a few
# megabytes, not the ~55MB of model blobs. The prune must be explicit: BuildKit
# only dedupes files identical to lower layers on some builders (CI yes,
# local dockerd no), so leaving them in COPY . . re-ships them from local builds.
FROM python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7 AS source
COPY . /src
RUN rm -rf /src/model_service/models

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

# Remaining bundled model data in its own rarely-invalidated layers, after the
# gates so a species-table refresh does not re-run the memory-intensive checks.
COPY --chown=${UID}:${GID} model_service/models/v2.4 ./model_service/models/v2.4
COPY --chown=${UID}:${GID} model_service/models/species_table.csv \
     model_service/models/ebird_codes.json \
     ./model_service/models/

# Source code last: the only layer that changes on a routine release.
COPY --from=source --chown=${UID}:${GID} /src ./

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
