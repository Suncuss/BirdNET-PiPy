#!/bin/bash
# Move BirdNET-PiPy's data/ folder (database, settings, recordings) onto an
# external USB/SSD drive.
#
#   sudo scripts/data-drive.sh list                    # show candidate drives
#   sudo scripts/data-drive.sh setup /dev/sdX          # format (asks), mount, move data
#   sudo scripts/data-drive.sh setup --mounted /path   # use a drive you already mount
#   sudo scripts/data-drive.sh move-back               # move data back to this disk
#   scripts/data-drive.sh status                       # where data lives right now
#
# Layout: data/ becomes a symlink to <drive>/birdnet, and .env records the
# drive's mount point (BIRDNET_DATA_DRIVE). `setup /dev/sdX` mounts the drive by
# UUID at /mnt/birdnet-data through an fstab entry bound to the device, so a
# drive that drops out and returns is remounted. A marker file on the drive
# lets the service refuse to start on an empty mount point.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$PROJECT_ROOT/data"
MOUNT_POINT=/mnt/birdnet-data
MARKER=.birdnet-data-volume
COPYING=.birdnet-copy-in-progress   # lets an interrupted setup resume
LABEL=BIRDNET-DATA
SERVICE=${BIRDNET_SERVICE:-birdnet-pipy.service}

die() { echo "Error: $*" >&2; exit 1; }
info() { echo "==> $*"; }

need_root() { [ "$(id -u)" -eq 0 ] || die "run with sudo"; }

# Checked before anything is changed. rsync and sfdisk are missing from
# some minimal Debian images.
need_tools() {
    local tool missing=""
    for tool in "$@"; do
        command -v "$tool" >/dev/null || missing="$missing $tool"
    done
    [ -z "$missing" ] || die "missing:$missing. Install them with: sudo apt install rsync fdisk e2fsprogs"
}

# The copy must fit; files from an interrupted earlier run are reused.
check_space() {
    local source=$1 dest=$2 need have=0 free
    need=$(du -sb "$source" | cut -f1)
    [ ! -d "$dest" ] || have=$(du -sb "$dest" | cut -f1)
    free=$(df -B1 --output=avail "$(dirname "$dest")" | tail -1)
    [ $((need - have)) -lt "$free" ] \
        || die "the data needs $(numfmt --to=iec $((need - have))) more, only $(numfmt --to=iec "$free") free at $(dirname "$dest")"
}

warn() { echo "Warning: $*" >&2; }

owner() { stat -c %U "$PROJECT_ROOT"; }

env_drive() { sed -n 's/^BIRDNET_DATA_DRIVE=//p' "$PROJECT_ROOT/.env" 2>/dev/null | tail -1; }

# Only stop/start the systemd service when it runs this checkout.
service_is_ours() {
    [ "$(systemctl show -p WorkingDirectory --value "$SERVICE" 2>/dev/null)" = "$PROJECT_ROOT" ]
}

containers_running() {
    [ -n "$(cd "$PROJECT_ROOT" && docker compose ps -q --status running 2>/dev/null)" ]
}

STATION_WAS_RUNNING=false

# First pass, with the station still running: recordings it deletes mid-copy
# make rsync exit 24 ("vanished"), which is harmless; the final pass is exact.
copy_live() {
    local rc=0
    rsync -a "$@" || rc=$?
    [ "$rc" -eq 0 ] || [ "$rc" -eq 24 ] || die "copy failed (rsync exit $rc); run the command again to resume"
}

# Called after the first (live) copy pass: the final pass needs a still station.
stop_station() {
    if service_is_ours && systemctl is-active --quiet "$SERVICE"; then
        info "Stopping BirdNET-PiPy for the final copy..."
        systemctl stop "$SERVICE"
        STATION_WAS_RUNNING=true
    fi
    ! containers_running || die "BirdNET-PiPy containers are still running; stop them (sudo systemctl stop $SERVICE) and run this again"
}

