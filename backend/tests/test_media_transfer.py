"""Focused media move checks using real temporary files."""
import json
from unittest.mock import Mock

import pytest


@pytest.fixture
def move_setup(tmp_path, monkeypatch):
    import core.media_storage as ms
    import core.media_transfer as mt
    internal = tmp_path / 'data'
    drive = tmp_path / 'drive'
    internal.mkdir()
    drive.mkdir()
    targets = [
        {'id': 'internal', 'mount_path': str(internal)},
        {'id': str(drive), 'mount_path': str(drive)},
    ]
    settings = {'storage': {'media_target': str(drive)}}
    monkeypatch.setattr(mt, '_INTERNAL_MEDIA_ROOT', str(internal))
    monkeypatch.setattr(mt, 'get_available_media_targets', lambda: targets)
    monkeypatch.setattr(mt, 'get_media_storage_status', lambda s: {
        'effective_target_id': str(drive), 'effective_target': targets[1]})
    monkeypatch.setattr(mt, 'get_effective_media_root', lambda s: str(drive / ms.EXTERNAL_MEDIA_APP_DIR))
    monkeypatch.setattr(mt, 'REQUEST_PATH', str(tmp_path / 'request.json'))
    monkeypatch.setattr(mt, 'STATUS_PATH', str(tmp_path / 'status.json'))
    for subdir, name in [('audio/recordings/source_0', 'recording.wav'),
                         ('audio/extracted_songs', 'bird.mp3'),
                         ('spectrograms', 'bird.webp')]:
        folder = internal / subdir
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(('test ' + name).encode())
    (internal / 'birds.db').write_bytes(b'database unchanged')
    (internal / 'user_settings.json').write_text('{"keep": "here"}')
    return mt, internal, drive / ms.EXTERNAL_MEDIA_APP_DIR, settings


def test_move_copies_verifies_then_saves_and_removes_media(move_setup, monkeypatch, test_db_manager):
    mt, internal, destination, settings = move_setup
    progress = []
    pause = Mock()
    resume = Mock()
    def save(saved):
        # Every original is still present when the destination is committed.
        assert (internal / 'audio/extracted_songs/bird.mp3').exists()
        assert (destination / 'audio/extracted_songs/bird.mp3').read_bytes() == b'test bird.mp3'
        assert saved == settings
    import core.settings_store as store
    monkeypatch.setattr(store, 'save_user_settings', save)
    mt.queue_transfer(settings, {'full_restart_paths': ['storage.media_target'], 'full_restart_required': True})
    real_write = mt.atomic_write_private_json
    def record(path, value):
        if path == mt.STATUS_PATH:
            progress.append(dict(value))
        real_write(path, value)
    monkeypatch.setattr(mt, 'atomic_write_private_json', record)
    assert mt.handle_pending_transfer(pause, resume, test_db_manager)
    pause.assert_called_once()
    resume.assert_called_once()
    assert not mt.transfer_pending()
    status = mt.transfer_status()
    assert status['state'] == 'complete'
    assert status['files_done'] == status['files_total'] == 3
    assert status['bytes_done'] == status['bytes_total'] > 0
    assert not status['changes']['full_restart_required']
    assert any(p['state'] == 'copying' for p in progress)
    for subdir, name in [('audio/recordings/source_0', 'recording.wav'),
                         ('audio/extracted_songs', 'bird.mp3'), ('spectrograms', 'bird.webp')]:
        assert not (internal / subdir / name).exists()
        assert (destination / subdir / name).read_bytes() == ('test ' + name).encode()
    assert (internal / 'birds.db').read_bytes() == b'database unchanged'
    assert json.loads((internal / 'user_settings.json').read_text()) == {'keep': 'here'}
    assert not (destination / 'birds.db').exists()
    assert not (destination / 'user_settings.json').exists()


def test_save_failure_keeps_originals_and_resumes(move_setup, monkeypatch, test_db_manager):
    mt, internal, _, settings = move_setup
    import core.settings_store as store
    monkeypatch.setattr(store, 'save_user_settings', Mock(side_effect=OSError('settings save failed')))
    resume = Mock()
    mt.queue_transfer(settings, {'full_restart_paths': ['storage.media_target']})
    mt.handle_pending_transfer(Mock(), resume, test_db_manager)
    assert mt.transfer_status()['state'] == 'failed'
    assert not mt.transfer_status()['location_saved']
    assert (internal / 'audio/extracted_songs/bird.mp3').exists()
    resume.assert_called_once()


def test_insufficient_space_leaves_originals(move_setup, monkeypatch):
    mt, internal, destination, settings = move_setup
    monkeypatch.setattr(mt.shutil, 'disk_usage', lambda path: type('Usage', (), {'free': 0})())
    with pytest.raises(ValueError, match='Not enough free space'):
        mt.move_media(settings, lambda **kwargs: None)
    assert (internal / 'audio/extracted_songs/bird.mp3').exists()
    assert not destination.exists()


def test_verification_failure_leaves_originals(move_setup, monkeypatch):
    mt, internal, _, settings = move_setup
    monkeypatch.setattr(mt, '_hash_file', lambda path: b'bad checksum')
    with pytest.raises(OSError, match='verification failed'):
        mt.move_media(settings, lambda **kwargs: None)
    assert (internal / 'audio/extracted_songs/bird.mp3').exists()


def test_recording_workers_pause_and_resume(monkeypatch):
    import queue

    import core.main as main
    started = queue.Queue()
    def worker(*args):
        started.put(True)
        main.stop_flag.wait()
    for name in ('continuous_audio_recording', 'process_audio_files', 'storage_monitor_loop'):
        monkeypatch.setattr(main, name, worker)
    try:
        main.start_media_workers()
        for _ in range(3):
            started.get(timeout=2)
        main.pause_media_workers()
        assert not any(getattr(main, name).is_alive() for name in
                       ('recording_thread', 'processing_thread', 'storage_thread'))
        main.start_media_workers()
        for _ in range(3):
            started.get(timeout=2)
    finally:
        main.pause_media_workers()
