"""Tests for Home Assistant mode API behavior."""
import os
from unittest.mock import MagicMock, patch

import pytest
import requests


class TestHaModeDetection:
    """Test ha_mode.py runtime detection logic."""

    def test_native_mode_when_no_token(self):
        with patch.dict(os.environ, {}, clear=True):
            from core.ha_mode import get_runtime_mode, is_home_assistant_mode
            assert get_runtime_mode() == 'native'
            assert is_home_assistant_mode() is False

    def test_native_mode_when_empty_token(self):
        with patch.dict(os.environ, {'SUPERVISOR_TOKEN': ''}):
            from core.ha_mode import get_runtime_mode, is_home_assistant_mode
            assert get_runtime_mode() == 'native'
            assert is_home_assistant_mode() is False

    def test_native_mode_when_whitespace_token(self):
        with patch.dict(os.environ, {'SUPERVISOR_TOKEN': '   '}):
            from core.ha_mode import get_runtime_mode, is_home_assistant_mode
            assert get_runtime_mode() == 'native'
            assert is_home_assistant_mode() is False

    def test_ha_mode_when_token_set(self):
        with patch.dict(os.environ, {'SUPERVISOR_TOKEN': 'abc123'}):
            from core.ha_mode import get_runtime_mode, is_home_assistant_mode
            assert get_runtime_mode() == 'ha'
            assert is_home_assistant_mode() is True


