FROM python:3.11-slim

# Build arguments for user/group IDs (defaults for fallback)
ARG UID=1000
ARG GID=1000

# Cache apt packages for faster rebuilds
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    curl \
    tzdata \
    # PulseAudio client library for audio access via socket
    libpulse0

WORKDIR /app

COPY requirements.txt .

# Use piwheels for pre-compiled ARM packages (massive speedup on Raspberry Pi)
# Split install: heavy packages first (better caching), then rest
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --extra-index-url https://www.piwheels.org/simple \
    numpy==1.26.4 && \
    pip install --extra-index-url https://www.piwheels.org/simple \
    -r requirements.txt

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
