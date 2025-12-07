import pytest
from unittest.mock import patch, MagicMock

class TestSystemAPI:
    """Test system update API endpoints"""

    # Sample version.json content
    SAMPLE_VERSION_INFO = {
        'commit': '1a081f5',
        'commit_date': '2025-11-28T08:49:00Z',
        'branch': 'develop',
        'remote_url': 'https://github.com/Suncuss/BirdNET-PiPy',
        'build_time': '2025-11-28T10:00:00Z'
    }

    def test_get_version_info_success(self, api_client):
        """Test GET /api/system/version returns version info"""
        with patch('core.api.load_version_info') as mock_load:
            mock_load.return_value = self.SAMPLE_VERSION_INFO

            response = api_client.get('/api/system/version')
            assert response.status_code == 200
            data = response.get_json()
            assert data['current_commit'] == '1a081f5'
            assert data['current_branch'] == 'develop'
            assert data['remote_url'] == 'https://github.com/Suncuss/BirdNET-PiPy'

    def test_get_version_info_missing_file(self, api_client):
        """Test GET /api/system/version handles missing version.json"""
        with patch('core.api.load_version_info') as mock_load:
            mock_load.return_value = None

            response = api_client.get('/api/system/version')
            assert response.status_code == 500
            data = response.get_json()
            assert 'error' in data
            assert 'Version information not available' in data['error']

    def test_check_for_updates_available(self, api_client):
        """Test update check when updates are available"""
        with patch('core.api.load_version_info') as mock_load, \
             patch('core.api.get_commits_comparison') as mock_compare, \
             patch('core.api.get_latest_remote_commit') as mock_latest:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            # Note: ahead_by indicates how many commits the remote is ahead of our local commit
            mock_compare.return_value = ({
                'ahead_by': 5,
                'behind_by': 0,
                'status': 'behind',
                'commits': [
                    {'hash': '2b192g6', 'message': 'feat: add new feature', 'date': '2025-11-29T10:00:00Z'},
                    {'hash': 'abc1234', 'message': 'fix: bug fix', 'date': '2025-11-29T09:00:00Z'}
                ],
                'target_commit': '2b192g6'
            }, None)
            mock_latest.return_value = ({'sha': '2b192g6', 'message': 'feat: add new feature', 'date': '2025-11-29T10:00:00Z'}, None)

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is True
            assert data['commits_behind'] == 5
            assert data['current_commit'] == '1a081f5'
            assert data['remote_commit'] == '2b192g6'
            assert data['target_branch'] == 'main'
            assert len(data['preview_commits']) == 2
            assert data['preview_commits'][0]['hash'] == '2b192g6'
            assert data['preview_commits'][0]['message'] == 'feat: add new feature'

    def test_check_for_updates_up_to_date(self, api_client):
        """Test update check when already up to date"""
        with patch('core.api.load_version_info') as mock_load, \
             patch('core.api.get_commits_comparison') as mock_compare, \
             patch('core.api.get_latest_remote_commit') as mock_latest:

            mock_load.return_value = {**self.SAMPLE_VERSION_INFO, 'branch': 'main'}
            mock_compare.return_value = ({
                'ahead_by': 0,
                'behind_by': 0,
                'status': 'identical',
                'commits': [],
                'target_commit': '1a081f5'
            }, None)
            mock_latest.return_value = ({'sha': '1a081f5', 'message': 'fix: improve spectrogram display', 'date': '2025-11-28T08:49:00Z'}, None)

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is False
            assert data['commits_behind'] == 0
            assert data['preview_commits'] == []

    def test_check_for_updates_github_api_failure(self, api_client):
        """Test update check handles GitHub API failure"""
        with patch('core.api.load_version_info') as mock_load, \
             patch('core.api.get_commits_comparison') as mock_compare:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_compare.return_value = (None, "Network error")

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 500
            data = response.get_json()
            assert 'error' in data
            assert 'Failed to check for updates' in data['error']

    def test_check_for_updates_missing_version(self, api_client):
        """Test update check handles missing version.json"""
        with patch('core.api.load_version_info') as mock_load:
            mock_load.return_value = None

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 500
            data = response.get_json()
            assert 'Version information not available' in data['error']

    def test_trigger_update_success(self, api_client):
        """Test POST /api/system/update writes flag.

        Note: The trigger endpoint no longer checks GitHub API - frontend already
        verified update availability via /api/system/update-check before calling this.
        """
        with patch('core.api.load_version_info') as mock_load, \
             patch('core.api.write_flag') as mock_flag:

            mock_load.return_value = self.SAMPLE_VERSION_INFO

            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'update_triggered'
            assert data['estimated_downtime'] == '2-5 minutes'
            mock_flag.assert_called_once_with('update-requested')

    def test_trigger_update_detached_head(self, api_client):
        """Test POST /api/system/update rejects detached HEAD state"""
        with patch('core.api.load_version_info') as mock_load:
            mock_load.return_value = {**self.SAMPLE_VERSION_INFO, 'branch': 'HEAD'}

            response = api_client.post('/api/system/update')
            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data
            assert 'detached HEAD state' in data['error']

    def test_trigger_update_missing_version(self, api_client):
        """Test POST /api/system/update handles missing version.json"""
        with patch('core.api.load_version_info') as mock_load:
            mock_load.return_value = None

            response = api_client.post('/api/system/update')
            assert response.status_code == 500
            data = response.get_json()
            assert 'Version information not available' in data['error']

    def test_version_constant_exists(self):
        """Test that version module exists and has required attributes"""
        import version
        assert hasattr(version, '__version__')
        assert hasattr(version, '__version_info__')
        assert hasattr(version, 'DISPLAY_NAME')
        assert hasattr(version, 'TECHNICAL_NAME')
        assert version.__version__ == '0.1.0'
        assert version.__version_info__ == (0, 1, 0)
        assert version.DISPLAY_NAME == 'BirdNET-PiPy'
        assert version.TECHNICAL_NAME == 'birdnet-pipy'


