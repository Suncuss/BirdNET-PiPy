# System Administration & Architecture

This document details the internal architecture, service management, and advanced configuration of BirdNET-PiPy.

## Directory Structure

### Runtime Control (`deployment/`)
- **`birdnet-service.sh`**: The master orchestration script. managed by systemd. It handles:
  - Docker container lifecycle
  - Audio backend detection and startup (PulseAudio vs PipeWire)
  - Auto-updates via git

### Audio Configuration (`deployment/audio/`)
- Includes PulseAudio configs (`system.pa`, `daemon.conf`) for running in system-wide mode on RPi OS Lite.
- Icecast streaming server configuration.

---

For audio architecture details, see **[Audio Architecture](../docs/ARCHITECTURE.md#audio-architecture)** in the Architecture docs.

---

## Service Management

The system runs as a standard systemd service named `birdnet-pipy`.

### Basic Controls

```bash
sudo systemctl start birdnet-pipy    # Start
sudo systemctl stop birdnet-pipy     # Stop
sudo systemctl restart birdnet-pipy  # Restart
sudo systemctl status birdnet-pipy   # Check Status
```

### Viewing Logs

**Service Controller Logs** (Wrapper script output):
```bash
journalctl -u birdnet-pipy -f
```

**Application Logs** (Inner container output):
```bash
cd ~/BirdNET-PiPy
docker compose logs -f [container_name]
# containers: main, api, model-server, frontend, icecast
```

---

## Maintenance Triggers

You can trigger maintenance tasks by touching flag files, avoiding full reboots.

| Trigger File | Action | Description |
|--------------|--------|-------------|
| `data/flags/restart-backend` | **Restart** | Restarts all Docker containers. Useful after config changes. |
| `data/flags/update-requested` | **Update** | Runs `install.sh --update` which syncs code, rebuilds images, and updates system configs. |

**Example:**
```bash
# Trigger an update (content is the target branch)
echo "main" > ~/BirdNET-PiPy/data/flags/update-requested
```

### Update Channels

BirdNET-PiPy supports two update channels, configurable in Settings:

| Channel | Branch | Description |
|---------|--------|-------------|
| **Release** | `main` | Stable releases (default) |
| **Latest** | `staging` | Newest features, may be less stable |

When you trigger an update, the system checks for updates from the configured channel's branch.

### Update Flow Details

When an update is triggered, `install.sh --update` performs:
1. Stops Docker containers
2. Fetches and syncs to the target branch (git fetch + checkout + reset)
3. Rebuilds Docker images
4. Updates system configs (PulseAudio, systemd service, sudoers)
5. Exits for systemd to restart the service

**Manual update (current branch):**
```bash
cd ~/BirdNET-PiPy && sudo ./install.sh --update
```

**Manual update (specific branch):**
```bash
cd ~/BirdNET-PiPy && sudo ./install.sh --update --branch staging
```

**Note:** For existing installations before this feature was added, run `sudo ./install.sh` once to update the sudoers configuration for automatic updates.

---

## External Media Storage

**Settings → Storage → Connected drives** lists USB drives and SSDs detected
by the Linux host, including model, capacity, filesystem and mount status.
The list is read-only: discovering a drive does not mount it, format it or
make it a media storage location. It labels whether each drive is eligible
for preparation. System/boot/swap drives, read-only drives, and drives holding
BirdNET's application, database or settings are excluded. If the protected
storage or drive identity cannot be confirmed, it shows **Eligibility unknown**.

Protected storage is identified from the running API container's mount mappings
and the host filesystem identities, including separate database/settings mounts.
Only mount metadata is inspected; container environment variables are not read.
The label describes the current inventory and does not authorize formatting.
Eligible drives have a **Format…** confirmation showing the drive, erase warning
and ext4 as the new format. Type the exact drive name, then choose **Erase and
format**. This requires password protection and a signed-in owner.

The installed root-owned helper rechecks live identity, eligibility, all BirdNET
bind/volume filesystems, the configured media location and Docker storage before
writing. It refuses protected drives, unmounts the selected unused drive, creates
one GPT partition and formats it as ext4 labelled `BIRDSTORE`. It verifies the
filesystem, mounts it and grants the service user write access before reporting
completion. Busy drives fail without forced unmounts. Recording continues and no
application restart is needed. The dropdown refreshes after mounting; selecting
the new location and moving existing media remain separate choices.

`install.sh` installs the helper and its pure eligibility rules into
`/usr/local/libexec/birdnet-pipy`, owned by root, with fixed installation metadata
in `/etc/birdnet-pipy/storage-format.json`. The installer registers
`birdnet-storage-format.path`, which waits for a filesystem event on
`data/flags/storage-format-request.json`. Only the confirmed formatting action
creates this file. The event starts `birdnet-storage-format.service`, a root-owned
one-shot job that runs the fixed helper without arguments and exits afterward.
There is no periodic formatter launch or heartbeat. Progress is published to
`data/flags/storage-format-status.json` and shown in the existing Settings banner.
A root-owned journal in `/var/lib/birdnet-pipy` prevents replay after interruption.
API writes, including restarts and media transfers, are blocked while a request
is pending.

The installer writes `data/flags/storage-format-available` once after enabling
the watcher. The API reads this installation capability separately from job
progress, so availability and completed results do not expire when idle.
Uninstall disables the watcher and removes the capability marker. Opening the
confirmation dialog or its dry-run preview never starts the helper.

The service checks host integration before creating containers. This covers the
first upgrade from an older installer, whose already-loaded shell functions do
not know about the new helpers. If setup is missing or outdated, the service runs
`install.sh --update --branch <current-branch> --configure-host` using the existing
update permission. This internal mode runs the same `setup_sudoers` stage as a
normal install/update, including helper installation and mount preparation. It
does not fetch code, download images, build images or format drives. Current
installations skip it. Setup failures are logged and recording startup continues;
formatting remains unavailable. Starting Compose alone bypasses this host service.

The root-owned `storage_mounts.py` helper mounts prepared filesystems by UUID below
`/var/lib/birdnet-pipy/media`. A UUID registry in
`/var/lib/birdnet-pipy/media-mounts.json` records only drives prepared through this
flow. `birdnet-media-mounts.service` restores connected drives before Docker starts;
a missing drive is logged and startup continues. This dedicated parent is a shared
bind mount, exposed to containers at `/managed-media` with host-to-container
propagation (`rslave`). New mounts become visible without restarting recording.
An empty parent folder is never offered as media storage. The installer prepares
this parent and records `BIRDNET_MANAGED_MEDIA_PATH` and
`BIRDNET_MANAGED_MEDIA_PROPAGATION=rslave` in `.env` before creating containers.
Existing installations must use the updated Compose bindings before formatting
is enabled. Without the host installation, Compose uses an empty local folder
with private propagation, leaving managed mounting unavailable.

The existing `birdnet-pipy` host service refreshes this inventory every
15 seconds using `lsblk`. The app receives a metadata snapshot through its
existing flags directory; it gets no block-device access or additional
privileges. The list refreshes while expanded. If the host service is not
running, information becomes unavailable rather than showing an old list as
current. This discovery is for Linux service-managed installations; starting
Docker Compose alone or using the Home Assistant add-on does not run the
host collector.


BirdNET-PiPy can store recordings, extracted clips, and spectrograms in one
explicitly configured host directory. The database and application settings
remain in `./data`.

Use **ext4** for an external drive on the Raspberry Pi. The current media
writer requires hard links to publish completed clips safely; **FAT32 and
exFAT do not support this and are not suitable**. Other filesystems have not
been validated for this feature. The drive must be mounted read/write and
writable by the BirdNET-PiPy service user. Formatting through Settings mounts
the drive but does not select it for media storage.

See the [filesystem feature comparison](https://learn.microsoft.com/en-us/windows/win32/fileio/filesystem-functionality-comparison)
for FAT32/exFAT hard-link limitations.

1. Mount the drive on the host and create a directory that the BirdNET-PiPy
   service user can write to:

   ```bash
   sudo mkdir -p /mnt/birdnet-media
   sudo chown "$(id -u):$(id -g)" /mnt/birdnet-media
   ```

2. Add the host directory to `~/BirdNET-PiPy/.env`:

   ```bash
   BIRDNET_MEDIA_PATH=/mnt/birdnet-media
   ```

   To choose between several drives in the Settings UI, set this to their
   common parent instead. Only direct child mount points are offered as drives:

   ```bash
   BIRDNET_MEDIA_PATH=/media/birdnet
   ```

3. Restart the service, then select the drive under **Settings → Storage →
   Media storage**. Choose **SD card / internal storage** to switch back:

   ```bash
   sudo systemctl restart birdnet-pipy
   ```

Changing the location leaves existing media in place by default. Select
**Move existing media to new location** before saving to move recordings,
clips and spectrograms from the available storage locations. Recording,
analysis and cleanup pause during the move, then resume automatically. The
existing Settings progress banner shows the stage, files and bytes copied;
it also restores the progress display if the page is refreshed.

The move checks free space and verifies copies before saving the new location
and removing originals. The database and settings file stay in `./data`.

Space-based automatic cleanup removes media only from the filesystem that
needs space. Media on other drives and the existing per-species protections
are preserved. Age-based retention and media-budget settings keep their
existing behavior.

A media move alone does not require a container restart. Other saved changes
that need one continue through the normal restart flow.

Media is written below a `BirdNET-PiPy/` subdirectory on that target. If the
directory is absent or not writable, new media falls back to internal storage;
existing internal files remain readable. Manually configured drives should use a
stable mount in `/etc/fstab`. Drives prepared through Settings use the UUID registry
and boot mount service instead.

Only `BIRDNET_MEDIA_PATH` and the dedicated managed-media folder are exposed to
the containers. The application does not scan the host's full `/media` or `/mnt` trees.

---

## Troubleshooting

### No Audio Being Recorded

```bash
# Verify PulseAudio is running on host
pactl info

# List available audio sources
pactl list sources short
```

### Live Stream Not Working

```bash
# Check if Icecast is receiving audio
curl -s http://localhost:8888/status-json.xsl | grep -o '"listeners":[0-9]*'

# Test stream directly
curl http://localhost:8888/stream.mp3 --max-time 3 -o /dev/null && echo "Stream OK"
```

**Icecast Web Interface:** http://localhost:8888/status.xsl

---

## Icecast Configuration

### Change Stream Bitrate

Set environment variable before starting containers:
```bash
export STREAM_BITRATE=192k  # Default is 128k
docker compose up -d
```

### Change Icecast Passwords

By default, a **random 16-character password** is generated each time the Icecast container starts. This is secure but means the password changes on restart.

To set a **persistent password**, set the environment variable:
```bash
export ICECAST_PASSWORD=your_secure_password
docker compose up -d
```

**Note:** There is no static Icecast config: the startup script generates a secure one at runtime.