start_station() {
    if [ "$STATION_WAS_RUNNING" = true ]; then
        info "Starting BirdNET-PiPy..."
        systemctl start "$SERVICE"
    fi
}

# Whole disks that are not the system disk (nothing mounted at / or /boot*).
list_drives() {
    lsblk -dno PATH,SIZE,TRAN,MODEL | while read -r path size tran model; do
        [ "$tran" = usb ] || [ "$tran" = nvme ] || [ "$tran" = sata ] || continue
        if lsblk -nro MOUNTPOINTS "$path" | grep -qE '^/$|^/boot'; then
            continue
        fi
        echo "$path  $size  $tran  ${model:-unknown}"
    done
}

check_candidate() {
    local disk=$1
    [ -b "$disk" ] && [ "$(lsblk -dno TYPE "$disk")" = disk ] \
        || die "$disk is not a whole disk (use e.g. /dev/sda, not /dev/sda1)"
    list_drives | grep -q "^$disk " || die "$disk is the system disk or not a USB/NVMe/SATA drive"
    local mounts
    mounts=$(lsblk -nro MOUNTPOINTS "$disk" | grep . | grep -vx "$MOUNT_POINT" || true)
    [ -z "$mounts" ] || die "$disk is mounted ($(echo "$mounts" | tr '\n' ' ')). Unmount it first."
}

format_drive() {
    local disk=$1 model
    model=$(lsblk -dno MODEL "$disk" | xargs)
    echo
    lsblk -o NAME,SIZE,FSTYPE,LABEL,MODEL "$disk"
    echo
    echo "ALL DATA ON $disk ($model) WILL BE ERASED."
    read -r -p "Type the drive name ($model) to format it as ext4: " answer
    [ -n "$model" ] && [ "$answer" = "$model" ] || die "name did not match; nothing changed"
    wipefs -aq "$disk"
    printf 'label: gpt\n, , L\n' | sfdisk -q --wipe always "$disk"
    udevadm settle
    local part
    part=$(lsblk -nrpo PATH,TYPE "$disk" | awk '$2 == "part" {print $1; exit}')
    mkfs.ext4 -q -L "$LABEL" "$part"
    udevadm settle
}

# The single ext4 partition on the disk, formatting it first if needed.
data_partition() {
    local disk=$1 parts
    parts=$(lsblk -nrpo PATH,TYPE,FSTYPE "$disk" | awk '$2 == "part"')
    if [ "$(echo "$parts" | grep -c .)" -eq 1 ] && echo "$parts" | grep -q ' ext4$'; then
        echo "$parts" | awk '{print $1}'
        return
    fi
    echo "$disk needs to be formatted as ext4 (exFAT/NTFS/FAT cannot hold the database or recordings)." >&2
    format_drive "$disk" >&2
    lsblk -nrpo PATH,TYPE "$disk" | awk '$2 == "part" {print $1; exit}'
}

add_fstab_entry() {
    local uuid=$1 unit
    if mountpoint -q "$MOUNT_POINT" && [ "$(findmnt -no UUID -M "$MOUNT_POINT")" != "$uuid" ]; then
        die "another drive ($(findmnt -no SOURCE -M "$MOUNT_POINT")) is mounted at $MOUNT_POINT; unmount it first"
    fi
    unit=$(systemd-escape -p --suffix=device "/dev/disk/by-uuid/$uuid")
    cp -p /etc/fstab "/etc/fstab.birdnet-backup"
    sed -i "\|[[:space:]]${MOUNT_POINT}[[:space:]]|d" /etc/fstab
    # nofail: boot never hangs on a missing drive. wanted-by the device:
    # systemd remounts the drive when it is reconnected.
    printf 'UUID=%s %s ext4 defaults,noatime,nofail,x-systemd.device-timeout=30s,x-systemd.wanted-by=%s 0 2\n' \
        "$uuid" "$MOUNT_POINT" "$unit" >> /etc/fstab
    systemctl daemon-reload
    mkdir -p "$MOUNT_POINT"
    mountpoint -q "$MOUNT_POINT" || mount "$MOUNT_POINT"
    [ "$(findmnt -no UUID -M "$MOUNT_POINT")" = "$uuid" ] || die "$MOUNT_POINT did not mount the expected drive"
}