class TestVersionHelpers:
    """Test helper functions for version management"""

    def test_load_version_info_success(self, tmp_path):
        """Test loading version.json successfully"""
        import json
        version_data = {
            'commit': 'abc1234',
            'commit_date': '2025-11-28T10:00:00Z',
            'branch': 'main',
            'remote_url': 'https://github.com/Suncuss/BirdNET-PiPy',
            'build_time': '2025-11-28T11:00:00Z'
        }

        # Create data directory and version file
        data_dir = tmp_path / 'data'
        data_dir.mkdir()
        version_file = data_dir / 'version.json'
        version_file.write_text(json.dumps(version_data))

        with patch('core.api.BASE_DIR', str(tmp_path)):
            from core.api import load_version_info
            result = load_version_info()
            assert result == version_data

    def test_load_version_info_missing_file(self, tmp_path):
        """Test loading version.json when file doesn't exist"""
        with patch('core.api.BASE_DIR', str(tmp_path)):
            from core.api import load_version_info
            result = load_version_info()
            assert result is None

    def test_call_github_api_success(self):
        """Test successful GitHub API call"""
        with patch('core.api.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {'sha': 'abc1234567890'}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.api import call_github_api
            result, error = call_github_api('commits/main')

            assert result == {'sha': 'abc1234567890'}
            assert error is None

    def test_call_github_api_timeout(self):
        """Test GitHub API timeout handling"""
        import requests

        with patch('core.api.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()

            from core.api import call_github_api
            result, error = call_github_api('commits/main')

            assert result is None
            assert 'timed out' in error.lower()

    def test_call_github_api_network_error(self):
        """Test GitHub API network error handling"""
        import requests

        with patch('core.api.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError('Network unreachable')

            from core.api import call_github_api
            result, error = call_github_api('commits/main')

            assert result is None
            assert 'GitHub API error' in error

    def test_get_commits_comparison_success(self):
        """Test successful commit comparison"""
        mock_response = {
            'ahead_by': 0,
            'behind_by': 3,
            'status': 'behind',
            'commits': [
                {
                    'sha': 'abc1234567890',
                    'commit': {
                        'message': 'feat: new feature\n\nDetailed description',
                        'committer': {'date': '2025-11-29T10:00:00Z'}
                    }
                }
            ]
        }

        with patch('core.api.call_github_api') as mock_api:
            mock_api.return_value = (mock_response, None)

            from core.api import get_commits_comparison
            result, error = get_commits_comparison('1a081f5', 'main')

            assert error is None
            assert result['behind_by'] == 3
            assert len(result['commits']) == 1
            assert result['commits'][0]['hash'] == 'abc1234'
            assert result['commits'][0]['message'] == 'feat: new feature'

    def test_get_latest_remote_commit_success(self):
        """Test successful latest commit fetch"""
        mock_response = {
            'sha': 'abc1234567890',
            'commit': {
                'message': 'Latest commit message',
                'committer': {'date': '2025-11-29T10:00:00Z'}
            }
        }

        with patch('core.api.call_github_api') as mock_api:
            mock_api.return_value = (mock_response, None)

            from core.api import get_latest_remote_commit
            result, error = get_latest_remote_commit('main')

            assert error is None
            assert result['sha'] == 'abc1234'
            assert result['message'] == 'Latest commit message'
