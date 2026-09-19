"""Transitions that must never report a save as an observed runtime success."""
import copy
import json
import os
from unittest.mock import Mock

import pytest


def test_fresh_install_can_read_defaults_repeatedly(settings_file):
    path, runtime = settings_file
    for _ in range(3):
        assert runtime.read_saved_settings(force_reload=True)['audio']['sources'] == []
    assert not path.exists()


def test_atomic_replacement_during_read_cannot_pin_old_content(settings_file, monkeypatch):
    path, runtime = settings_file
    path.write_text(json.dumps({'access': {'public_access': True}}))
    original = runtime.load_user_settings
    calls = 0

    def racing_read(**kwargs):
        nonlocal calls
        data = original(**kwargs)
        calls += 1
        if calls == 1:
            old_stat = path.stat()
            replacement = path.with_suffix('.new')
            replacement.write_text(json.dumps({'access': {'public_access': False}}))
            os.utime(replacement, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
            replacement.replace(path)
        return data

    monkeypatch.setattr(runtime, 'load_user_settings', racing_read)
    assert runtime.get_runtime_setting('access.public_access') is False
    assert runtime.get_runtime_setting('access.public_access') is False
    assert calls == 2


@pytest.mark.parametrize('bad', ['{', '[]', '{"access": null}', '{"access":{"public_access":"false"}}'])
def test_invalid_settings_retain_last_good_and_reject_strict_read(settings_file, bad):
    path, runtime = settings_file
    path.write_text('{"access":{"public_access":false}}')
    assert runtime.get_runtime_setting('access.public_access') is False
    path.write_text(bad)
    runtime.invalidate_runtime_settings_cache()
    assert runtime.get_runtime_setting('access.public_access') is False
    with pytest.raises(ValueError):
        runtime.read_saved_settings(force_reload=True)
    path.write_text('{"access":{"public_access":true}}')
    assert runtime.get_runtime_setting('access.public_access') is True


def test_removed_settings_do_not_restore_public_defaults(settings_file):
    path, runtime = settings_file
    path.write_text('{"access":{"public_access":false}}')
    runtime.get_runtime_settings()
    path.unlink()
    assert runtime.get_runtime_setting('access.public_access') is False
    with pytest.raises(ValueError):
        runtime.read_saved_settings(force_reload=True)


def test_runtime_migration_is_read_only(settings_file):
    path, runtime = settings_file
    original = '{"audio":{"recording_mode":"pulseaudio"},"spectrogram":{"min_dbfs":-120}}'
    path.write_text(original)
    saved = runtime.read_saved_settings()
    assert saved['audio']['sources'][0]['id'] == 'source_0'
    assert saved['audio']['next_source_id'] == 1
    assert path.read_text() == original


def test_values_outside_current_rules_are_repaired_but_wrong_shapes_are_unreadable(settings_file, caplog):
    from config.settings import SettingsUnreadable
    path, runtime = settings_file
    # Equal percentages were accepted before the ordering rule existed; a
    # station must not stop over them (see the 2026-09-12 staging outage).
    path.write_text('{"storage":{"trigger_percent":70,"target_percent":70}}')
    with caplog.at_level('WARNING'):
        saved = runtime.read_saved_settings(force_reload=True)
    assert (saved['storage']['trigger_percent'], saved['storage']['target_percent']) == (70, 65)
    assert 'storage.target_percent must be less than trigger_percent' in caplog.text
    path.write_text('{"storage":{"trigger_percent":"70"}}')
    with pytest.raises(SettingsUnreadable, match='storage.trigger_percent must be a finite number'):
        runtime.read_saved_settings(force_reload=True)
    path.write_text('{"storage": {')
    with pytest.raises(SettingsUnreadable, match='Saved settings could not be read: Expecting'):
        runtime.read_saved_settings(force_reload=True)


def source(sid='source_0', **changes):
    return {'id': sid, 'type': 'rtsp', 'url': f'rtsp://camera/{sid}', 'enabled': True, **changes}


def test_source_reconciliation_keeps_unaffected_capture_and_retries_failed_stop():
    from core.source_config import reconcile_recorders
    factory = Mock(side_effect=lambda *_: Mock())
    recorders = {}
    sources = [source(), source('source_1')]
    assert reconcile_recorders(recorders, sources, 9, factory) == {}
    first, second = recorders.values()
    sources[0]['label'] = 'Renamed'
    reconcile_recorders(recorders, sources, 9, factory)
    first.stop.assert_not_called()
    assert factory.call_count == 2

    sources[0]['url'] = 'rtsp://replacement/audio'
    first.stop.side_effect = RuntimeError('still stopping')
    assert 'source_0' in reconcile_recorders(recorders, sources, 9, factory)
    assert recorders['source_0'] is first
    second.stop.assert_not_called()
    assert factory.call_count == 2

    first.stop.side_effect = None
    assert reconcile_recorders(recorders, sources, 9, factory) == {}
    assert recorders['source_0'] is not first
    assert recorders['source_1'] is second
    reconcile_recorders(recorders, sources, 12, factory)
    second.stop.assert_called_once()
    assert factory.call_count == 5


def test_failed_source_constructor_does_not_block_healthy_source():
    from core.source_config import reconcile_recorders
    factory = Mock(side_effect=[OSError('offline'), Mock(), Mock()])
    recorders = {}
    desired = [source(), source('source_1')]
    assert reconcile_recorders(recorders, desired, 9, factory) == {'source_0': 'Could not start recorder; retrying'}
    healthy = recorders['source_1']
    assert reconcile_recorders(recorders, desired, 9, factory) == {}
    assert recorders['source_1'] is healthy


def acknowledgements(saved):
    from core.source_config import recorder_source_revision
    return {s['id']: recorder_source_revision(s, saved) for s in saved['audio']['sources']}


def status_inputs():
    from config.settings import get_default_settings
    from core.source_config import source_revision
    saved = get_default_settings()
    saved['audio'].update(sources=[source()], next_source_id=1)
    recorder = {'updated_at': 1000, 'model_type': 'birdnet', 'source_settings_revisions': acknowledgements(saved),
                'sources': {'source_0': {'config_revision': source_revision(source(), 9), 'application_state': 'active'}}}
    streaming = {'updated_at': 1000, 'sources': {'source_0': {'config_revision': source_revision(source()), 'state': 'active'}}}
    return saved, recorder, streaming, {'model': {'type': 'birdnet'}}


def test_runtime_status_distinguishes_saved_connecting_failed_stale_and_active():
    from core.settings_status import build_settings_status
    saved, recorder, streaming, model = status_inputs()
    def read():
        return build_settings_status(saved, recorder, streaming, model, now=1001)
    assert read()['sources']['source_0'] == {'recording': 'active', 'streaming': 'active'}
    streaming['sources']['source_0']['state'] = 'failed'
    assert read()['sources']['source_0']['streaming'] == 'failed'
    saved['audio']['sources'][0]['url'] = 'rtsp://new/audio'
    assert read()['sources']['source_0'] == {'recording': 'pending', 'streaming': 'pending'}
    recorder['updated_at'] = streaming['updated_at'] = 900
    assert read()['sources']['source_0'] == {'recording': 'unknown', 'streaming': 'unknown'}
    assert read()['model']['state'] == 'unknown'


def test_repeated_model_save_stays_pending_until_both_services_acknowledge():
    from core.settings_status import build_settings_status
    saved, recorder, streaming, model = status_inputs()
    saved['model']['type'] = 'birdnet_v3'
    for _ in range(2):
        assert build_settings_status(copy.deepcopy(saved), recorder, streaming, model, now=1001)['model']['restart_required']
    model['model']['type'] = 'birdnet_v3'
    assert build_settings_status(saved, recorder, streaming, model, now=1001)['model']['restart_required']
    recorder['model_type'] = 'birdnet_v3'
    assert build_settings_status(saved, recorder, streaming, model, now=1001)['model']['state'] == 'active'


def test_disabled_source_is_pending_while_old_process_remains():
    from core.settings_status import build_settings_status
    saved, recorder, streaming, model = status_inputs()
    saved['audio']['sources'][0]['enabled'] = False
    recorder['source_settings_revisions'] = acknowledgements(saved)
    result = build_settings_status(saved, recorder, streaming, model, now=1001)
    assert result['sources']['source_0'] == {'recording': 'pending', 'streaming': 'pending'}
    recorder['sources'] = streaming['sources'] = {}
    result = build_settings_status(saved, recorder, streaming, model, now=1001)
    assert result['sources']['source_0'] == {'recording': 'disabled', 'streaming': 'disabled'}


def test_quiet_hours_pause_recording_without_stopping_stream():
    from core.settings_status import build_settings_status
    saved, recorder, streaming, model = status_inputs()
    recorder['sources']['source_0'] = {'state': 'paused'}
    recorder['pause'] = {'reason': 'quiet_hours'}
    result = build_settings_status(saved, recorder, streaming, model, now=1001)
    assert result['sources']['source_0'] == {'recording': 'paused', 'streaming': 'active'}
    assert result['pause'] == {'reason': 'quiet_hours'}
    assert build_settings_status(saved, recorder, streaming, model, now=1021)['pause'] is None


def test_constructor_failure_is_visible_without_an_active_recorder():
    from core.settings_status import build_settings_status
    saved, recorder, streaming, model = status_inputs()
    recorder['sources']['source_0'] = {'reload_error': 'Could not start recorder; retrying'}
    assert build_settings_status(saved, recorder, streaming, model, now=1001)['sources']['source_0'] == {
        'recording': 'failed', 'streaming': 'active', 'error': 'Could not start recorder; retrying'}


def test_capture_failure_carries_the_recorder_error_text():
    from core.settings_status import build_settings_status
    saved, recorder, streaming, model = status_inputs()
    recorder['sources']['source_0'].update(application_state='failed', last_error_message='Device not found')
    result = build_settings_status(saved, recorder, streaming, model, now=1001)
    assert result['sources']['source_0'] == {'recording': 'failed', 'streaming': 'active', 'error': 'Device not found'}


def test_http_unavailable_does_not_acknowledge_queued_audio(monkeypatch):
    import core.main as main
    monkeypatch.setattr(main.requests, 'post', Mock(return_value=Mock(status_code=503)))
    with pytest.raises(main.ModelServiceUnavailableError):
        main.process_audio_file('/tmp/queued.wav')
