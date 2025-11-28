FROM debian:bookworm-slim

# Build arguments for user/group IDs
ARG UID=1000
ARG GID=1000

RUN apt-get update && apt-get install -y --no-install-recommends \
    icecast2 \
    ffmpeg \
    libpulse0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create user with matching host UID/GID
# Use 'streamer' to avoid conflict with icecast package's own user
RUN groupadd -g ${GID} streamer && \
    useradd -u ${UID} -g streamer -m streamer && \
    mkdir -p /var/log/icecast2 /etc/icecast2 && \
    chown -R streamer:streamer /app /var/log/icecast2 /etc/icecast2

# Copy entry script and set permissions
COPY --chown=streamer:streamer scripts/start-icecast.sh /app/start-icecast.sh
RUN chmod +x /app/start-icecast.sh

# Switch to non-root user
USER streamer

EXPOSE 8888

CMD ["/app/start-icecast.sh"]
