#!/usr/bin/python3 -I
"""Root-owned, no-argument host formatter. Never run from the source checkout.

The installer copies this and storage_devices.py into a root-owned directory.
Requests contain drive identity and confirmation only, never commands/options.
"""
import fcntl
import json
import os
import stat
import sys
import time
from pathlib import Path

# -I excludes the script directory too; only this root-owned installation is trusted.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from storage_devices import _nodes, describe_devices  # noqa: E402
from storage_mounts import MEDIA_ROOT, atomic_json, mount_new_drive, run  # noqa: E402

CONFIG = Path('/etc/birdnet-pipy/storage-format.json')
JOURNAL = Path('/var/lib/birdnet-pipy/storage-format.json')
COLUMNS = 'NAME,PATH,TYPE,SIZE,MODEL,TRAN,ROTA,RO,FSTYPE,LABEL,MOUNTPOINTS,MAJ:MIN,SERIAL,WWN'


def read_settings(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise RuntimeError('Cannot read BirdNET settings safely.')
        return json.load(stream)


def container_path(path, mounts):
    matches = [mount for mount in mounts if path == mount['Destination']
               or path.startswith(mount['Destination'].rstrip('/') + '/')]
    if not matches:
        raise RuntimeError('Cannot map BirdNET storage to the host. No drive changes made.')
    mount = max(matches, key=lambda m: len(m['Destination']))
    return os.path.realpath(mount['Source'] + path[len(mount['Destination']):])


def live_inventory(project, command=run, settings_reader=read_settings):
    """Protect every app bind/volume, Docker storage and the host system mounts."""
    inventory = json.loads(command(['lsblk', '--json', '--bytes', '--output', COLUMNS]))['blockdevices']
    ids = command(['docker', 'ps', '--quiet', '--filter', 'label=com.docker.compose.service=api']).split()
    containers = []
    for container_id in ids:
        report = json.loads(command(['docker', 'inspect', '--format',
            '{"mounts":{{json .Mounts}},"labels":{{json .Config.Labels}}}', container_id]))
        if report['labels'].get('com.docker.compose.project.working_dir') == project:
            containers.append(report)
    if len(containers) != 1:
        raise RuntimeError('Cannot identify the running BirdNET installation. No drive changes made.')
    paths = [project, command(['docker', 'info', '--format', '{{.DockerRootDir}}']).strip()]
    mounts = containers[0]['mounts']
    managed = next((mount for mount in mounts if mount['Destination'] == '/managed-media'), None)
    if (not managed or managed['Source'] != str(MEDIA_ROOT)
            or managed.get('Propagation') not in ('rslave', 'rshared')):
        raise RuntimeError('Update the host installation and restart services before formatting. Managed media is not connected.')
    paths.extend(mount['Source'] for mount in mounts)
    settings = settings_reader(container_path('/app/data/config/user_settings.json', mounts))
    media_target = settings.get('storage', {}).get('media_target', 'internal')
    if media_target != 'internal':
        if not isinstance(media_target, str) or not any(media_target == root or media_target.startswith(root + '/')
                for root in ('/external-media', '/managed-media')):
            raise RuntimeError('Cannot verify the configured media location. No drive changes made.')
        # /external-media can expose a parent containing several mounted drives.
        # Checking just the parent misses the currently selected child drive.
        paths.append(container_path(media_target, mounts))
    protected = set()
    for path in paths:
        report = json.loads(command(['findmnt', '--json', '--target', path, '--output', 'MAJ:MIN']))
        identities = [entry.get('maj:min') for entry in report['filesystems']]
        if not identities or not all(identities):
            raise RuntimeError('Cannot identify protected storage. No drive changes made.')
        protected.update(identities)
    return inventory, {role: protected for role in ('application', 'database', 'settings')}


def validate(request, inventory, protected):
    drive = next((d for d in describe_devices(inventory, protected)
                  if d['path'] == request.get('path') and d['device_id'] == request.get('device_id')), None)
    if not drive or request.get('confirmation') != drive['name']:
        raise RuntimeError('Drive information changed. Refresh the drive list and confirm again.')
    if drive['preparation_eligible'] is not True:
        raise RuntimeError('This drive contains system or BirdNET data, is read-only, or cannot be verified.')
    disk = next(d for d in inventory if d.get('path') == drive['path'])
    if any(node.get('type') not in ('disk', 'part') for node in _nodes(disk)):
        raise RuntimeError('This drive uses managed storage. Disconnect it from that storage before formatting.')
    return disk


def format_drive(request, project, progress, command=run, discover=live_inventory, check_device=None, *, mount_drive):
    """Injected command/discovery functions let tests exercise the real flow without drives."""
    inventory, protected = discover(project, command)
    disk = validate(request, inventory, protected)
    path = disk['path']
    if check_device is None:
        info = os.stat(path)
        if not stat.S_ISBLK(info.st_mode) or os.path.realpath(path) != path:
            raise RuntimeError('The selected path is not a physical block device.')
        if f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}' != disk['maj:min']:
            raise RuntimeError('The selected device changed. Confirm it again.')
    else:
        check_device(path)
    progress('unmounting', 'Unmounting selected drive…')
    mounts = {mount for node in _nodes(disk) for mount in (node.get('mountpoints') or []) if mount}
    for mount in sorted(mounts, key=len, reverse=True):
        command(['umount', '--', mount])
    # Fresh authorization after unmounting, immediately before writing.
    inventory, protected = discover(project, command)
    disk = validate(request, inventory, protected)
    if any(mount for node in _nodes(disk) for mount in (node.get('mountpoints') or [])):
        raise RuntimeError('The drive is still mounted. No formatting was started.')
    progress('partitioning', 'Creating a new partition table…')
    command(['sfdisk', '--lock=yes', '--wipe', 'always', '--wipe-partitions', 'always', path],
            input='label: gpt\n, , L\n')
    command(['udevadm', 'settle', '--timeout=30'])
    inventory, protected = discover(project, command)
    disk = validate(request, inventory, protected)
    partitions = [node for node in disk.get('children', []) if node.get('type') == 'part']
    if len(partitions) != 1 or not partitions[0].get('path'):
        raise RuntimeError('The new partition could not be identified. Reconnect the drive and try again.')
    partition = partitions[0]['path']
    progress('formatting', 'Creating ext4 filesystem…')
    # No force flag: mke2fs must refuse a mounted/in-use partition.
    command(['mkfs.ext4', '-L', 'BIRDSTORE', partition])
    inventory, protected = discover(project, command)
    disk = validate(request, inventory, protected)
    if (not any(p.get('path') == partition for p in disk.get('children', []))
            or command(['blkid', '--probe', '--match-tag', 'TYPE', '--output', 'value', partition]).strip() != 'ext4'):
        raise RuntimeError('Formatting finished but the ext4 filesystem could not be verified.')
    progress('mounting', 'Mounting formatted drive…')
    try:
        mount_drive(partition)
    except (RuntimeError, OSError) as error:
        raise RuntimeError(f'Drive formatted as ext4, but mounting setup failed: {error}') from error
    progress('complete', 'Drive formatted and mounted. Select it under Media storage. No restart needed.')


