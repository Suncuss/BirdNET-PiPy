"""HTTP contract and public visibility for species summaries."""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from tests.api.conftest import auth_enabled_app, insert_detection, login_owner


@pytest.fixture
def freeze_clock(monkeypatch):
    """Pin the route's station timezone and UTC clock: freeze_clock(tz, utc_iso)."""
    def freeze(tz_name, utc_iso):
        import core.routes.species as species_routes
        monkeypatch.setattr(species_routes, 'get_timezone', lambda: ZoneInfo(tz_name))
        monkeypatch.setattr(species_routes, '_utc_now',
                            lambda: datetime.fromisoformat(utc_iso).replace(tzinfo=UTC))
        return species_routes
    return freeze


def test_summary_dates_and_timezone(api_client, real_db_manager, monkeypatch):
    import core.routes.species as species_routes
    monkeypatch.setattr(species_routes, 'get_timezone_str', lambda: 'Australia/Brisbane')
    insert_detection(real_db_manager, timestamp='2026-11-07T00:00:00',
                     scientific_name='Gymnorhina tibicen', common_name='Australian Magpie')
    insert_detection(real_db_manager, timestamp='2026-11-14T00:00:00')
    response = api_client.get('/api/species/summary?start_date=2026-11-07&end_date=2026-11-13')
    assert response.status_code == 200
    assert response.get_json() == {
        'start_date': '2026-11-07', 'end_date': '2026-11-13', 'hours': None,
        'timezone': 'Australia/Brisbane',
        'species': [{
            'scientific_name': 'Gymnorhina tibicen', 'common_name': 'Australian Magpie',
            'display_common_name': 'Australian Magpie',
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




@pytest.mark.parametrize('public_access', [False, True])
@pytest.mark.parametrize('charts_public', [False, True])
def test_anonymous_access_follows_public_charts(real_db_manager, public_access, charts_public):
    from core.timezone_service import local_now
    insert_detection(real_db_manager)
    # A row inside the rolling window too, so hours=24 has something to shape-check.
    insert_detection(real_db_manager, timestamp=local_now().strftime('%Y-%m-%dT%H:%M:%S'))
    with auth_enabled_app(real_db_manager, access={
        'public_access': public_access, 'charts_public': charts_public,
    }) as (client, _):
        allowed = public_access and charts_public
        for url in (
            '/api/species/summary',
            '/api/species/summary?start_date=2024-01-15&end_date=2024-01-15',
            '/api/species/summary?hours=24',
        ):
            response = client.get(url)
            assert response.status_code == (200 if allowed else 401)
            if allowed:
                assert set(response.get_json()['species'][0]) == {
                    'scientific_name', 'common_name', 'display_common_name',
                    'count', 'first_detected', 'last_detected',
                }
        login_owner(client)
        assert client.get('/api/species/summary').status_code == 200


def test_display_names_follow_bird_name_language(api_client, real_db_manager):
    from unittest.mock import patch

    from core.bird_name_utils import clear_bird_name_caches
    insert_detection(real_db_manager, timestamp='2026-11-07T10:00:00',
                     scientific_name='Cyanocitta cristata', common_name='Blue Jay')
    clear_bird_name_caches()
    try:
        with patch('core.routes.species.load_user_settings', return_value={
            'model': {'type': 'birdnet'}, 'display': {'bird_name_language': 'de'},
        }):
            species = api_client.get('/api/species/summary').get_json()['species']
    finally:
        clear_bird_name_caches()
    assert species[0]['common_name'] == 'Blue Jay'
    assert species[0]['display_common_name'] == 'Blauhäher'


def test_rolling_hours_window(api_client, real_db_manager, freeze_clock):
    freeze_clock('UTC', '2026-11-14T12:00:00')
    for timestamp in ('2026-11-13T11:59:59', '2026-11-13T12:00:00', '2026-11-14T11:00:00'):
        insert_detection(real_db_manager, timestamp=timestamp)
    data = api_client.get('/api/species/summary?hours=24').get_json()
    assert (data['hours'], data['start_date'], data['end_date']) == (24, None, None)
    assert [(s['count'], s['first_detected'], s['last_detected']) for s in data['species']] == [
        (2, '2026-11-13T12:00:00', '2026-11-14T11:00:00'),
    ]
    assert api_client.get('/api/species/summary?hours=1').get_json()['species'][0]['count'] == 1


@pytest.mark.parametrize('query', [
    'start_date=2026-11-07', 'end_date=2026-11-13',
    'start_date=&end_date=',
    'start_date=2026-02-30&end_date=2026-03-01',
    'start_date=20261107&end_date=20261113',
    'start_date=2026-1-7&end_date=2026-11-13',
    'start_date=2026-11-07T00:00:00&end_date=2026-11-13',
    'start_date=2026-11-14&end_date=2026-11-13',
    'hours=0', 'hours=169', 'hours=-1', 'hours=1.5', 'hours=abc', 'hours=',
    'hours=24&start_date=2026-11-07&end_date=2026-11-13',
    'hours=24&start_date=2026-11-07',
])
def test_invalid_window_params(api_client, query):
    response = api_client.get(f'/api/species/summary?{query}')
    assert response.status_code == 400
    assert response.get_json()['error']


@pytest.mark.parametrize('utc_now, expected', [
    # 2026-11-01 12:00 EST: clocks fell back at 02:00, so 24 elapsed hours
    # ago is 13:00 EDT the day before, not 12:00.
    ('2026-11-01T17:00:00', '2026-10-31T13:00:00'),
    # 2026-03-08 12:00 EDT: clocks sprang forward, so 24h ago is 11:00 EST.
    ('2026-03-08T16:00:00', '2026-03-07T11:00:00'),
])
def test_rolling_cutoff_counts_elapsed_hours_across_dst(freeze_clock, utc_now, expected):
    species_routes = freeze_clock('America/New_York', utc_now)
    assert species_routes._rolling_cutoff(24).isoformat() == expected
