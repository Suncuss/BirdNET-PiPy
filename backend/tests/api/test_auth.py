"""Tests for authentication endpoints and functionality."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest


class TestAuthEndpoints:
    """Test authentication API endpoints."""

    @pytest.fixture
    def auth_client(self):
        """Create a test client with temporary auth config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch auth config paths
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'):

                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client, tmpdir

    def test_auth_status_default_disabled(self, auth_client):
        """Test that auth is disabled by default."""
        client, _ = auth_client

        response = client.get('/api/auth/status')
        assert response.status_code == 200

        data = response.get_json()
        assert data['auth_enabled'] is False
        assert data['setup_complete'] is False
        assert data['authenticated'] is True  # When auth disabled, always authenticated

    def test_setup_creates_password(self, auth_client):
        """Test that setup creates password hash."""
        client, tmpdir = auth_client

        response = client.post('/api/auth/setup',
                              data=json.dumps({'password': 'testpass123'}),
                              content_type='application/json')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        # Verify auth.json was created
        auth_file = os.path.join(tmpdir, 'auth.json')
        assert os.path.exists(auth_file)

        with open(auth_file) as f:
            auth_config = json.load(f)
            assert auth_config['password_hash'] is not None
            assert auth_config['auth_enabled'] is True

    def test_setup_requires_password(self, auth_client):
        """Test that setup requires a password."""
        client, _ = auth_client

        response = client.post('/api/auth/setup',
                              data=json.dumps({}),
                              content_type='application/json')

        assert response.status_code == 400
        assert 'Password required' in response.get_json()['error']

    def test_setup_requires_min_length(self, auth_client):
        """Test that setup requires minimum password length."""
        client, _ = auth_client

        response = client.post('/api/auth/setup',
                              data=json.dumps({'password': 'short12'}),  # 7 chars, less than required 8
                              content_type='application/json')

        assert response.status_code == 400
        assert 'at least 8 characters' in response.get_json()['error']

    def test_setup_fails_if_already_setup(self, auth_client):
        """Test that setup fails if password already set."""
        client, _ = auth_client

        # First setup
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Second setup should fail
        response = client.post('/api/auth/setup',
                              data=json.dumps({'password': 'newpass456'}),
                              content_type='application/json')

        assert response.status_code == 400
        assert 'already set up' in response.get_json()['error']

    def test_login_with_correct_password(self, auth_client):
        """Test login with correct password."""
        client, _ = auth_client

        # Setup password first
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Logout first
        client.post('/api/auth/logout')

        # Login
        response = client.post('/api/auth/login',
                              data=json.dumps({'password': 'testpass123'}),
                              content_type='application/json')

        assert response.status_code == 200
        assert response.get_json()['success'] is True

    def test_login_with_wrong_password(self, auth_client):
        """Test login with wrong password."""
        client, _ = auth_client

        # Setup password first
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Logout
        client.post('/api/auth/logout')

        # Login with wrong password
        response = client.post('/api/auth/login',
                              data=json.dumps({'password': 'wrongpass'}),
                              content_type='application/json')

        assert response.status_code == 401
        assert 'Invalid password' in response.get_json()['error']

    def test_login_fails_without_setup(self, auth_client):
        """Test that login fails if password not set up."""
        client, _ = auth_client

        response = client.post('/api/auth/login',
                              data=json.dumps({'password': 'anypass'}),
                              content_type='application/json')

        assert response.status_code == 400
        assert 'not configured' in response.get_json()['error']

    def test_logout_clears_session(self, auth_client):
        """Test that logout clears the session."""
        client, _ = auth_client

        # Setup and login
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Verify authenticated
        response = client.get('/api/auth/status')
        assert response.get_json()['authenticated'] is True

        # Logout
        response = client.post('/api/auth/logout')
        assert response.status_code == 200

        # Verify no longer authenticated
        response = client.get('/api/auth/status')
        assert response.get_json()['authenticated'] is False

    def test_verify_returns_200_when_authenticated(self, auth_client):
        """Test that verify returns 200 when authenticated."""
        client, _ = auth_client

        # Setup and auto-login
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        response = client.get('/api/auth/verify')
        assert response.status_code == 200

    def test_verify_returns_401_when_not_authenticated(self, auth_client):
        """Test that verify returns 401 when not authenticated."""
        client, _ = auth_client

        # Setup password
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Logout
        client.post('/api/auth/logout')

        response = client.get('/api/auth/verify')
        assert response.status_code == 401

    def test_verify_returns_200_when_auth_disabled(self, auth_client):
        """Test that verify returns 200 when auth is disabled."""
        client, _ = auth_client

        # Auth disabled by default
        response = client.get('/api/auth/verify')
        assert response.status_code == 200