set_env() {
    local env="$PROJECT_ROOT/.env"
    touch "$env"
    sed -i '/^BIRDNET_DATA_DRIVE=/d' "$env"
    [ -z "${1:-}" ] || echo "BIRDNET_DATA_DRIVE=$1" >> "$env"
    chown "$(owner):" "$env"
}

# Hard links (media publishing), symlinks and Linux ownership all work here.
supports_links() {
    local probe ok=1
    probe=$(mktemp -d "$1/.birdnet-probe.XXXXXX" 2>/dev/null) || return 1
    if touch "$probe/f" && ln "$probe/f" "$probe/h" && ln -s f "$probe/s" \
        && chown "$(owner):" "$probe/f" && [ "$(stat -c %U "$probe/f")" = "$(owner)" ]; then
        ok=0
    fi 2>/dev/null
    rm -rf "$probe"
    return $ok
}

# A drive the user already mounts: it must be a real, fstab-managed mount of
# a Linux filesystem. Their fstab entry is theirs; we only point out gaps.
check_mounted_dir() {
    local dir=$1 opts
    mountpoint -q "$dir" || die "$dir is not a mount point; mount the drive there first"
    [ "$(stat -c %d "$dir")" != "$(stat -c %d /)" ] || die "$dir is on the system disk"
    supports_links "$dir" \
        || die "$dir ($(findmnt -no FSTYPE -M "$dir")) cannot hold BirdNET data (it needs hard links and Linux permissions); use ext4"
    opts=$(findmnt -s -no OPTIONS "$dir" 2>/dev/null) \
        || die "$dir is not in /etc/fstab, so it would not be mounted after a reboot. Add an fstab entry, or let this script manage the drive: sudo $0 setup /dev/sdX"
    case ",$opts," in
        *,nofail,*) ;;
        *) warn "the fstab entry for $dir has no 'nofail': if the drive is missing, the Pi stops booting" ;;
    esac
    case ",$opts" in
        *,x-systemd.wanted-by=*|*,x-systemd.automount*) ;;
        *) warn "the fstab entry for $dir has no x-systemd.wanted-by=<device unit>: if the drive disconnects, BirdNET-PiPy stays stopped until it is mounted again (sudo mount $dir) or the Pi reboots" ;;
    esac
}

# Copy data/ to <drive>/birdnet and point data/ at it.
migrate_to() {
    local drive=$1 target="$1/birdnet" backup
    if [ -d "$target" ] && [ -n "$(ls -A "$target")" ] && [ ! -f "$target/$COPYING" ]; then
        die "$target already has files (an earlier BirdNET-PiPy copy?). Rename or delete it, then run setup again."
    fi
    check_space "$DATA" "$target"

    if ! service_is_ours && containers_running; then
        die "BirdNET-PiPy is running outside its service; stop it first"
    fi
    install -d -o "$(owner)" -g "$(owner)" "$target"
    touch "$target/$COPYING"
    info "Copying data while the station keeps running (can take a while)..."
    copy_live --exclude="/$COPYING" "$DATA/" "$target/"
    sync -f "$target"   # flush now, not while the station is stopped
    stop_station
    rsync -a --delete --exclude="/$COPYING" "$DATA/" "$target/"
    touch "$target/$MARKER"
    chown "$(owner):" "$target/$MARKER"
    rm -f "$target/$COPYING"

    backup="$PROJECT_ROOT/data.internal-$(date +%Y%m%d-%H%M%S)"
    mv "$DATA" "$backup"
    ln -s "$target" "$DATA"
    chown -h "$(owner):" "$DATA"
    set_env "$drive"
    start_station
    echo
    echo "Done. Data now lives on the drive ($target)."
    echo "The original copy is kept at $backup."
    echo "Once the station runs well from the drive, free the space with:"
    echo "  sudo rm -rf $backup"
}

