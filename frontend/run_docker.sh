#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Configuration
DOCKER_IMAGE_NAME="birdnet-pipy-frontend"
CONTAINER_NAME="birdnet-pipy-frontend-container"
HOST_PORT=80
CONTAINER_PORT=80

# Function to check if a container is running
is_container_running() {
    docker ps --filter "name=$1" --format '{{.Names}}' | grep -q "$1"
}

echo "Checking if dist folder exists..."
if [ ! -d "dist" ]; then
    echo "Error: dist folder not found in the current directory"
    exit 1
fi

echo "Building Docker image..."
docker build -t $DOCKER_IMAGE_NAME:latest .

echo "Stopping and removing old container if it exists..."
if is_container_running $CONTAINER_NAME; then
    docker stop $CONTAINER_NAME
    docker rm $CONTAINER_NAME
fi

echo "Running new container..."
docker run -d --name $CONTAINER_NAME -p $HOST_PORT:$CONTAINER_PORT $DOCKER_IMAGE_NAME:latest
echo "Container is now running on http://localhost:$HOST_PORT"