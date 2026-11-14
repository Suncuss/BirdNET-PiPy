"""Owner settings flow: queue, poll and finish a media-only move."""
from unittest.mock import Mock


def test_settings_move_preserves_config_location_and_reports_completion(api_client, real_db_manager, tmp_path, monkeypatch):
    import core.media_transfer as mt
    internal = tmp_path / 'old-media'
    drive = tmp_path / 'new-media'
    clip = internal / 'audio/extracted_songs/bird.mp3'
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b'bird audio')
    drive.mkdir()
    target = '/external-media'
    targets = [{'id': 'internal', 'mount_path': str(internal)},
               {'id': target, 'mount_path': str(drive)}]
    monkeypatch.setattr(mt, '_INTERNAL_MEDIA_ROOT', str(internal))
    monkeypatch.setattr(mt, 'get_available_media_targets', lambda: targets)
    monkeypatch.setattr(mt, 'get_media_storage_status', lambda settings: {
        'effective_target_id': target, 'effective_target': targets[1]})
    monkeypatch.setattr(mt, 'get_effective_media_root', lambda settings: str(drive / 'BirdNET-PiPy'))
    monkeypatch.setattr(mt, 'REQUEST_PATH', str(tmp_path / 'request.json'))
    monkeypatch.setattr(mt, 'STATUS_PATH', str(tmp_path / 'status.json'))
    initial = api_client.get('/api/settings').json
    response = api_client.put('/api/settings', json={'storage': {'media_target': target}},
                              headers={'X-Move-Existing-Media': 'true'})
    assert response.status_code == 202
    assert response.json['transfer']['state'] == 'waiting'
    assert api_client.get('/api/settings').json == initial
    assert api_client.put('/api/settings', json={'display': {'station_name': 'other'}}).status_code == 409
    mt.handle_pending_transfer(Mock(), Mock(), real_db_manager)
    status = api_client.get('/api/system/media-transfer')
    assert status.json['state'] == 'complete'
    assert not status.json['changes']['full_restart_required']
    assert status.json['settings']['storage']['media_target'] == target
    assert 'ETag' in status.headers
    assert (drive / 'BirdNET-PiPy/audio/extracted_songs/bird.mp3').read_bytes() == b'bird audio'
    assert not clip.exists()
    # Config and DB directories are not changed by the storage preference.
    import core.settings_store as store
    assert str(tmp_path / 'new-media') not in store.USER_SETTINGS_PATH
    assert real_db_manager.db_path != str(drive / 'birds.db')