class TestHaVersionEndpoint:
    """Test GET /api/system/version in HA mode."""

    def test_returns_ha_version_info(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api.get_runtime_mode', return_value='ha'), \
             patch('core.api.load_ha_source_commit', return_value='abc1234def'):
            with patch.dict(os.environ, {'BUILD_VERSION': '2.0.0'}):
                response = api_client.get('/api/system/version')
                assert response.status_code == 200
                data = response.get_json()
                assert data['version'] == '2.0.0'
                assert data['current_commit'] == 'abc1234def'
                assert data['current_branch'] == 'home_assistant'
                assert data['runtime_mode'] == 'ha'
                assert 'app_source_commit' not in data

    def test_returns_unknown_when_no_source_commit(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api.get_runtime_mode', return_value='ha'), \
             patch('core.api.load_ha_source_commit', return_value=None):
            with patch.dict(os.environ, {'BUILD_VERSION': '2.0.0'}):
                response = api_client.get('/api/system/version')
                assert response.status_code == 200
                data = response.get_json()
                assert data['current_commit'] == 'unknown'

    def test_native_mode_returns_runtime_mode(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=False), \
             patch('core.api.get_runtime_mode', return_value='native'), \
             patch('core.api.load_version_info') as mock_load:
            mock_load.return_value = {
                'version': '0.5.0',
                'commit': '1a081f5',
                'commit_date': '2025-11-28T08:49:00Z',
                'branch': 'main',
                'remote_url': 'https://github.com/Suncuss/BirdNET-PiPy',
            }
            response = api_client.get('/api/system/version')
            assert response.status_code == 200
            data = response.get_json()
            assert data['runtime_mode'] == 'native'


class TestHaUpdateCheck:
    """Test GET /api/system/update-check in HA mode."""

    def test_update_check_returns_available(self, api_client):
        supervisor_info = {
            'update_available': True,
            'version': '0.6.3',
            'version_latest': '0.6.4',
        }
        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api._call_supervisor', return_value=(supervisor_info, None)):
            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is True
            assert data['runtime_mode'] == 'ha'
            assert data['current_version'] == '0.6.3'
            assert data['latest_version'] == '0.6.4'

    def test_update_check_returns_up_to_date(self, api_client):
        supervisor_info = {
            'update_available': False,
            'version': '0.6.4',
            'version_latest': '0.6.4',
        }
        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api._call_supervisor', return_value=(supervisor_info, None)):
            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is False

    def test_update_check_supervisor_error_returns_502(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api._call_supervisor', return_value=(None, 'Connection refused')):
            response = api_client.get('/api/system/update-check')
            assert response.status_code == 502
            data = response.get_json()
            assert 'Failed to check' in data['error']

    def test_update_check_force_calls_store_reload(self, api_client):
        supervisor_info = {
            'update_available': False,
            'version': '0.6.4',
            'version_latest': '0.6.4',
        }
        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api._call_supervisor', return_value=(supervisor_info, None)) as mock_call:
            response = api_client.get('/api/system/update-check?force=true')
            assert response.status_code == 200
            calls = mock_call.call_args_list
            assert len(calls) == 2
            assert calls[0] == (('POST', '/store/reload'), {'timeout': 30})
            assert calls[1] == (('GET', '/addons/self/info'),)

    def test_update_check_no_force_skips_store_reload(self, api_client):
        supervisor_info = {
            'update_available': False,
            'version': '0.6.4',
            'version_latest': '0.6.4',
        }
        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api._call_supervisor', return_value=(supervisor_info, None)) as mock_call:
            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            mock_call.assert_called_once_with('GET', '/addons/self/info')


class TestHaUpdateChannel:
    """Test PUT /api/system/update-channel in HA mode."""

    def test_rejects_channel_change_in_ha_mode(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=True):
            response = api_client.put(
                '/api/settings/channel',
                json={'channel': 'latest'},
            )
            assert response.status_code == 400
            data = response.get_json()
            assert 'not supported' in data['error'].lower()


def _entity_state_resp(installed='0.6.4-dev16', latest='0.6.4-dev17'):
    """Build a mock GET /states/<entity> response with given versions."""
    resp = MagicMock()
    resp.ok = True
    resp.json.return_value = {
        'attributes': {'installed_version': installed, 'latest_version': latest}
    }
    return resp


@pytest.fixture
def ha_addon_mocks(monkeypatch):
    """Patch HA addon trigger preconditions: HA mode on, slug + entity resolved,
    SUPERVISOR_TOKEN set. Yields the supervisor and lookup mocks so tests can
    override return values for failure-path scenarios."""
    monkeypatch.setenv('SUPERVISOR_TOKEN', 'test-token')
    with patch('core.api.is_home_assistant_mode', return_value=True), \
         patch('core.api._call_supervisor',
               return_value=({'slug': 'a0d7b954_birdnet-pipy'}, None)) as mock_supervisor, \
         patch('core.api._find_addon_update_entity',
               return_value=('update.birdnet_pipy_update', None)) as mock_lookup:
        yield {'supervisor': mock_supervisor, 'lookup': mock_lookup}


class TestHaTriggerUpdate:
    """Test POST /api/system/update in HA mode.

    In the real success case, Supervisor kills the Flask process — Python never
    reaches the except block. Only genuine failures produce exceptions.
    """

    def test_trigger_update_success_on_2xx(self, api_client, ha_addon_mocks):
        post_resp = MagicMock()
        post_resp.raise_for_status.return_value = None

        with patch('core.api.requests.post', return_value=post_resp) as mock_post, \
             patch('core.api.requests.get', return_value=_entity_state_resp()) as mock_get:
            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            assert response.get_json()['status'] == 'update_triggered'
            ha_addon_mocks['supervisor'].assert_called_once_with('GET', '/addons/self/info')
            ha_addon_mocks['lookup'].assert_called_once_with('a0d7b954_birdnet-pipy', 'test-token')
            assert len(mock_post.call_args_list) == 2
            refresh_call, install_call = mock_post.call_args_list
            assert refresh_call.args[0] == 'http://supervisor/core/api/services/homeassistant/update_entity'
            assert refresh_call.kwargs['json'] == {'entity_id': 'update.birdnet_pipy_update'}
            assert install_call.args[0] == 'http://supervisor/core/api/services/update/install'
            assert install_call.kwargs['headers'] == {'Authorization': 'Bearer test-token'}
            assert install_call.kwargs['json'] == {'entity_id': 'update.birdnet_pipy_update'}
            assert install_call.kwargs['timeout'] == 10
            mock_get.assert_called_with(
                'http://supervisor/core/api/states/update.birdnet_pipy_update',
                headers={'Authorization': 'Bearer test-token'},
                timeout=5,
            )

    def test_trigger_update_continues_when_entity_refresh_fails(self, api_client, ha_addon_mocks):
        install_resp = MagicMock()
        install_resp.raise_for_status.return_value = None

        def post_side_effect(url, *args, **kwargs):
            if 'update_entity' in url:
                raise requests.ConnectionError('refresh failed')
            return install_resp

        with patch('core.api.requests.post', side_effect=post_side_effect), \
             patch('core.api.requests.get', return_value=_entity_state_resp()):
            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            assert response.get_json()['status'] == 'update_triggered'

    def test_trigger_update_returns_502_when_entity_stays_stale(self, api_client, ha_addon_mocks):
        post_resp = MagicMock()
        post_resp.raise_for_status.return_value = None

        with patch('core.api.requests.post', return_value=post_resp), \
             patch('core.api.requests.get',
                   return_value=_entity_state_resp(installed='1.0.0', latest='1.0.0')), \
             patch('core.api._HA_ENTITY_POLL_TIMEOUT_SECONDS', 0), \
             patch('core.api.time.sleep'):
            response = api_client.post('/api/system/update')
            assert response.status_code == 502
            assert 'has not yet refreshed' in response.get_json()['error']

    def test_trigger_update_slug_lookup_error_returns_502(self, api_client, ha_addon_mocks):
        ha_addon_mocks['supervisor'].return_value = (None, 'Connection refused')
        response = api_client.post('/api/system/update')
        assert response.status_code == 502
        assert 'determine Home Assistant addon slug' in response.get_json()['error']

    def test_trigger_update_missing_slug_returns_502(self, api_client, ha_addon_mocks):
        ha_addon_mocks['supervisor'].return_value = ({}, None)
        response = api_client.post('/api/system/update')
        assert response.status_code == 502
        assert 'determine Home Assistant addon slug' in response.get_json()['error']

    def test_trigger_update_entity_lookup_error_returns_502(self, api_client, ha_addon_mocks):
        ha_addon_mocks['lookup'].return_value = (None, 'Could not find update entity for addon a0d7b954_birdnet-pipy')
        response = api_client.post('/api/system/update')
        assert response.status_code == 502
        assert 'Could not find update entity' in response.get_json()['error']

    def test_trigger_update_http_error_returns_502(self, api_client, ha_addon_mocks):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = requests.HTTPError('401 Unauthorized')

        with patch('core.api.requests.post', return_value=mock_resp), \
             patch('core.api.requests.get', return_value=_entity_state_resp()):
            response = api_client.post('/api/system/update')
            assert response.status_code == 502
            assert 'Failed to trigger' in response.get_json()['error']

    def test_trigger_update_connection_error_treated_as_success(self, api_client, ha_addon_mocks):
        # Self-update kills our process mid-request, so a ConnectionError
        # after dispatch is the expected outcome — not a failure.
        with patch('core.api.requests.post', side_effect=requests.ConnectionError('Connection refused')), \
             patch('core.api.requests.get', return_value=_entity_state_resp()):
            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            assert response.get_json()['status'] == 'update_triggered'

    def test_trigger_update_timeout_treated_as_success(self, api_client, ha_addon_mocks):
        # HA Core's REST service call blocks until install finishes; a
        # ReadTimeout after dispatch means the install is running, not failed.
        with patch('core.api.requests.post', side_effect=requests.Timeout('Request timed out')), \
             patch('core.api.requests.get', return_value=_entity_state_resp()):
            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            assert response.get_json()['status'] == 'update_triggered'

    def test_native_trigger_update_writes_flag(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=False), \
             patch('core.api.load_version_info') as mock_load, \
             patch('core.api.write_flag') as mock_flag:
            mock_load.return_value = {
                'version': '0.5.0',
                'commit': '1a081f5',
            }
            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            mock_flag.assert_called_once()


class TestFindAddonUpdateEntity:
    """Test _find_addon_update_entity helper."""

    def _states(self, *extra):
        base = [
            {
                'entity_id': 'sensor.cpu',
                'attributes': {'entity_picture': '/api/hassio/addons/a0d7b954_birdnet-pipy/icon'},
            },
            {
                'entity_id': 'update.other_addon_update',
                'attributes': {'entity_picture': '/api/hassio/addons/other_slug/icon'},
            },
        ]
        return base + list(extra)

    def test_returns_entity_id_on_match(self):
        from core.api import _find_addon_update_entity
        states = self._states({
            'entity_id': 'update.birdnet_pipy_update',
            'attributes': {'entity_picture': '/api/hassio/addons/a0d7b954_birdnet-pipy/icon'},
        })
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = states
        with patch('core.api.requests.get', return_value=mock_resp) as mock_get:
            entity_id, err = _find_addon_update_entity('a0d7b954_birdnet-pipy', 'tok')
            assert entity_id == 'update.birdnet_pipy_update'
            assert err is None
            mock_get.assert_called_once_with(
                'http://supervisor/core/api/states',
                headers={'Authorization': 'Bearer tok'},
                timeout=10,
            )

    def test_returns_error_when_not_found(self):
        from core.api import _find_addon_update_entity
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = self._states()
        with patch('core.api.requests.get', return_value=mock_resp):
            entity_id, err = _find_addon_update_entity('a0d7b954_birdnet-pipy', 'tok')
            assert entity_id is None
            assert 'Could not find update entity' in err

    def test_returns_error_on_http_failure(self):
        from core.api import _find_addon_update_entity
        with patch('core.api.requests.get',
                   side_effect=requests.ConnectionError('refused')):
            entity_id, err = _find_addon_update_entity('a0d7b954_birdnet-pipy', 'tok')
            assert entity_id is None
            assert 'Failed to fetch HA Core states' in err


class TestHaRestart:
    """Test POST /api/system/restart in HA mode."""

    def test_restart_calls_supervisor_api(self, api_client):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {'data': {}}
        mock_resp.content = b'{}'

        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api.requests.request', return_value=mock_resp) as mock_req:
            with patch.dict(os.environ, {'SUPERVISOR_TOKEN': 'test-token'}):
                response = api_client.post('/api/system/restart')
                assert response.status_code == 200
                data = response.get_json()
                assert data['status'] == 'restart_requested'

                mock_req.assert_called_once_with(
                    'POST',
                    'http://supervisor/addons/self/restart',
                    headers={'Authorization': 'Bearer test-token'},
                    timeout=10,
                )

    def test_restart_returns_502_on_supervisor_error(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api.requests.request') as mock_req:
            mock_req.side_effect = requests.ConnectionError('Connection refused')
            with patch.dict(os.environ, {'SUPERVISOR_TOKEN': 'test-token'}):
                response = api_client.post('/api/system/restart')
                assert response.status_code == 502
                data = response.get_json()
                assert 'Failed to restart' in data['error']

    def test_restart_returns_502_on_http_error(self, api_client):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError('401 Unauthorized')

        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api.requests.request', return_value=mock_resp):
            with patch.dict(os.environ, {'SUPERVISOR_TOKEN': 'bad-token'}):
                response = api_client.post('/api/system/restart')
                assert response.status_code == 502
                data = response.get_json()
                assert 'Failed to restart' in data['error']

    def test_native_restart_writes_flag(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=False), \
             patch('core.api.write_flag') as mock_flag:
            response = api_client.post('/api/system/restart')
            assert response.status_code == 200
            mock_flag.assert_called_once_with('restart-backend')


class TestLoadHaSourceCommit:
    """Test load_ha_source_commit helper."""

    def test_reads_from_env_var(self):
        with patch.dict(os.environ, {'BIRDNET_PIPY_SOURCE_COMMIT': 'abc123'}):
            from core.api import load_ha_source_commit
            assert load_ha_source_commit() == 'abc123'

    def test_env_var_takes_precedence_over_file(self, tmp_path):
        commit_file = tmp_path / 'birdnet_pipy_source_commit.txt'
        commit_file.write_text('file_commit')

        with patch.dict(os.environ, {'BIRDNET_PIPY_SOURCE_COMMIT': 'env_commit'}), \
             patch('core.api.HA_SOURCE_COMMIT_FILE', str(commit_file)):
            from core.api import load_ha_source_commit
            assert load_ha_source_commit() == 'env_commit'

    def test_reads_from_file_when_no_env(self, tmp_path):
        commit_file = tmp_path / 'birdnet_pipy_source_commit.txt'
        commit_file.write_text('file_commit\n')

        with patch.dict(os.environ, {}, clear=True), \
             patch('core.api.HA_SOURCE_COMMIT_FILE', str(commit_file)):
            # Clear env var if present
            os.environ.pop('BIRDNET_PIPY_SOURCE_COMMIT', None)
            from core.api import load_ha_source_commit
            assert load_ha_source_commit() == 'file_commit'

    def test_returns_none_when_no_source(self, tmp_path):
        with patch.dict(os.environ, {}, clear=True), \
             patch('core.api.HA_SOURCE_COMMIT_FILE', str(tmp_path / 'nonexistent.txt')):
            os.environ.pop('BIRDNET_PIPY_SOURCE_COMMIT', None)
            from core.api import load_ha_source_commit
            assert load_ha_source_commit() is None
