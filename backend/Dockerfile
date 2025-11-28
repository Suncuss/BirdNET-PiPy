FROM python:3.11-slim

# Build arguments for user/group IDs (defaults for fallback)
ARG UID=1000
ARG GID=1000

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    sox \
    ffmpeg \
    curl \
    # PulseAudio client library for audio access via socket
    libpulse0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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