"""Privacy regression tests: station coordinates must not leak.

Exact latitude/longitude pinpoint the user's home, so they are treated as
sensitive. Detection/observation payloads must never carry them (the data layer
strips them in DatabaseManager._normalize_detection, with a second endpoint-level
guard via _localize_detection). The only surfaces that expose coordinates are the
authenticated Settings GET and the authenticated CSV export. /api/settings/defaults
carries the default station coordinates and so is gated behind auth too.
"""

import json


def _insert_detection_with_coords(db, *, common_name='Blue Jay',
                                  scientific_name='Cyanocitta cristata',
                                  timestamp='2025-06-15T10:00:00'):
    db.insert_detection({
        'timestamp': timestamp,
        'group_timestamp': timestamp,
        'scientific_name': scientific_name,
        'common_name': common_name,
        'confidence': 0.9,
        'latitude': 40.7128,
        'longitude': -74.0060,
        'cutoff': 0.1,
        'sensitivity': 1.0,
        'overlap': 0.0,
        'extra': {},
        'audio_source': 'test_source',
    })


class TestObservationEndpointsHideCoordinates:
    """The public /api/observations/* endpoints must not expose coordinates."""

    def test_latest_observation_strips_coordinates(self, api_client, real_db_manager):
        _insert_detection_with_coords(real_db_manager)

        response = api_client.get('/api/observations/latest')
        assert response.status_code == 200
        data = response.get_json()
        # The detection is returned (so the endpoint still works)...
        assert data is not None
        assert data['common_name'] == 'Blue Jay'
        # ...but without the private coordinates.
        assert 'latitude' not in data
        assert 'longitude' not in data

    def test_recent_observations_strip_coordinates(self, api_client, real_db_manager):
        _insert_detection_with_coords(real_db_manager, timestamp='2025-06-15T10:00:00')
        _insert_detection_with_coords(
            real_db_manager, common_name='American Robin',
            scientific_name='Turdus migratorius', timestamp='2025-06-15T11:00:00',
        )

        response = api_client.get('/api/observations/recent')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data) == 2
        for detection in data:
            assert 'latitude' not in detection
            assert 'longitude' not in detection


class TestSettingsDefaultsRequiresAuth:
    """/api/settings/defaults carries default coordinates and is auth-gated."""

    def test_defaults_accessible_when_auth_disabled(self, api_client):
        # Auth is off by default in the sandboxed app.
        response = api_client.get('/api/settings/defaults')
        assert response.status_code == 200

    def test_defaults_blocked_when_not_authenticated(self, api_client):
        # Setup password (enables auth) then log out so we're unauthenticated.
        api_client.post('/api/auth/setup',
                        data=json.dumps({'password': 'testpass123'}),
                        content_type='application/json')
        api_client.post('/api/auth/logout')

        response = api_client.get('/api/settings/defaults')
        assert response.status_code == 401
        # The 401 body is an error message, not the settings payload.
        assert 'latitude' not in response.get_data(as_text=True)

    def test_defaults_accessible_when_authenticated(self, api_client):
        # Setup both enables auth and auto-logs-in.
        api_client.post('/api/auth/setup',
                        data=json.dumps({'password': 'testpass123'}),
                        content_type='application/json')

        response = api_client.get('/api/settings/defaults')
        assert response.status_code == 200
