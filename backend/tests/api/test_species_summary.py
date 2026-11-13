"""HTTP contract and public visibility for species summaries."""
import pytest

from tests.api.conftest import auth_enabled_app, insert_detection, login_owner


def test_summary_dates_and_timezone(api_client, real_db_manager, monkeypatch):
    import core.routes.species as species_routes
    monkeypatch.setattr(species_routes, 'get_timezone_str', lambda: 'Australia/Brisbane')
    insert_detection(real_db_manager, timestamp='2026-11-07T00:00:00',
                     scientific_name='Gymnorhina tibicen', common_name='Australian Magpie')
    insert_detection(real_db_manager, timestamp='2026-11-14T00:00:00')
    response = api_client.get('/api/species/summary?start_date=2026-11-07&end_date=2026-11-13')
    assert response.status_code == 200
    assert response.get_json() == {
        'start_date': '2026-11-07', 'end_date': '2026-11-13',
        'timezone': 'Australia/Brisbane',
        'species': [{
            'scientific_name': 'Gymnorhina tibicen', 'common_name': 'Australian Magpie',
            'count': 1, 'first_detected': '2026-11-07T00:00:00',
            'last_detected': '2026-11-07T00:00:00',
        }],
    }


def test_all_time_and_empty_results(api_client, real_db_manager):
    response = api_client.get('/api/species/summary')
    assert response.status_code == 200
    data = response.get_json()
    assert data['start_date'] is None and data['end_date'] is None
    assert data['species'] == []
    insert_detection(real_db_manager, timestamp='2000-01-01T00:00:00')
    assert api_client.get('/api/species/summary').get_json()['species'][0]['count'] == 1
    response = api_client.get('/api/species/summary?start_date=2026-11-07&end_date=2026-11-13')
    assert response.status_code == 200
    assert response.get_json()['species'] == []


@pytest.mark.parametrize('query', [
    'start_date=2026-11-07', 'end_date=2026-11-13',
    'start_date=&end_date=',
    'start_date=2026-02-30&end_date=2026-03-01',
    'start_date=20261107&end_date=20261113',
    'start_date=2026-1-7&end_date=2026-11-13',
    'start_date=2026-11-07T00:00:00&end_date=2026-11-13',
    'start_date=2026-11-14&end_date=2026-11-13',
])
def test_invalid_dates(api_client, query):
    response = api_client.get('/api/species/summary?' + query)
    assert response.status_code == 400
    assert response.get_json()['error']


@pytest.mark.parametrize('public_access', [False, True])
@pytest.mark.parametrize('charts_public', [False, True])
def test_follows_station_public_visibility(real_db_manager, public_access, charts_public):
    insert_detection(real_db_manager)
    with auth_enabled_app(real_db_manager, access={
        'public_access': public_access, 'charts_public': charts_public,
    }) as (client, _):
        for url in (
            '/api/species/summary',
            '/api/species/summary?start_date=2024-01-15&end_date=2024-01-15',
        ):
            response = client.get(url)
            assert response.status_code == (200 if public_access else 401)
            if public_access:
                assert set(response.get_json()['species'][0]) == {
                    'scientific_name', 'common_name', 'count', 'first_detected', 'last_detected',
                }
        login_owner(client)
        assert client.get('/api/species/summary').status_code == 200
