"""Tests for Home Assistant mode API behavior."""
import os
from unittest.mock import MagicMock, patch

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

    def test_returns_no_update_in_ha_mode(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=True):
            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is False
            assert 'Home Assistant' in data['message']


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


class TestHaRestart:
    """Test POST /api/system/restart in HA mode."""

    def test_restart_calls_supervisor_api(self, api_client):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api.requests.post', return_value=mock_resp) as mock_post:
            with patch.dict(os.environ, {'SUPERVISOR_TOKEN': 'test-token'}):
                response = api_client.post('/api/system/restart')
                assert response.status_code == 200
                data = response.get_json()
                assert data['status'] == 'restart_requested'

                mock_post.assert_called_once_with(
                    'http://supervisor/addons/self/restart',
                    headers={'Authorization': 'Bearer test-token'},
                    timeout=10,
                )

    def test_restart_returns_502_on_supervisor_error(self, api_client):
        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api.requests.post') as mock_post:
            mock_post.side_effect = requests.ConnectionError('Connection refused')
            with patch.dict(os.environ, {'SUPERVISOR_TOKEN': 'test-token'}):
                response = api_client.post('/api/system/restart')
                assert response.status_code == 502
                data = response.get_json()
                assert 'Failed to restart' in data['error']

    def test_restart_returns_502_on_http_error(self, api_client):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError('401 Unauthorized')

        with patch('core.api.is_home_assistant_mode', return_value=True), \
             patch('core.api.requests.post', return_value=mock_resp):
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
