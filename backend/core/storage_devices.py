"""Pure drive identity and eligibility rules, also installed with the host formatter."""
import hashlib
import json

_SYSTEM_MOUNTS = {'/', '/boot', '/boot/firmware', '/boot/efi', '[SWAP]'}
_PROTECTED_ROLES = ('application', 'database', 'settings')


def _nodes(device):
    yield device
    for child in device.get('children', []):
        yield from _nodes(child)


def preparation_eligibility(nodes, protected_filesystems):
    """Assess the current inventory only; this does not authorize an action."""
    mounts = {mount for node in nodes for mount in (node.get('mountpoints') or []) if mount}
    identities = {node['maj:min'] for node in nodes if node.get('maj:min')}
    protected_filesystems = protected_filesystems or {}
    roles = [role for role in _PROTECTED_ROLES
             if identities.intersection(protected_filesystems.get(role, set()))]
    if _SYSTEM_MOUNTS.intersection(mounts):
        return False, 'System drive'
    if roles:
        return False, 'Contains BirdNET ' + ' and '.join(roles)
    if any(node.get('ro') in (True, 1, '1') for node in nodes):
        return False, 'Read-only drive'
    if int(nodes[0].get('size') or 0) <= 0:
        return False, 'No media detected'
    if (not all(node.get('maj:min') for node in nodes)
            or not all(protected_filesystems.get(role) for role in _PROTECTED_ROLES)):
        return None, 'Eligibility unknown'
    return True, 'Eligible for preparation'


def _protected_filesystems(snapshot):
    result = {}
    for role in _PROTECTED_ROLES:
        reports = snapshot.get('protected', {}).get(role, [])
        if not reports or any(not report or not report.get('filesystems') for report in reports):
            continue
        identities = [entry.get('maj:min') for report in reports for entry in report['filesystems']]
        if all(identities):
            result[role] = set(identities)
    return result


def describe_devices(blockdevices, protected_filesystems=None):
    """Select USB disks and NVMe/SATA/SAS SSDs, retaining mount metadata."""
    drives = []
    for disk in blockdevices:
        if disk.get('type') != 'disk':
            continue
        bus = (disk.get('tran') or '').lower()
        ssd = bus == 'nvme' or (bus in ('sata', 'sas') and disk.get('rota') in (False, 0, '0'))
        if bus != 'usb' and not ssd:
            continue
        nodes = list(_nodes(disk))
        mounts = sorted({mount for node in nodes for mount in (node.get('mountpoints') or []) if mount})
        filesystems = sorted({node['fstype'] for node in nodes if node.get('fstype')})
        path = disk.get('path') or '/dev/' + disk['name']
        eligible, eligibility_reason = preparation_eligibility(nodes, protected_filesystems)
        drives.append({
            'device_id': hashlib.sha256(json.dumps([
                path, disk.get('maj:min'), disk.get('size'), disk.get('model'),
                disk.get('serial'), disk.get('wwn'),
            ]).encode()).hexdigest(),
            'path': path,
            'name': (disk.get('model') or disk.get('label') or disk['name']).strip(),
            'size_bytes': int(disk.get('size') or 0),
            'connection': bus.upper(),
            'filesystems': filesystems,
            'mount_points': mounts,
            'mounted': bool(mounts),
            'system_drive': bool(_SYSTEM_MOUNTS.intersection(mounts)),
            'read_only': disk.get('ro') in (True, 1, '1'),
            'preparation_eligible': eligible,
            'eligibility_reason': eligibility_reason,
        })
    return sorted(drives, key=lambda drive: drive['path'])
