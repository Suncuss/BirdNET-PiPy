import pytest
from unittest.mock import patch, MagicMock

class TestSystemAPI:
    """Test system update API endpoints"""

    def test_get_version_info_success(self, api_client):
        """Test GET /api/system/version returns version info"""
        with patch('core.api.run_git_command') as mock_git:
            mock_git.side_effect = [
                '1a081f5',
                'fix: improve spectrogram display',
                '2025-11-28T08:49:00Z',
                'develop',
                'git@github.com:Suncuss/Birdnet-PiPy-archive.git'
            ]

            response = api_client.get('/api/system/version')
            assert response.status_code == 200
            data = response.get_json()
            assert data['current_commit'] == '1a081f5'
            assert data['current_commit_message'] == 'fix: improve spectrogram display'
            assert data['current_branch'] == 'develop'
            assert data['remote_url'] == 'git@github.com:Suncuss/Birdnet-PiPy-archive.git'

    def test_get_version_info_git_failure(self, api_client):
        """Test GET /api/system/version handles git command failure"""
        with patch('core.api.run_git_command') as mock_git:
            mock_git.side_effect = Exception('Git command failed')

            response = api_client.get('/api/system/version')
            assert response.status_code == 500
            data = response.get_json()
            assert 'error' in data
            assert 'Failed to get version info' in data['error']

    def test_check_for_updates_available(self, api_client):
        """Test update check when updates are available"""
        with patch('core.api.run_git_command') as mock_git:
            mock_git.side_effect = [
                None,  # git fetch (no output)
                '1a081f5',  # current commit
                '2b192g6',  # remote commit
                'develop',  # current branch
                '5',  # commits behind
                '2b192g6|feat: add new feature|2025-11-29T10:00:00Z\n' +
                'abc1234|fix: bug fix|2025-11-29T09:00:00Z'
            ]

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
        with patch('core.api.run_git_command') as mock_git:
            mock_git.side_effect = [
                None,  # git fetch
                '1a081f5',  # current commit
                '1a081f5',  # remote commit (same)
                'main',  # current branch
                '0',  # commits behind
            ]

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is False
            assert data['commits_behind'] == 0
            assert data['preview_commits'] == []

    def test_check_for_updates_git_failure(self, api_client):
        """Test update check handles git command failure"""
        with patch('core.api.run_git_command') as mock_git:
            mock_git.side_effect = Exception('Network error')

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 500
            data = response.get_json()
            assert 'error' in data
            assert 'Failed to check for updates' in data['error']

    def test_trigger_update_success(self, api_client):
        """Test POST /api/system/update writes flag"""
        with patch('core.api.run_git_command') as mock_git, \
             patch('core.api.write_flag') as mock_flag:
            mock_git.side_effect = [
                'develop',  # branch check
                '3'  # commits behind
            ]

            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'update_triggered'
            assert data['estimated_downtime'] == '2-5 minutes'
            assert data['commits_to_apply'] == 3
            mock_flag.assert_called_once_with('update-requested')

    def test_trigger_update_detached_head(self, api_client):
        """Test POST /api/system/update rejects detached HEAD state"""
        with patch('core.api.run_git_command') as mock_git:
            mock_git.return_value = 'HEAD'  # Detached HEAD state

            response = api_client.post('/api/system/update')
            assert response.status_code == 400
            data = response.get_json()
            assert 'error' in data
            assert 'detached HEAD state' in data['error']

    def test_trigger_update_already_up_to_date(self, api_client):
        """Test POST /api/system/update when already up to date"""
        with patch('core.api.run_git_command') as mock_git, \
             patch('core.api.write_flag') as mock_flag:
            mock_git.side_effect = [
                'main',  # branch check
                '0'  # no commits behind
            ]

            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'no_update_needed'
            assert 'already up to date' in data['message'].lower()
            mock_flag.assert_not_called()

    def test_trigger_update_git_failure(self, api_client):
        """Test POST /api/system/update handles git command failure"""
        with patch('core.api.run_git_command') as mock_git:
            mock_git.side_effect = Exception('Git error')

            response = api_client.post('/api/system/update')
            assert response.status_code == 500
            data = response.get_json()
            assert 'error' in data
            assert 'Failed to trigger update' in data['error']

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
