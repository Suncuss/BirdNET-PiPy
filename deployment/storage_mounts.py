#!/usr/bin/python3 -I
"""Root-owned mounts for drives formatted by BirdNET. No arbitrary mount requests."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG = Path('/etc/birdnet-pipy/storage-format.json')
MEDIA_ROOT = Path('/var/lib/birdnet-pipy/media')
REGISTRY = Path('/var/lib/birdnet-pipy/media-mounts.json')
MOUNTINFO = Path('/proc/self/mountinfo')
_UUID = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}


def run(args, *, input=None):
    result = subprocess.run(args, input=input, text=True, capture_output=True,
                            timeout=600 if args[0] in ('sfdisk', 'mkfs.ext4') else 30, check=False, env=ENV, cwd='/')
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed: {(result.stderr or result.stdout)[-600:].strip()}')
    return result.stdout


def atomic_json(path, payload):
    fd, temporary = tempfile.mkstemp(prefix='.storage-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def is_mountpoint(path):
    """Read kernel mount points, including bind mounts on the same filesystem.

    os.path.ismount cannot reliably detect those binds. Read failures propagate:
    an unreadable mount table is not evidence that a new mount is needed.
    """
    target = os.path.realpath(path)
    with MOUNTINFO.open(encoding='utf-8', errors='surrogateescape') as stream:
        for line in stream:
            fields = line.split()
            if len(fields) >= 5:
                mountpoint = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), fields[4])
                if mountpoint == target:
                    return True
    return False


def shares_parent_peer_group(path):
    """Detect a self-bind that still shares mount events with its parent."""
    target = os.path.realpath(path)
    group = None
    parent_group = None
    parent_length = -1
    with MOUNTINFO.open(encoding='utf-8', errors='surrogateescape') as stream:
        for line in stream:
            fields = line.split()
            if len(fields) < 7:
                continue
            mountpoint = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), fields[4])
            peer = next((field for field in fields[6:fields.index('-')] if field.startswith('shared:')), None)
            if mountpoint == target:
                group = peer
            elif target.startswith(mountpoint.rstrip('/') + '/') and len(mountpoint) >= parent_length:
                parent_length, parent_group = len(mountpoint), peer
    return group is not None and group == parent_group


def prepare_root(command=run):
    """Share only this dedicated mount tree, never the host's root mount."""
    MEDIA_ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
    if MEDIA_ROOT.is_symlink():
        raise RuntimeError('The managed media folder must not be a symbolic link.')
    if not is_mountpoint(MEDIA_ROOT):
        command(['mount', '--bind', str(MEDIA_ROOT), str(MEDIA_ROOT)])
    # A bind inherits its parent's shared peer group. Detach that relationship
    # before sharing with Docker, otherwise child mounts propagate back twice.
    if shares_parent_peer_group(MEDIA_ROOT):
        command(['mount', '--make-private', str(MEDIA_ROOT)])
    propagation = command(['findmnt', '--noheadings', '--raw', '--mountpoint', str(MEDIA_ROOT),
                           '--output', 'PROPAGATION']).strip()
    if 'shared' not in propagation.split(','):
        command(['mount', '--make-rshared', str(MEDIA_ROOT)])


def mount_uuid(uuid, uid, gid, command=run):
    if not isinstance(uuid, str) or not _UUID.fullmatch(uuid):
        raise RuntimeError('The formatted drive has no valid filesystem UUID.')
    target = MEDIA_ROOT / uuid
    target.mkdir(mode=0o755, exist_ok=True)
    if target.is_symlink():
        raise RuntimeError('The drive mount folder must not be a symbolic link.')
    if not is_mountpoint(target):
        command(['mount', '-t', 'ext4', '-o', 'nosuid,nodev', 'UUID=' + uuid, str(target)])
    # Pin the mounted directory before giving the service user write access.
    fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        actual = command(['findmnt', '--noheadings', '--raw', '--mountpoint', str(target),
                          '--output', 'UUID']).strip()
        if actual != uuid:
            raise RuntimeError('The mounted drive identity could not be verified.')
        os.fchown(fd, uid, gid)
        os.fchmod(fd, 0o755)
    finally:
        os.close(fd)
    print(f'Media drive mounted: {target}', flush=True)
    return '/managed-media/' + uuid


def mount_new_drive(partition, uid, gid, command=run):
    uuid = command(['blkid', '--probe', '--match-tag', 'UUID', '--output', 'value', partition]).strip()
    prepare_root(command)
    target = mount_uuid(uuid, uid, gid, command)
    known = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []
    if uuid not in known:
        atomic_json(REGISTRY, [*known, uuid])
    return target


def restore_mounts(uid, gid, command=run):
    prepare_root(command)
    known = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []
    for uuid in known:
        if not isinstance(uuid, str) or not _UUID.fullmatch(uuid):
            raise RuntimeError('Invalid saved media drive identity.')
        try:
            command(['blkid', '--uuid', uuid])
        except RuntimeError:
            print(f'Media drive not connected: {uuid}; continuing startup.', flush=True)
            continue
        try:
            mount_uuid(uuid, uid, gid, command)
        except (RuntimeError, OSError) as error:
            print(f'Could not remount media drive {uuid}: {error}; continuing startup.', flush=True)


def main():
    if len(sys.argv) != 1 or os.geteuid() != 0:
        raise SystemExit('Run the installed media mount helper as root without arguments.')
    config = json.loads(CONFIG.read_text())
    restore_mounts(config['uid'], config['gid'])


if __name__ == '__main__':
    main()
