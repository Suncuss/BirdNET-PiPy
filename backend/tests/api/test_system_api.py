from unittest.mock import MagicMock, patch


class TestSystemAPI:
    """Test system update API endpoints"""

    # Sample version.json content
    SAMPLE_VERSION_INFO = {
        'version': '0.5.0',
        'commit': '1a081f5',
        'commit_date': '2025-11-28T08:49:00Z',
        'branch': 'develop',
        'remote_url': 'https://github.com/Suncuss/BirdNET-PiPy',
        'build_time': '2025-11-28T10:00:00Z'
    }

    def test_get_version_info_success(self, api_client):
        """Test GET /api/system/version returns version info"""
        with patch('core.routes.system.load_version_info') as mock_load:
            mock_load.return_value = self.SAMPLE_VERSION_INFO

            response = api_client.get('/api/system/version')
            assert response.status_code == 200
            data = response.get_json()
            assert data['version'] == '0.5.0'
            assert data['current_commit'] == '1a081f5'
            assert data['current_branch'] == 'develop'
            assert data['remote_url'] == 'https://github.com/Suncuss/BirdNET-PiPy'

    def test_get_version_info_missing_file(self, api_client):
        """Test GET /api/system/version handles missing version.json"""
        with patch('core.routes.system.load_version_info') as mock_load:
            mock_load.return_value = None

            response = api_client.get('/api/system/version')
            assert response.status_code == 500
            data = response.get_json()
            assert 'error' in data
            assert 'Version information not available' in data['error']

    def test_check_for_updates_available(self, api_client):
        """Test update check when updates are available"""
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.get_commits_comparison') as mock_compare, \
             patch('core.routes.system.get_latest_remote_commit') as mock_latest, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_channel.return_value = ('release', 'main')
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
            assert data['channel'] == 'release'
            assert len(data['preview_commits']) == 2
            assert data['preview_commits'][0]['hash'] == '2b192g6'
            assert data['preview_commits'][0]['message'] == 'feat: add new feature'

    def test_check_for_updates_up_to_date(self, api_client):
        """Test update check when already up to date"""
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.get_commits_comparison') as mock_compare, \
             patch('core.routes.system.get_latest_remote_commit') as mock_latest, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = {**self.SAMPLE_VERSION_INFO, 'branch': 'main'}
            mock_channel.return_value = ('release', 'main')
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
            assert data['channel'] == 'release'

    def test_check_for_updates_channel_switch_behind(self, api_client):
        """Test update check when switching channels and target is behind current.

        This happens when switching from latest (staging) back to release (main)
        where main is behind staging. Should still show update available.
        """
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.get_commits_comparison') as mock_compare, \
             patch('core.routes.system.get_latest_remote_commit') as mock_latest, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = {**self.SAMPLE_VERSION_INFO, 'branch': 'staging'}
            mock_channel.return_value = ('release', 'main')  # Switching to release
            # status='behind' means target (main) is behind current (staging)
            mock_compare.return_value = ({
                'ahead_by': 0,
                'behind_by': 5,
                'status': 'behind',
                'commits': [],
                'target_commit': 'older123'
            }, None)
            mock_latest.return_value = ({'sha': 'older123', 'message': 'older commit', 'date': '2025-11-25T10:00:00Z'}, None)

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            # Should show update available even though target is "behind"
            # because we're switching channels
            assert data['update_available'] is True
            assert data['channel'] == 'release'

    def test_check_for_updates_channel_switch_diverged(self, api_client):
        """Test update check when branches have diverged.

        This can happen if both branches have independent commits.
        Should show update available.
        """
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.get_commits_comparison') as mock_compare, \
             patch('core.routes.system.get_latest_remote_commit') as mock_latest, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_channel.return_value = ('latest', 'staging')
            # status='diverged' means branches have independent commits
            mock_compare.return_value = ({
                'ahead_by': 3,
                'behind_by': 2,
                'status': 'diverged',
                'commits': [{'hash': 'abc1234', 'message': 'staging commit', 'date': '2025-11-29T10:00:00Z'}],
                'target_commit': 'abc1234'
            }, None)
            mock_latest.return_value = ({'sha': 'abc1234', 'message': 'staging commit', 'date': '2025-11-29T10:00:00Z'}, None)

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 200
            data = response.get_json()
            assert data['update_available'] is True
            assert data['channel'] == 'latest'

    def test_check_for_updates_github_api_failure(self, api_client):
        """Test update check handles GitHub API failure"""
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.get_commits_comparison') as mock_compare, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_channel.return_value = ('release', 'main')
            mock_compare.return_value = (None, "Network error")

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 500
            data = response.get_json()
            assert 'error' in data
            assert 'Failed to check for updates' in data['error']
            assert 'Network error' in data['error']

    def test_check_for_updates_missing_version(self, api_client):
        """Test update check handles missing version.json"""
        with patch('core.routes.system.load_version_info') as mock_load:
            mock_load.return_value = None

            response = api_client.get('/api/system/update-check')
            assert response.status_code == 500
            data = response.get_json()
            assert 'Version information not available' in data['error']

    def test_trigger_update_success(self, api_client):
        """Test POST /api/system/update writes flag with target branch.

        Note: The trigger endpoint writes the target branch name to the flag file
        so the service script knows which branch to update to.
        """
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.write_flag') as mock_flag, \
             patch('core.routes.system.reset_update_status') as mock_reset, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_reset.return_value = 'pending'
            mock_channel.return_value = ('release', 'main')

            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'update_triggered'
            assert data['estimated_downtime'] == '2-5 minutes'
            assert data['channel'] == 'release'
            assert data['target_branch'] == 'main'
            # The responder is the OLD process; its boot_id serves as a late
            # identity baseline for the frontend's restart poll, and the
            # read-back status confirms the stale-value reset happened
            assert len(data['boot_id']) == 36
            assert data['update_status'] == 'pending'
            mock_flag.assert_called_once_with('update-requested', 'main')

    def test_trigger_update_latest_channel(self, api_client):
        """Test POST /api/system/update writes staging branch for latest channel"""
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.write_flag') as mock_flag, \
             patch('core.routes.system.reset_update_status') as mock_reset, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_reset.return_value = 'pending'
            mock_channel.return_value = ('latest', 'staging')

            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'update_triggered'
            assert data['channel'] == 'latest'
            assert data['target_branch'] == 'staging'
            mock_flag.assert_called_once_with('update-requested', 'staging')

    def test_trigger_update_resets_stale_update_state(self, api_client):
        """POST /api/system/update clears stale state from earlier attempts.

        The terminal status resets to 'pending' — a leftover 'failed' would be
        visible to the frontend's restart poll before install.sh overwrites
        it, producing an instant false "update failed" report — and the
        update-progress stage file is deleted so the banner's progress poll
        can't surface a stage from a previous attempt.
        """
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.write_flag'), \
             patch('core.routes.system.reset_update_status') as mock_reset, \
             patch('core.routes.system.reset_update_progress') as mock_progress, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_reset.return_value = 'pending'
            mock_channel.return_value = ('release', 'main')

            response = api_client.post('/api/system/update')
            assert response.status_code == 200
            mock_reset.assert_called_once()
            mock_progress.assert_called_once()

    def test_trigger_update_missing_version(self, api_client):
        """Test POST /api/system/update handles missing version.json"""
        with patch('core.routes.system.load_version_info') as mock_load:
            mock_load.return_value = None

            response = api_client.post('/api/system/update')
            assert response.status_code == 500
            data = response.get_json()
            assert 'Version information not available' in data['error']

    def test_trigger_restart_returns_boot_id(self, api_client):
        """POST /api/system/restart echoes the current process boot_id.

        The responder is the old process, so the frontend can use this as a
        late identity baseline when its /system/version capture failed.
        """
        with patch('core.routes.system.write_flag') as mock_flag:
            response = api_client.post('/api/system/restart')
            assert response.status_code == 200
            data = response.get_json()
            assert data['status'] == 'restart_requested'
            assert len(data['boot_id']) == 36
            mock_flag.assert_called_once_with('restart-backend')

    def test_version_includes_stable_boot_id(self, api_client):
        """GET /api/system/version returns a boot_id stable across requests.

        The frontend compares boot_id before/after a restart to detect that it
        is talking to a NEW server process, not the old one still shutting
        down. It must be constant for the process lifetime.
        """
        with patch('core.routes.system.load_version_info') as mock_load:
            mock_load.return_value = self.SAMPLE_VERSION_INFO

            first = api_client.get('/api/system/version').get_json()
            second = api_client.get('/api/system/version').get_json()

            assert first['boot_id']
            assert len(first['boot_id']) == 36  # uuid4 string form
            assert first['boot_id'] == second['boot_id']

    def test_version_includes_update_status(self, api_client):
        """GET /api/system/version surfaces the update-status flag content."""
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.read_update_status') as mock_status:
            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_status.return_value = 'failed'

            data = api_client.get('/api/system/version').get_json()
            assert data['update_status'] == 'failed'

    def test_version_update_status_none_without_flag(self, api_client):
        """update_status is null when no status flag file exists."""
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.read_update_status') as mock_status:
            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_status.return_value = None

            data = api_client.get('/api/system/version').get_json()
            assert data['update_status'] is None

    def test_version_constant_exists(self):
        """Test that version module exists and has required attributes"""
        import version
        assert hasattr(version, '__version__')
        assert hasattr(version, '__version_info__')
        assert hasattr(version, 'DISPLAY_NAME')
        assert hasattr(version, 'TECHNICAL_NAME')
        # Check format, not specific values (those change on each release)
        assert isinstance(version.__version__, str)
        assert len(version.__version__.split('.')) >= 2  # at least major.minor
        assert isinstance(version.__version_info__, tuple)
        assert len(version.__version_info__) >= 2
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

        with patch('core.update_service.BASE_DIR', str(tmp_path)):
            from core.update_service import load_version_info
            result = load_version_info()
            assert result == version_data

    def test_load_version_info_missing_file(self, tmp_path):
        """Test loading version.json when file doesn't exist"""
        with patch('core.update_service.BASE_DIR', str(tmp_path)):
            from core.update_service import load_version_info
            result = load_version_info()
            assert result is None

    def test_call_github_api_success(self):
        """Test successful GitHub API call"""
        with patch('core.update_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.json.return_value = {'sha': 'abc1234567890'}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.update_service import call_github_api
            result, error = call_github_api('commits/main')

            assert result == {'sha': 'abc1234567890'}
            assert error is None

    def test_call_github_api_timeout(self):
        """Test GitHub API timeout handling"""
        import requests

        with patch('core.update_service.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()

            from core.update_service import call_github_api
            result, error = call_github_api('commits/main')

            assert result is None
            assert 'timed out' in error.lower()

    def test_call_github_api_network_error(self):
        """Test GitHub API network error handling"""
        import requests

        with patch('core.update_service.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError('Network unreachable')

            from core.update_service import call_github_api
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

        with patch('core.update_service.call_github_api') as mock_api:
            mock_api.return_value = (mock_response, None)

            from core.update_service import get_commits_comparison
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

        with patch('core.update_service.call_github_api') as mock_api:
            mock_api.return_value = (mock_response, None)

            from core.update_service import get_latest_remote_commit
            result, error = get_latest_remote_commit('main')

            assert error is None
            assert result['sha'] == 'abc1234'
            assert result['message'] == 'Latest commit message'


class TestUpdateNotes:
    """Test update notes functionality"""

    def test_fetch_update_notes_success(self):
        """Test fetching UPDATE_NOTES.json with message"""

        with patch('core.update_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'message': 'Port changed from 8080 to 80!',
                'show_to_versions_before': 'abc1234'
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.update_service import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is not None
            assert result['message'] == 'Port changed from 8080 to 80!'
            assert result['show_to_versions_before'] == 'abc1234'

    def test_fetch_update_notes_empty_message(self):
        """Test fetching UPDATE_NOTES.json with null/empty message returns None"""
        with patch('core.update_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'message': None,
                'show_to_versions_before': None
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.update_service import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is None

    def test_fetch_update_notes_file_not_found(self):
        """Test fetching UPDATE_NOTES.json when file doesn't exist"""
        with patch('core.update_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_get.return_value = mock_response

            from core.update_service import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is None

    def test_fetch_update_notes_network_error(self):
        """Test fetching UPDATE_NOTES.json handles network errors"""
        import requests

        with patch('core.update_service.requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError('Network error')

            from core.update_service import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is None

    def test_fetch_update_notes_invalid_json(self):
        """Test fetching UPDATE_NOTES.json handles invalid JSON"""
        import json

        with patch('core.update_service.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.side_effect = json.JSONDecodeError('Invalid JSON', '', 0)
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            from core.update_service import fetch_update_notes
            result = fetch_update_notes('main')

            assert result is None

    def test_should_show_update_note_no_data(self):
        """Test should_show_update_note returns False for None data"""
        from core.update_service import should_show_update_note
        assert should_show_update_note('abc1234', None) is False

    def test_should_show_update_note_empty_message(self):
        """Test should_show_update_note returns False for empty message"""
        from core.update_service import should_show_update_note
        assert should_show_update_note('abc1234', {'message': '', 'show_to_versions_before': None}) is False

    def test_should_show_update_note_no_version_targeting(self):
        """Test should_show_update_note returns True when no version targeting"""
        from core.update_service import should_show_update_note
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
        with patch('core.update_service.get_commits_comparison') as mock_compare:
            mock_compare.return_value = ({
                'status': 'ahead',
                'behind_by': 0,
                'ahead_by': 5,
                'commits': []
            }, None)

            from core.update_service import should_show_update_note
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
        with patch('core.update_service.get_commits_comparison') as mock_compare:
            mock_compare.return_value = ({
                'status': 'behind',
                'behind_by': 3,
                'ahead_by': 0,
                'commits': []
            }, None)

            from core.update_service import should_show_update_note
            result = should_show_update_note('newer_commit', {
                'message': 'Port changed!',
                'show_to_versions_before': 'older_commit'
            })
            assert result is False

    def test_should_show_update_note_identical_commits(self):
        """Test should_show_update_note returns False when user is at exact target version

        'show_to_versions_before' means strictly before, not at or before.
        """
        with patch('core.update_service.get_commits_comparison') as mock_compare:
            mock_compare.return_value = ({
                'status': 'identical',
                'behind_by': 0,
                'ahead_by': 0,
                'commits': []
            }, None)

            from core.update_service import should_show_update_note
            result = should_show_update_note('abc1234', {
                'message': 'Port changed!',
                'show_to_versions_before': 'abc1234'
            })
            assert result is False

    def test_should_show_update_note_diverged_commits(self):
        """Test should_show_update_note returns True when commits diverged (safe default)"""
        with patch('core.update_service.get_commits_comparison') as mock_compare:
            mock_compare.return_value = ({
                'status': 'diverged',
                'behind_by': 2,
                'ahead_by': 3,
                'commits': []
            }, None)

            from core.update_service import should_show_update_note
            result = should_show_update_note('abc1234', {
                'message': 'Port changed!',
                'show_to_versions_before': 'def5678'
            })
            # Should return True to be safe when commits diverged
            assert result is True

    def test_should_show_update_note_comparison_error(self):
        """Test should_show_update_note returns True when comparison fails (safe default)"""
        with patch('core.update_service.get_commits_comparison') as mock_compare:
            mock_compare.return_value = (None, 'Comparison failed')

            from core.update_service import should_show_update_note
            result = should_show_update_note('abc1234', {
                'message': 'Port changed!',
                'show_to_versions_before': 'def5678'
            })
            # Should return True to be safe when comparison fails
            assert result is True


class TestUpdateCheckWithNotes:
    """Test update-check endpoint includes update notes"""

    SAMPLE_VERSION_INFO = {
        'version': '0.5.0',
        'commit': '1a081f5',
        'commit_date': '2025-11-28T08:49:00Z',
        'branch': 'develop',
        'remote_url': 'https://github.com/Suncuss/BirdNET-PiPy',
        'build_time': '2025-11-28T10:00:00Z'
    }

    def test_update_check_includes_update_note(self, api_client):
        """Test update-check includes update_note when available"""
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.get_commits_comparison') as mock_compare, \
             patch('core.routes.system.get_latest_remote_commit') as mock_latest, \
             patch('core.routes.system.fetch_update_notes') as mock_notes, \
             patch('core.routes.system.should_show_update_note') as mock_should_show, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_channel.return_value = ('release', 'main')
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
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.get_commits_comparison') as mock_compare, \
             patch('core.routes.system.get_latest_remote_commit') as mock_latest, \
             patch('core.routes.system.fetch_update_notes') as mock_notes, \
             patch('core.routes.system.should_show_update_note') as mock_should_show, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = self.SAMPLE_VERSION_INFO
            mock_channel.return_value = ('release', 'main')
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
        with patch('core.routes.system.load_version_info') as mock_load, \
             patch('core.routes.system.get_commits_comparison') as mock_compare, \
             patch('core.routes.system.get_latest_remote_commit') as mock_latest, \
             patch('core.routes.system.get_channel_branch') as mock_channel:

            mock_load.return_value = {**self.SAMPLE_VERSION_INFO, 'branch': 'main'}
            mock_channel.return_value = ('release', 'main')
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


class TestUpdateStatusHelpers:
    """Unit tests for the update-status flag helpers in core.update_service."""

    def _patched_service(self, monkeypatch, tmp_path):
        import core.update_service as update_service
        monkeypatch.setattr(update_service, 'BASE_DIR', str(tmp_path))
        return update_service

    def test_read_update_status_missing_file(self, tmp_path, monkeypatch):
        update_service = self._patched_service(monkeypatch, tmp_path)
        assert update_service.read_update_status() is None

    def test_read_update_status_strips_whitespace(self, tmp_path, monkeypatch):
        update_service = self._patched_service(monkeypatch, tmp_path)
        flags = tmp_path / 'data' / 'flags'
        flags.mkdir(parents=True)
        (flags / 'update-status').write_text('failed\n')
        assert update_service.read_update_status() == 'failed'

    def test_read_update_status_empty_file(self, tmp_path, monkeypatch):
        update_service = self._patched_service(monkeypatch, tmp_path)
        flags = tmp_path / 'data' / 'flags'
        flags.mkdir(parents=True)
        (flags / 'update-status').write_text('')
        assert update_service.read_update_status() is None

    def test_read_update_status_corrupt_bytes(self, tmp_path, monkeypatch):
        """A file corrupted mid-write (SD power loss) must read as None, not
        take the whole /system/version response down with a decode error."""
        update_service = self._patched_service(monkeypatch, tmp_path)
        flags = tmp_path / 'data' / 'flags'
        flags.mkdir(parents=True)
        (flags / 'update-status').write_bytes(b'\xff\xfe\x00garbage\x80')
        assert update_service.read_update_status() is None

    def test_reset_update_status_overwrites_stale_status(self, tmp_path, monkeypatch):
        """A leftover terminal status is replaced by 'pending' on dispatch.

        Removes-then-recreates so a root-owned file from install.sh (the flags
        dir itself is user-writable) cannot block the reset.
        """
        update_service = self._patched_service(monkeypatch, tmp_path)
        flags = tmp_path / 'data' / 'flags'
        flags.mkdir(parents=True)
        (flags / 'update-status').write_text('failed')

        update_service.reset_update_status()
        assert update_service.read_update_status() == 'pending'

    def test_reset_update_status_creates_from_scratch(self, tmp_path, monkeypatch):
        update_service = self._patched_service(monkeypatch, tmp_path)
        update_service.reset_update_status()
        assert update_service.read_update_status() == 'pending'

    def test_reset_update_status_returns_read_back_value(self, tmp_path, monkeypatch):
        """The dispatch response forwards this so the frontend knows the
        stale-value reset verifiably happened."""
        update_service = self._patched_service(monkeypatch, tmp_path)
        flags = tmp_path / 'data' / 'flags'
        flags.mkdir(parents=True)
        (flags / 'update-status').write_text('failed')

        assert update_service.reset_update_status() == 'pending'

    def test_reset_update_status_never_raises(self, tmp_path, monkeypatch):
        """Status is advisory: reset must not be able to block an update dispatch."""
        update_service = self._patched_service(monkeypatch, tmp_path)
        # Point BASE_DIR at a path whose parent is an unwritable *file*, so both
        # the unlink and the rewrite fail with OSError internally.
        blocker = tmp_path / 'blocker'
        blocker.write_text('')
        monkeypatch.setattr(update_service, 'BASE_DIR', str(blocker / 'nested'))
        update_service.reset_update_status()  # must simply not raise

    def test_reset_update_progress_removes_file(self, tmp_path, monkeypatch):
        update_service = self._patched_service(monkeypatch, tmp_path)
        flags = tmp_path / 'data' / 'flags'
        flags.mkdir(parents=True)
        stage_file = flags / 'update-progress'
        stage_file.write_text('{"stage":"pull","message":"Downloading updated images (1 of 3)"}')

        update_service.reset_update_progress()
        assert not stage_file.exists()

    def test_reset_update_progress_missing_file_is_fine(self, tmp_path, monkeypatch):
        update_service = self._patched_service(monkeypatch, tmp_path)
        update_service.reset_update_progress()  # must simply not raise

    def test_reset_update_progress_never_raises(self, tmp_path, monkeypatch):
        """Progress is advisory: reset must not be able to block a dispatch."""
        update_service = self._patched_service(monkeypatch, tmp_path)
        blocker = tmp_path / 'blocker'
        blocker.write_text('')
        monkeypatch.setattr(update_service, 'BASE_DIR', str(blocker / 'nested'))
        update_service.reset_update_progress()  # must simply not raise