class TestProtectedRoutes:
    """Test that protected routes require authentication."""

    @pytest.fixture
    def auth_client_with_settings(self):
        """Create a test client with auth enabled and mock settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'), \
                 patch('core.api.load_user_settings') as mock_load:

                mock_load.return_value = {
                    'audio': {'recording_mode': 'pulseaudio'},
                    'location': {'latitude': 40.0, 'longitude': -75.0}
                }

                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client, tmpdir

    def test_settings_allowed_when_auth_disabled(self, auth_client_with_settings):
        """Test that settings are accessible when auth is disabled."""
        client, _ = auth_client_with_settings

        response = client.get('/api/settings')
        assert response.status_code == 200

    def test_settings_blocked_when_not_authenticated(self, auth_client_with_settings):
        """Test that settings are blocked when auth enabled but not logged in."""
        client, _ = auth_client_with_settings

        # Setup password (enables auth)
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Logout
        client.post('/api/auth/logout')

        # Try to access settings
        response = client.get('/api/settings')
        assert response.status_code == 401

    def test_settings_allowed_when_authenticated(self, auth_client_with_settings):
        """Test that settings are accessible when authenticated."""
        client, _ = auth_client_with_settings

        # Setup password (enables auth and auto-logins)
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Access settings
        response = client.get('/api/settings')
        assert response.status_code == 200


class TestPasswordReset:
    """Test password reset functionality."""

    @pytest.fixture
    def auth_client_for_reset(self):
        """Create a test client for reset testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = os.path.join(tmpdir, 'auth.json')
            reset_file = os.path.join(tmpdir, 'RESET_PASSWORD')

            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', auth_file), \
                 patch('core.auth.RESET_PASSWORD_FILE', reset_file), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'):

                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client, tmpdir, auth_file, reset_file

    def test_password_reset_file_clears_auth(self, auth_client_for_reset):
        """Test that reset file clears authentication."""
        client, tmpdir, auth_file, reset_file = auth_client_for_reset

        # Setup password
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        assert os.path.exists(auth_file)

        # Create reset file
        with open(reset_file, 'w') as f:
            f.write('')

        # Any auth request should trigger reset
        response = client.get('/api/auth/status')

        # Auth should be reset (no password, disabled)
        data = response.get_json()
        assert data['setup_complete'] is False
        assert data['auth_enabled'] is False

        # Reset file should be deleted
        assert not os.path.exists(reset_file)


