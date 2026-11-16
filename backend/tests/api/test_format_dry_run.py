"""Formatting plans use synthetic snapshots and never invoke disk commands."""
import json
import os
import time
from unittest.mock import Mock

import pytest


@pytest.fixture
def synthetic_drive(api_client, tmp_path, monkeypatch):
    import core.storage_discovery as discovery
    snapshot = tmp_path / 'drives.json'
    payload = {
        'inventory': {'blockdevices': [{
            'name': 'sda', 'path': '/dev/sda', 'type': 'disk', 'tran': 'usb',
            'model': 'BIRDSTORE', 'size': 500000000000, 'maj:min': '8:0', 'serial': 'sample-A',
            'children': [{'name': 'sda1', 'type': 'part', 'maj:min': '8:1', 'fstype': 'exfat'}],
        }]},
        'protected': {role: [{'filesystems': [{'maj:min': '179:2'}]}]
                      for role in ('application', 'database', 'settings')},
    }
    snapshot.write_text(json.dumps(payload))
    monkeypatch.setattr(discovery, 'SNAPSHOT_PATH', str(snapshot))
    drive = api_client.get('/api/system/storage-devices').json['devices'][0]
    request = {'path': drive['path'], 'device_id': drive['device_id'], 'confirmation': drive['name']}
    return snapshot, payload, request


def test_dry_run_returns_plan_without_disk_commands_or_snapshot_changes(api_client, synthetic_drive, monkeypatch):
    snapshot, _, request = synthetic_drive
    original = snapshot.read_bytes()
    # Any attempted command would fail this test; all drive data is synthetic.
    monkeypatch.setattr('subprocess.run', Mock(side_effect=AssertionError('No commands during dry run')))
    response = api_client.post('/api/system/storage/format-dry-run', json=request)
    assert response.status_code == 200
    plan = response.json
    assert plan['dry_run'] is True
    assert plan['drive']['path'] == '/dev/sda'
    assert plan['drive']['name'] == 'BIRDSTORE'
    assert plan['drive']['size_bytes'] == 500000000000
    assert plan['filesystem'] == 'ext4'
    assert plan['erases_all_data'] is True
    assert plan['formatting_enabled'] is False
    assert snapshot.read_bytes() == original


def test_dry_run_rejects_wrong_typed_name(api_client, synthetic_drive):
    _, _, request = synthetic_drive
    request['confirmation'] = 'different drive'
    response = api_client.post('/api/system/storage/format-dry-run', json=request)
    assert response.status_code == 400
    assert 'does not match' in response.json['error']


def test_dry_run_rechecks_current_eligibility(api_client, synthetic_drive):
    snapshot, payload, request = synthetic_drive
    payload['protected']['database'] = [{'filesystems': [{'maj:min': '8:1'}]}]
    snapshot.write_text(json.dumps(payload))
    response = api_client.post('/api/system/storage/format-dry-run', json=request)
    assert response.status_code == 409
    assert response.json['error'] == 'Contains BirdNET database'


def test_dry_run_rejects_replaced_device_at_same_path(api_client, synthetic_drive):
    snapshot, payload, request = synthetic_drive
    payload['inventory']['blockdevices'][0]['serial'] = 'sample-B'
    snapshot.write_text(json.dumps(payload))
    response = api_client.post('/api/system/storage/format-dry-run', json=request)
    assert response.status_code == 409
    assert 'Drive information changed' in response.json['error']


def test_dry_run_requires_fresh_inventory(api_client, synthetic_drive):
    snapshot, _, request = synthetic_drive
    old = time.time() - 120
    os.utime(snapshot, (old, old))
    response = api_client.post('/api/system/storage/format-dry-run', json=request)
    assert response.status_code == 503
