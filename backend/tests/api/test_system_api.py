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


class TestUpdateNotes:
    """Test update notes functionality"""

    def test_fetch_update_notes_success(self):
        """Test fetching UPDATE_NOTES.json with message"""
        import requests

        with patch('core.api.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'message': 'Port changed from 8080 to 80!',
                'show_to_versions_before': 'abc1234'
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.api import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is not None
            assert result['message'] == 'Port changed from 8080 to 80!'
            assert result['show_to_versions_before'] == 'abc1234'

    def test_fetch_update_notes_empty_message(self):
        """Test fetching UPDATE_NOTES.json with null/empty message returns None"""
        with patch('core.api.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'message': None,
                'show_to_versions_before': None
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.api import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is None

    def test_fetch_update_notes_file_not_found(self):
        """Test fetching UPDATE_NOTES.json when file doesn't exist"""
        with patch('core.api.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_get.return_value = mock_response

            from core.api import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is None

    def test_fetch_update_notes_network_error(self):
        """Test fetching UPDATE_NOTES.json handles network errors"""
        import requests

        with patch('core.api.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError('Network error')

            from core.api import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is None

    def test_fetch_update_notes_invalid_json(self):
        """Test fetching UPDATE_NOTES.json handles invalid JSON"""
        import json

        with patch('core.api.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.side_effect = json.JSONDecodeError('Invalid JSON', '', 0)
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.api import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is None

    def test_should_show_update_note_no_data(self):
        """Test should_show_update_note returns False for None data"""
        from core.api import should_show_update_note
        assert should_show_update_note('abc1234', None) is False

    def test_should_show_update_note_empty_message(self):
        """Test should_show_update_note returns False for empty message"""
        from core.api import should_show_update_note
        assert should_show_update_note('abc1234', {'message': '', 'show_to_versions_before': None}) is False

    def test_should_show_update_note_no_version_targeting(self):
        """Test should_show_update_note returns True when no version targeting"""
        from core.api import should_show_update_note
        result = should_show_update_note('abc1234', {
            'message': 'Important update!',
            'show_to_versions_before': None
        })
        assert result is True

    def test_should_show_update_note_user_behind_target(self):
        """Test should_show_update_note returns True when user is behind target version

        When user is on an older version, comparing current...target returns:
        - status: 'ahead' (target is ahead of current)
        - ahead_by > 0
        """
        with patch('core.api.get_commits_comparison') as mock_compare:
            mock_compare.return_value = ({
                'status': 'ahead',
                'behind_by': 0,
                'ahead_by': 5,
                'commits': []
            }, None)

            from core.api import should_show_update_note
            result = should_show_update_note('old_commit', {
                'message': 'Port changed!',
                'show_to_versions_before': 'newer_commit'
            })
            assert result is True

    def test_should_show_update_note_user_ahead_of_target(self):
        """Test should_show_update_note returns False when user is ahead of target version

        When user is on a newer version, comparing current...target returns:
        - status: 'behind' (target is behind current)
        - behind_by > 0
        """
        with patch('core.api.get_commits_comparison') as mock_compare:
            mock_compare.return_value = ({
                'status': 'behind',
                'behind_by': 3,
                'ahead_by': 0,
                'commits': []
            }, None)

            from core.api import should_show_update_note
            result = should_show_update_note('newer_commit', {
                'message': 'Port changed!',
                'show_to_versions_before': 'older_commit'
            })
            assert result is False

    def test_should_show_update_note_identical_commits(self):
        """Test should_show_update_note returns False when user is at exact target version

        'show_to_versions_before' means strictly before, not at or before.
        """
        with patch('core.api.get_commits_comparison') as mock_compare:
            mock_compare.return_value = ({
                'status': 'identical',
                'behind_by': 0,
                'ahead_by': 0,
                'commits': []
            }, None)

            from core.api import should_show_update_note
            result = should_show_update_note('abc1234', {
                'message': 'Port changed!',
                'show_to_versions_before': 'abc1234'
            })
            assert result is False

    def test_should_show_update_note_diverged_commits(self):
        """Test should_show_update_note returns True when commits diverged (safe default)"""
        with patch('core.api.get_commits_comparison') as mock_compare:
            mock_compare.return_value = ({
                'status': 'diverged',
                'behind_by': 2,
                'ahead_by': 3,
                'commits': []
            }, None)

            from core.api import should_show_update_note
            result = should_show_update_note('abc1234', {
                'message': 'Port changed!',
                'show_to_versions_before': 'def5678'
            })
            # Should return True to be safe when commits diverged
            assert result is True

    def test_should_show_update_note_comparison_error(self):
        """Test should_show_update_note returns True when comparison fails (safe default)"""
        with patch('core.api.get_commits_comparison') as mock_compare:
            mock_compare.return_value = (None, 'Comparison failed')

            from core.api import should_show_update_note
            result = should_show_update_note('abc1234', {
                'message': 'Port changed!',
                'show_to_versions_before': 'def5678'
            })
            # Should return True to be safe when comparison fails
            assert result is True


class TestUpdateCheckWithNotes:
    """Test update-check endpoint includes update notes"""

    SAMPLE_VERSION_INFO = {
        'commit': '1a081f5',
        'commit_date': '2025-11-28T08:49:00Z',
        'branch': 'develop',
        'remote_url': 'https://github.com/Suncuss/BirdNET-PiPy',
        'build_time': '2025-11-28T10:00:00Z'
    }

    def test_update_check_includes_update_note(self, api_client):
        """Test update-check includes update_note when available"""
        with patch('core.api.load_version_info') as mock_load, \
             patch('core.api.get_commits_comparison') as mock_compare, \
             patch('core.api.get_latest_remote_commit') as mock_latest, \
             patch('core.api.fetch_update_notes') as mock_notes, \
             patch('core.api.should_show_update_note') as mock_should_show:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            # Note: status 'ahead' means remote is ahead of local (update available)
            mock_compare.return_value = ({
                'ahead_by': 5,
                'behind_by': 0,
                'status': 'ahead',
                'commits': [{'hash': '2b192g6', 'message': 'feat: new feature', 'date': '2025-11-29T10:00:00Z'}],
                'target_commit': '2b192g6'
            }, None)
            mock_latest.return_value = ({'sha': '2b192g6', 'message': 'feat: new feature', 'date': '2025-11-29T10:00:00Z'}, None)
            mock_notes.return_value = {'message': 'Port changed to 80!', 'show_to_versions_before': 'abc123'}
            mock_should_show.return_value = True

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is True
            assert data['update_note'] == 'Port changed to 80!'

    def test_update_check_no_update_note_when_not_applicable(self, api_client):
        """Test update-check has null update_note when note doesn't apply"""
        with patch('core.api.load_version_info') as mock_load, \
             patch('core.api.get_commits_comparison') as mock_compare, \
             patch('core.api.get_latest_remote_commit') as mock_latest, \
             patch('core.api.fetch_update_notes') as mock_notes, \
             patch('core.api.should_show_update_note') as mock_should_show:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            # Note: status 'ahead' means remote is ahead of local (update available)
            mock_compare.return_value = ({
                'ahead_by': 5,
                'behind_by': 0,
                'status': 'ahead',
                'commits': [{'hash': '2b192g6', 'message': 'feat: new feature', 'date': '2025-11-29T10:00:00Z'}],
                'target_commit': '2b192g6'
            }, None)
            mock_latest.return_value = ({'sha': '2b192g6', 'message': 'feat: new feature', 'date': '2025-11-29T10:00:00Z'}, None)
            mock_notes.return_value = {'message': 'Port changed to 80!', 'show_to_versions_before': 'old123'}
            mock_should_show.return_value = False

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is True
            assert data['update_note'] is None

    def test_update_check_no_update_note_when_up_to_date(self, api_client):
        """Test update-check has null update_note when no update available"""
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
            mock_latest.return_value = ({'sha': '1a081f5', 'message': 'current', 'date': '2025-11-28T08:49:00Z'}, None)

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is False
            assert data['update_note'] is None