class TestAuthToggle:
    """Test authentication toggle functionality."""

    @pytest.fixture
    def auth_client(self):
        """Create a test client with temporary auth config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'):

                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client, tmpdir

    def test_toggle_auth_on(self, auth_client):
        """Test enabling authentication."""
        client, tmpdir = auth_client

        # Setup password first
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Disable auth
        client.post('/api/auth/toggle',
                   data=json.dumps({'enabled': False}),
                   content_type='application/json')

        # Verify disabled
        response = client.get('/api/auth/status')
        assert response.get_json()['auth_enabled'] is False

        # Enable auth
        response = client.post('/api/auth/toggle',
                              data=json.dumps({'enabled': True}),
                              content_type='application/json')

        assert response.status_code == 200
        assert response.get_json()['auth_enabled'] is True

    def test_toggle_requires_auth(self, auth_client):
        """Test that toggle requires authentication when auth is enabled."""
        client, _ = auth_client

        # Setup and enable auth
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Logout
        client.post('/api/auth/logout')

        # Try to toggle - should fail
        response = client.post('/api/auth/toggle',
                              data=json.dumps({'enabled': False}),
                              content_type='application/json')

        assert response.status_code == 401

    def test_toggle_enable_without_setup_fails(self, auth_client):
        """Test that enabling auth without password setup fails."""
        client, _ = auth_client

        # Try to enable auth without setting up password first
        response = client.post('/api/auth/toggle',
                              data=json.dumps({'enabled': True}),
                              content_type='application/json')

        assert response.status_code == 400
        assert 'without setting a password' in response.get_json()['error']

        # Verify auth is still disabled
        response = client.get('/api/auth/status')
        assert response.get_json()['auth_enabled'] is False


class TestChangePassword:
    """Test password change functionality."""

    @pytest.fixture
    def auth_client(self):
        """Create a test client with temporary auth config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'):

                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client

    def test_change_password_success(self, auth_client):
        """Test successful password change."""
        client = auth_client

        # Setup password
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'oldpass123'}),
                   content_type='application/json')

        # Change password
        response = client.post('/api/auth/change-password',
                              data=json.dumps({
                                  'current_password': 'oldpass123',
                                  'new_password': 'newpass456'
                              }),
                              content_type='application/json')

        assert response.status_code == 200

        # Logout and login with new password
        client.post('/api/auth/logout')

        response = client.post('/api/auth/login',
                              data=json.dumps({'password': 'newpass456'}),
                              content_type='application/json')
        assert response.status_code == 200

    def test_change_password_wrong_current(self, auth_client):
        """Test password change with wrong current password."""
        client = auth_client

        # Setup password
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'oldpass123'}),
                   content_type='application/json')

        # Try to change with wrong current password
        response = client.post('/api/auth/change-password',
                              data=json.dumps({
                                  'current_password': 'wrongpass',
                                  'new_password': 'newpass456'
                              }),
                              content_type='application/json')

        assert response.status_code == 400
        assert 'incorrect' in response.get_json()['error']

    def test_change_password_requires_auth(self, auth_client):
        """Test that password change requires authentication."""
        client = auth_client

        # Setup and logout
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'oldpass123'}),
                   content_type='application/json')
        client.post('/api/auth/logout')

        # Try to change password while logged out
        response = client.post('/api/auth/change-password',
                              data=json.dumps({
                                  'current_password': 'oldpass123',
                                  'new_password': 'newpass456'
                              }),
                              content_type='application/json')

        assert response.status_code == 401


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.fixture
    def auth_client(self):
        """Create a test client with temporary auth config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api.db_manager'), \
                 patch('core.api.socketio'):

                # Reset rate limiting state before each test
                import core.auth
                core.auth._login_attempts.clear()

                from core.api import create_app
                app, _ = create_app()
                app.config['TESTING'] = True

                with app.test_client() as client:
                    yield client

    def test_rate_limit_after_failed_attempts(self, auth_client):
        """Test that rate limiting kicks in after max failed attempts."""
        client = auth_client

        # Setup password
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Logout
        client.post('/api/auth/logout')

        # Make max failed login attempts (5 by default)
        for _i in range(5):
            response = client.post('/api/auth/login',
                                  data=json.dumps({'password': 'wrongpassword'}),
                                  content_type='application/json')
            assert response.status_code == 401

        # Next attempt should be rate limited
        response = client.post('/api/auth/login',
                              data=json.dumps({'password': 'wrongpassword'}),
                              content_type='application/json')

        assert response.status_code == 429
        assert 'Too many' in response.get_json()['error']

    def test_successful_login_clears_attempts(self, auth_client):
        """Test that successful login clears failed attempts."""
        client = auth_client

        # Setup password
        client.post('/api/auth/setup',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

        # Logout
        client.post('/api/auth/logout')

        # Make some failed attempts (less than max)
        for _ in range(3):
            client.post('/api/auth/login',
                       data=json.dumps({'password': 'wrongpassword'}),
                       content_type='application/json')

        # Successful login
        response = client.post('/api/auth/login',
                              data=json.dumps({'password': 'testpass123'}),
                              content_type='application/json')
        assert response.status_code == 200

        # Logout and try again - should not be rate limited
        client.post('/api/auth/logout')

        for _ in range(3):
            response = client.post('/api/auth/login',
                                  data=json.dumps({'password': 'wrongpassword'}),
                                  content_type='application/json')
            assert response.status_code == 401  # Not 429
