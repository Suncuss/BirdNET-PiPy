"""Exercise the real settings writer, preconditions and shared validation."""
import pytest


def test_stale_save_is_rejected_without_losing_other_sections(api_client):
    original = api_client.get('/api/settings')
    response = api_client.put('/api/settings', json={'display': {'station_name': 'New name'}},
                              headers={'If-Match': original.headers['ETag']})
    assert response.status_code == 200
    stale = api_client.put('/api/settings/access', json={'public_access': False},
                           headers={'If-Match': original.headers['ETag']})
    assert stale.status_code == 412
    response = api_client.put('/api/settings/access', json={'public_access': False},
                              headers={'If-Match': response.headers['ETag']})
    assert response.status_code == 200
    saved = api_client.get('/api/settings').get_json()
    assert saved['display']['station_name'] == 'New name'
    assert saved['access']['public_access'] is False


def test_weak_etag_from_a_compressing_proxy_still_matches(api_client):
    original = api_client.get('/api/settings')
    response = api_client.put('/api/settings', json={'display': {'station_name': 'Behind nginx'}},
                              headers={'If-Match': 'W/' + original.headers['ETag']})
    assert response.status_code == 200
    stale = api_client.put('/api/settings', json={'display': {'station_name': 'Stale'}},
                           headers={'If-Match': 'W/' + original.headers['ETag']})
    assert stale.status_code == 412


@pytest.mark.parametrize('patch', [
    {'display': {'use_metric_units': 'false'}}, {'access': {'public_access': 1}},
    {'notifications': {'apprise_urls': [42]}}, {'notifications': {'rare_threshold': True}},
    {'detection': {'cutoff': 1.1}}, {'detection': {'sensitivity': float('nan')}},
    {'location': {'latitude': 91}}, {'location': {'longitude': '42'}},
    {'audio': {'recording_length': 0}}, {'audio': {'recording_chunk_length': 5}},
    {'model': {'type': None}}, {'audio': None}, {'unknown': True},
    {'storage': {'target_percent': 99}}, {'schedule': {'quiet_hours': {'start': '25:00'}}},
])
def test_bulk_settings_cannot_bypass_validation(api_client, patch):
    before = api_client.get('/api/settings')
    response = api_client.put('/api/settings', json=patch)
    assert response.status_code == 400, response.get_json()
    assert api_client.get('/api/settings').headers['ETag'] == before.headers['ETag']


def test_partial_schedule_merges_before_validation(api_client):
    response = api_client.put('/api/settings', json={'schedule': {'quiet_hours': {'enabled': True}}})
    assert response.status_code == 200
    assert response.get_json()['settings']['schedule']['quiet_hours'] == {
        'enabled': True, 'start': '22:00', 'end': '06:00'}


def test_model_aware_threshold_defaults_are_server_owned(api_client):
    response = api_client.put('/api/settings', json={'model': {'type': 'birdnet_v3'}})
    assert response.status_code == 200
    assert response.get_json()['settings']['detection']['species_filter_threshold'] == 0.15
    assert response.get_json()['changes']['full_restart_required'] is True


def test_corrupt_saved_settings_cannot_be_overwritten_from_defaults(api_client):
    from core.settings_store import USER_SETTINGS_PATH
    api_client.put('/api/settings', json={'access': {'public_access': False}})
    with open(USER_SETTINGS_PATH, 'w') as stream:
        stream.write('{broken')
    response = api_client.put('/api/settings', json={'display': {'station_name': 'New name'}})
    assert response.status_code == 503
    with open(USER_SETTINGS_PATH) as stream:
        assert stream.read() == '{broken'


def test_unreadable_settings_file_is_reported_with_its_cause(api_client):
    import config.settings as config
    from core.runtime_config import invalidate_runtime_settings_cache
    with open(config.USER_SETTINGS_PATH, 'w') as f:
        f.write('{"storage": {"trigger_percent": "high"}}')
    invalidate_runtime_settings_cache()
    response = api_client.get('/api/settings')
    assert response.status_code == 503
    body = response.get_json()
    assert body['code'] == 'settings_unreadable'
    assert 'storage.trigger_percent must be a finite number' in body['error']
    saved = api_client.put('/api/settings', json={'display': {'station_name': 'x'}})
    assert saved.status_code == 503
    assert saved.get_json()['code'] == 'settings_unreadable'
    assert 'Repair the settings file' in saved.get_json()['error']
