"""Tests for /api/system/readiness and core.service_readiness."""

import time
from unittest.mock import Mock, patch

import requests

from tests.api.conftest import auth_enabled_app

MODEL_OK = {
    'status': 'ok',
    'model': {'type': 'birdnet', 'name': 'BirdNET', 'version': '2.4'},
    'location_filter': {'state': 'active'},
}


def _model_upstream():
    upstream = Mock()
    upstream.json.return_value = MODEL_OK
    return upstream


def _model_server_down():
    return patch('core.api.requests.get',
                 side_effect=requests.exceptions.ConnectionError('refused'))


class TestBuildServiceReadiness:
    def test_ready_when_model_is_up_and_recorder_heartbeat_is_fresh(self):
        from core.service_readiness import build_service_readiness
        result = build_service_readiness('ready', {'updated_at': 100.0}, now=105.0)
        assert result == {
            'ready': True,
            'services': {'model': 'ready', 'recorder': 'ready'},
        }

    def test_model_states(self):
        from core.service_readiness import model_readiness
        assert model_readiness(reachable=True, startup_failed=False) == 'ready'
        assert model_readiness(reachable=False, startup_failed=False) == 'starting'
        assert model_readiness(reachable=False, startup_failed=True) == 'failed'

    def test_recorder_starting_until_first_heartbeat(self):
        from core.service_readiness import build_service_readiness
        result = build_service_readiness('ready', {}, now=105.0)
        assert result['ready'] is False
        assert result['services']['recorder'] == 'starting'

    def test_stale_heartbeat_is_starting(self):
        from core.service_readiness import build_service_readiness
        from core.settings_status import STATUS_MAX_AGE
        result = build_service_readiness(
            'ready', {'updated_at': 100.0}, now=100.0 + STATUS_MAX_AGE + 1)
        assert result['services']['recorder'] == 'starting'

    def test_recorder_ready_even_when_sources_are_unhealthy(self):
        """A down camera or quiet hours must not hold the reload forever."""
        from core.service_readiness import build_service_readiness
        status = {'updated_at': 100.0, 'state': 'stopped', 'pause': {'reason': 'schedule'}}
        assert build_service_readiness('ready', status, now=101.0)['ready'] is True


class TestReadinessEndpoint:
    def test_reports_ready_services(self, api_client):
        import core.api as api_module
        api_module._recorder_status = {'updated_at': time.time()}
        with patch('core.api.requests.get', return_value=_model_upstream()) as request_get:
            response = api_client.get('/api/system/readiness')

        assert response.status_code == 200
        assert response.get_json() == {
            'ready': True,
            'services': {'model': 'ready', 'recorder': 'ready'},
        }
        # Short timeout: the model server is often down while this is polled
        assert request_get.call_args.kwargs['timeout'] == 1

    def test_degraded_location_filter_still_counts_as_ready(self, api_client):
        upstream = _model_upstream()
        upstream.json.return_value = {
            **MODEL_OK, 'status': 'degraded', 'location_filter': {'state': 'degraded'},
        }
        with patch('core.api.requests.get', return_value=upstream):
            response = api_client.get('/api/system/readiness')

        assert response.get_json()['services']['model'] == 'ready'

    def test_reports_starting_while_model_server_is_down(self, api_client):
        with _model_server_down(), patch('core.api.read_startup_failure', return_value=None):
            response = api_client.get('/api/system/readiness')

        assert response.get_json() == {
            'ready': False,
            'services': {'model': 'starting', 'recorder': 'starting'},
        }

    def test_reports_failed_model_without_error_details(self, api_client):
        failure = {'error_type': 'BirdNetV3AssetError', 'message': 'checksum mismatch'}
        with _model_server_down(), patch('core.api.read_startup_failure', return_value=failure):
            response = api_client.get('/api/system/readiness')

        assert response.get_json()['services']['model'] == 'failed'
        assert 'checksum' not in response.get_data(as_text=True)

    def test_public_even_on_a_private_station(self, real_db_manager):
        """A signed-out visitor on the update overlay polls this too."""
        with (
            auth_enabled_app(real_db_manager, access={'public_access': False}) as (client, _),
            patch('core.api.requests.get', return_value=_model_upstream()),
        ):
            response = client.get('/api/system/readiness')

        assert response.status_code == 200
        assert set(response.get_json()) == {'ready', 'services'}
