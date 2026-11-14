"""Read-only host inventory parsing and freshness checks."""
import json
import os
import time


def test_usb_ssds_and_system_drive_are_identified_without_actions():
    from core.storage_discovery import describe_devices
    devices = describe_devices([
        {'name': 'sda', 'path': '/dev/sda', 'type': 'disk', 'tran': 'usb',
         'model': 'USB SSD', 'size': 500000000000, 'rota': False, 'ro': False,
         'children': [{'name': 'sda1', 'fstype': 'exfat', 'mountpoints': [None]}]},
        {'name': 'nvme0n1', 'type': 'disk', 'tran': 'nvme', 'model': 'Boot SSD',
         'size': 256000000000, 'children': [
             {'name': 'nvme0n1p2', 'fstype': 'ext4', 'mountpoints': ['/']}]},
        {'name': 'sdb', 'type': 'disk', 'tran': 'sata', 'rota': True},
        {'name': 'loop0', 'type': 'loop', 'rota': False},
    ])
    assert len(devices) == 2
    usb = next(d for d in devices if d['connection'] == 'USB')
    assert usb['name'] == 'USB SSD'
    assert usb['size_bytes'] == 500000000000
    assert usb['filesystems'] == ['exfat']
    assert not usb['mounted']
    system = next(d for d in devices if d['system_drive'])
    assert system['mounted'] and system['mount_points'] == ['/']


def test_snapshot_is_read_only_and_stale_inventory_is_not_presented_as_current(tmp_path, monkeypatch):
    import core.storage_discovery as discovery
    snapshot = tmp_path / 'storage-devices.json'
    raw = json.dumps({'blockdevices': [{'name': 'sda', 'type': 'disk', 'tran': 'usb',
                                      'model': 'USB', 'size': 1000}]})
    snapshot.write_text(raw)
    monkeypatch.setattr(discovery, 'SNAPSHOT_PATH', str(snapshot))
    assert discovery.get_storage_devices()['state'] == 'available'
    assert snapshot.read_text() == raw
    old = time.time() - discovery.MAX_AGE_SECONDS - 1
    os.utime(snapshot, (old, old))
    assert discovery.get_storage_devices()['state'] == 'unavailable'


def _usb_disk(identity='8:0', partition='8:1', mounts=None):
    return {'name': 'sda', 'type': 'disk', 'tran': 'usb', 'size': 500000000000,
            'maj:min': identity, 'children': [
                {'name': 'sda1', 'type': 'part', 'maj:min': partition,
                 'fstype': 'exfat', 'mountpoints': mounts or []}]}


def test_usb_boot_disk_is_not_eligible_even_when_connected_by_usb():
    from core.storage_discovery import describe_devices
    drive = describe_devices([_usb_disk(mounts=['/'])])[0]
    assert drive['preparation_eligible'] is False
    assert drive['eligibility_reason'] == 'System drive'


def test_drives_holding_application_database_or_settings_are_excluded():
    from core.storage_discovery import describe_devices
    for role in ('application', 'database', 'settings'):
        protected = {name: {'179:2'} for name in ('application', 'database', 'settings')}
        protected[role] = {'8:1'}
        drive = describe_devices([_usb_disk()], protected)[0]
        assert drive['preparation_eligible'] is False
        assert drive['eligibility_reason'] == 'Contains BirdNET ' + role


def test_unused_drive_is_eligible_only_with_complete_protected_storage_information():
    from core.storage_discovery import describe_devices
    protected = {name: {'179:2'} for name in ('application', 'database', 'settings')}
    ready = describe_devices([_usb_disk()], protected)[0]
    assert ready['preparation_eligible'] is True
    assert ready['eligibility_reason'] == 'Eligible for preparation'
    unknown = describe_devices([_usb_disk()])[0]
    assert unknown['preparation_eligible'] is None
    assert unknown['eligibility_reason'] == 'Eligibility unknown'


def test_host_filesystem_reports_are_used_for_eligibility(tmp_path, monkeypatch):
    import core.storage_discovery as discovery
    snapshot = tmp_path / 'devices.json'
    report = {'filesystems': [{'maj:min': '8:1'}]}
    snapshot.write_text(json.dumps({
        'inventory': {'blockdevices': [_usb_disk()]},
        'protected': {role: [report] for role in ('application', 'database', 'settings')},
    }))
    monkeypatch.setattr(discovery, 'SNAPSHOT_PATH', str(snapshot))
    result = discovery.get_storage_devices()
    assert result['state'] == 'available'
    assert result['devices'][0]['preparation_eligible'] is False
    assert 'database' in result['devices'][0]['eligibility_reason']