check_data_local() {
    [ ! -L "$DATA" ] || die "data/ is already on an external drive ($(readlink "$DATA")). To change drives, run 'move-back' first."
    [ -d "$DATA" ] || die "no data/ folder at $DATA"
}

setup() {
    need_root
    need_tools rsync sfdisk wipefs mkfs.ext4
    local disk=${1:-}
    [ -n "$disk" ] || die "usage: sudo $0 setup /dev/sdX | setup --mounted /path   (see: sudo $0 list)"
    check_data_local

    if [ "$disk" = --mounted ]; then
        [ -n "${2:-}" ] || die "usage: sudo $0 setup --mounted /path/where/the/drive/is/mounted"
        local dir
        dir=$(realpath -e "$2") || die "$2 does not exist"
        check_mounted_dir "$dir"
        migrate_to "$dir"
        return
    fi

    check_candidate "$disk"
    local part uuid
    part=$(data_partition "$disk")
    uuid=$(blkid -s UUID -o value "$part")
    [ -n "$uuid" ] || die "could not read the filesystem UUID of $part"
    info "Mounting $part at $MOUNT_POINT (UUID $uuid)"
    add_fstab_entry "$uuid"
    migrate_to "$MOUNT_POINT"
}

# Copy the data back onto the internal disk. The drive keeps its copy.
move_back() {
    need_root
    need_tools rsync
    [ -L "$DATA" ] || die "data/ is already on the internal disk"
    local drive source dest="$PROJECT_ROOT/data.moving"
    drive=$(env_drive)
    source=$(readlink -f "$DATA")
    [ -n "$drive" ] && mountpoint -q "$drive" && [ -f "$DATA/$MARKER" ] \
        || die "the data drive is not mounted; reconnect it and try again"
    check_space "$source" "$dest"

    if ! service_is_ours && containers_running; then
        die "BirdNET-PiPy is running outside its service; stop it first"
    fi
    # An existing $dest is an interrupted earlier run: rsync resumes it.
    info "Copying data while the station keeps running (can take a while)..."
    copy_live --exclude="/$MARKER" "$source/" "$dest/"
    sync -f "$dest"
    stop_station
    rsync -a --delete --exclude="/$MARKER" "$source/" "$dest/"
    rm "$DATA"
    mv "$dest" "$DATA"
    set_env ""

    # Release a drive this script mounted; a mount the user set up is theirs.
    if [ "$drive" = "$MOUNT_POINT" ]; then
        cp -p /etc/fstab /etc/fstab.birdnet-backup
        sed -i "\|[[:space:]]${MOUNT_POINT}[[:space:]]|d" /etc/fstab
        systemctl daemon-reload
        if umount "$MOUNT_POINT"; then rmdir "$MOUNT_POINT"; else warn "could not unmount $MOUNT_POINT"; fi
    fi
    start_station
    echo
    echo "Done. Data is back on the internal disk ($DATA)."
    echo "The drive still holds the old copy in its birdnet/ folder; delete it, or rename it before setting this drive up again."
    local old
    for old in "$PROJECT_ROOT"/data.internal-*; do
        [ -e "$old" ] && echo "$old is an older backup from before the drive was set up; it can be deleted."
    done
    return 0
}

status() {
    if [ -L "$DATA" ]; then
        local drive
        drive=$(env_drive)
        echo "data/ -> $(readlink "$DATA")"
        if [ -n "$drive" ] && mountpoint -q "$drive" && [ -f "$DATA/$MARKER" ]; then
            df -h "$drive" | tail -1
        else
            echo "DRIVE NOT MOUNTED: BirdNET-PiPy waits until it is reconnected."
        fi
    else
        echo "data/ is on the internal disk"
        df -h "$DATA" | tail -1
    fi
}

case "${1:-}" in
    list) need_root; list_drives ;;
    setup) shift; setup "$@" ;;
    move-back) move_back ;;
    status) status ;;
    *) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
