#!/bin/bash
# Remove ghost Docker container records.
#
# After an unclean shutdown the daemon can be left with container metadata
# dirs whose overlay2 RW layer is gone ("failed to load container mount ...
# RW layer not found" at daemon start). Such records half-load on every
# daemon start: `docker ps -a` lists them, but inspect/rm/compose fail on
# them with "No such container", which aborts `docker compose up` for the
# whole stack. The only durable fix is deleting the orphaned metadata dirs
# while the daemon is stopped.
#
# Runs as root via a sudoers rule; called by birdnet-service.sh with the
# ghost container IDs it detected (see recover_ghost_containers).

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "docker-ghost-heal: must run as root" >&2
    exit 1
fi

if [ $# -lt 1 ]; then
    echo "usage: $0 <64-hex-container-id>..." >&2
    exit 1
fi

# Full 64-hex IDs only: the IDs become path components under the data root,
# so reject anything else outright.
for id in "$@"; do
    if ! [[ "$id" =~ ^[0-9a-f]{64}$ ]]; then
        echo "docker-ghost-heal: invalid container id: $id" >&2
        exit 1
    fi
done

# Resolve the daemon's data root while it is still running - installs can
# move it off the SD card via daemon.json. This immediately precedes
# destructive removal, so no guessing: if the daemon cannot tell us, abort
# rather than falling back to a default that may be a stale tree on a
# custom-data-root system. The caller retries after ensure_docker_running.
data_root=$(docker info --format '{{ .DockerRootDir }}' 2>/dev/null) || data_root=""
if [ -z "$data_root" ] || [[ "$data_root" != /* ]] || [ ! -d "$data_root/containers" ]; then
    echo "docker-ghost-heal: cannot resolve docker data root (daemon down?); refusing surgery" >&2
    exit 1
fi

# From the moment we start stopping Docker, it MUST come back no matter what
# fails below - exiting with the daemon down would leave the host with no
# Docker at all, which is worse than the ghosts. Preserve the original exit
# status; a failed daemon start forces a failure status.
# shellcheck disable=SC2154  # rc is assigned inside the trap itself
trap 'rc=$?; systemctl start docker.socket docker.service || rc=1; exit $rc' EXIT

# Stop the socket too, or any docker CLI call re-activates the daemon
# mid-surgery. ignore-dependencies is load-bearing: without it, a unit with
# Requires=docker.service (e.g. birdnet-pipy's pre-0.8.8 template - our own
# caller) gets a stop job enqueued first, which waits on the caller's script,
# which waits on us - a deadlock that ends in SIGKILL, which runs no traps
# and leaves Docker stopped. With it, only these two units are touched.
systemctl stop --job-mode=ignore-dependencies docker.socket docker.service

for id in "$@"; do
    dir="$data_root/containers/$id"
    if [ -d "$dir" ]; then
        echo "docker-ghost-heal: removing $dir"
        rm -rf "$dir"
    else
        echo "docker-ghost-heal: no metadata dir for $id (skipping)"
    fi
done

echo "docker-ghost-heal: done, restarting Docker"