def serve(config):
    flags = Path(config['flags'])
    if flags.is_symlink() or flags.stat().st_uid != config['uid']:
        raise RuntimeError('Storage flags directory must belong to the installation user.')
    status_path = flags / 'storage-format-status.json'
    request_path = flags / 'storage-format-request.json'
    previous = json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {'state': 'idle'}

    def progress(state, message, job_id=None):
        payload = {'state': state, 'message': message, 'id': job_id, 'updated_at': time.time()}
        if state == 'complete':
            try:
                inventory, protected = live_inventory(config['project'])
                payload['storage_devices'] = {
                    'state': 'available', 'updated_at': time.time(),
                    'devices': describe_devices(inventory, protected),
                }
            except Exception as error:
                # Formatting succeeded even if refreshing display metadata fails.
                print(f'Could not refresh connected-drive information: {error}', flush=True)
        atomic_json(JOURNAL, payload)
        atomic_json(status_path, payload)
        print(f'Storage formatting: {message}', flush=True)

    try:
        fd = os.open(request_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return
    try:
        with os.fdopen(fd) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise RuntimeError('Invalid formatting request file.')
            request = json.loads(stream.read(8192))
        job_id = request.get('id')
        if not isinstance(job_id, str) or not job_id:
            raise RuntimeError('Invalid formatting request.')
        if previous.get('id') == job_id:
            # Never replay a destructive job after a crash or service restart.
            state = previous['state'] if previous['state'] in ('complete', 'failed') else 'failed'
            progress(state, previous['message'] if state == previous['state'] else
                     'Formatting was interrupted. Check the drive before retrying.', job_id)
            return
        if not 0 <= time.time() - request.get('created_at', 0) <= 120:
            raise RuntimeError('Formatting request expired. Confirm the drive again.')
        progress('checking', 'Checking selected drive…', job_id)
        format_drive(request, config['project'], lambda state, message: progress(state, message, job_id),
                     mount_drive=lambda partition: mount_new_drive(partition, config['uid'], config['gid']))
    except Exception as error:
        progress('failed', str(error), locals().get('job_id'))
    finally:
        request_path.unlink(missing_ok=True)


def main():
    if len(sys.argv) != 1 or os.geteuid() != 0:
        raise SystemExit('Run the installed formatter as root without arguments.')
    config = json.loads(CONFIG.read_text())
    JOURNAL.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(JOURNAL.parent / 'storage-format.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        serve(config)


if __name__ == '__main__':
    main()
