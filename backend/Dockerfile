FROM python:3.11-slim

# Build arguments for user/group IDs (defaults for fallback)
ARG UID=1000
ARG GID=1000

# Cache apt packages for faster rebuilds
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    sox \
    ffmpeg \
    curl \
    # PulseAudio client library for audio access via socket
    libpulse0

WORKDIR /app

COPY requirements.txt .

# Use piwheels for pre-compiled ARM packages (massive speedup on Raspberry Pi)
# Split install: heavy packages first (better caching), then rest
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --extra-index-url https://www.piwheels.org/simple \
    numpy==1.26.4 scipy==1.15.3 matplotlib==3.10.3 && \
    pip install --extra-index-url https://www.piwheels.org/simple \
    -r requirements.txt

COPY . .

# Create user with matching host UID/GID
RUN groupadd -g ${GID} birdnet && \
    useradd -u ${UID} -g birdnet -m birdnet && \
    chown -R birdnet:birdnet /app

# Switch to non-root user
USER birdnet

# Set environment variables
ENV BASE_DIR=/app
ENV BIRDNET_SERVICE_PORT=5001
ENV API_PORT=5002