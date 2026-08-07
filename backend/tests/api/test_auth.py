"""Tests for authentication endpoints and functionality."""

import json
import os
import tempfile
import threading
from unittest.mock import MagicMock, patch

import pytest

from tests.api.conftest import sandboxed_auth_env


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
                 patch('core.api_infra.db_manager'), \
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

    def test_session_cookie_secure_tracks_request_scheme(self, auth_client):
        """The session cookie's Secure flag is per-request: set when the
        request arrived over HTTPS (X-Forwarded-Proto from a TLS-terminating
        proxy), clear over plain HTTP so http://pi logins keep working."""
        client, _ = auth_client

        client.post('/api/auth/setup',
                    data=json.dumps({'password': 'testpass123'}),
                    content_type='application/json')
        client.post('/api/auth/logout')

        plain = client.post('/api/auth/login',
                            data=json.dumps({'password': 'testpass123'}),
                            content_type='application/json')
        plain_cookie = plain.headers.get('Set-Cookie', '')
        assert 'birdnet_session' in plain_cookie
        assert 'Secure' not in plain_cookie

        client.post('/api/auth/logout')
        https = client.post('/api/auth/login',
                            data=json.dumps({'password': 'testpass123'}),
                            content_type='application/json',
                            headers={'X-Forwarded-Proto': 'https'})
        https_cookie = https.headers.get('Set-Cookie', '')
        assert 'birdnet_session' in https_cookie
        assert 'Secure' in https_cookie

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
                 patch('core.api_infra.db_manager'), \
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
                 patch('core.api_infra.db_manager'), \
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
                 patch('core.api_infra.db_manager'), \
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
                 patch('core.api_infra.db_manager'), \
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


class TestSessionEviction:
    """Changing the password must evict other devices' sessions.

    Sessions are stateless signed cookies, so without an epoch stamp a captured
    cookie stays valid forever and changing the password — the one remediation
    the UI offers — evicts nobody.
    """

    @pytest.fixture
    def auth_app(self):
        """Yield the app itself, so a test can hold two independent clients.

        sandboxed_auth_env also redirects USER_SETTINGS_PATH, which a
        hand-rolled auth-only patch block would leave pointing at the
        developer's real settings file.
        """
        with sandboxed_auth_env() as (api_module, _):
            app, _ = api_module.create_app()
            app.config['TESTING'] = True
            yield app

    @staticmethod
    def _setup(client, password='oldpass123'):
        client.post('/api/auth/setup',
                    data=json.dumps({'password': password}),
                    content_type='application/json')

    @staticmethod
    def _change(client, current='oldpass123', new='newpass456'):
        return client.post('/api/auth/change-password',
                           data=json.dumps({'current_password': current,
                                            'new_password': new}),
                           content_type='application/json')

    @staticmethod
    def _authenticated(client):
        return client.get('/api/auth/status').get_json()['authenticated']

    def test_password_change_evicts_other_sessions(self, auth_app):
        # Plain clients, not `with` blocks: nesting two test_client context
        # managers unwinds their request contexts out of order.
        owner = auth_app.test_client()
        other = auth_app.test_client()
        self._setup(owner)

        # A second device signs in with the old password.
        other.post('/api/auth/login',
                   data=json.dumps({'password': 'oldpass123'}),
                   content_type='application/json')
        assert self._authenticated(other) is True

        assert self._change(owner).status_code == 200

        assert self._authenticated(other) is False

    def test_password_change_keeps_the_caller_signed_in(self, auth_app):
        """The caller just proved knowledge of the password — don't log them
        out of the page they are standing on."""
        owner = auth_app.test_client()
        self._setup(owner)
        assert self._change(owner).status_code == 200
        assert self._authenticated(owner) is True

    def test_sessions_predating_the_epoch_stay_valid(self, auth_app):
        """Upgrade path: a cookie minted before this change carries no epoch,
        and a config written before it has no session_epoch. Both read as 0, so
        deploying the fix must not sign the owner out."""
        import core.auth as auth_module

        owner = auth_app.test_client()
        self._setup(owner)

        # Reconstruct the genuine pre-upgrade state: config written by the old
        # code (no session_epoch) and a cookie minted by it (no epoch).
        config = auth_module.load_auth_config()
        config.pop('session_epoch', None)
        auth_module.save_auth_config(config)
        with owner.session_transaction() as sess:
            sess.pop('epoch', None)

        assert self._authenticated(owner) is True

    def test_epoch_is_never_rewound_by_a_password_reset(self, auth_app):
        """RESET_PASSWORD deletes auth.json, so a counter would restart at 0 and
        revalidate cookies an earlier password change had evicted. The epoch is
        wall-clock, so a config rebuilt from scratch still outranks them."""
        import core.auth as auth_module

        owner = auth_app.test_client()
        other = auth_app.test_client()
        self._setup(owner)
        other.post('/api/auth/login',
                   data=json.dumps({'password': 'oldpass123'}),
                   content_type='application/json')
        self._change(owner)
        assert self._authenticated(other) is False

        # Owner forgets the new password and uses the documented recovery.
        with open(auth_module.RESET_PASSWORD_FILE, 'w') as f:
            f.write('reset')
        auth_module.check_password_reset()
        self._setup(owner, password='recovered123')

        # The evicted session must NOT come back from the dead.
        assert self._authenticated(other) is False

    def test_password_change_rotates_capability_secrets(self, auth_app):
        """A stolen session can mint signed media URLs (24-48h) and share
        tokens (30 days), neither of which carries the session epoch. Evicting
        the cookie alone would leave those working."""
        import core.auth as auth_module

        owner = auth_app.test_client()
        self._setup(owner)
        before = (auth_module.get_or_create_media_secret(),
                  auth_module.get_or_create_share_secret())

        self._change(owner)

        after = (auth_module.get_or_create_media_secret(),
                 auth_module.get_or_create_share_secret())
        assert after[0] != before[0]
        assert after[1] != before[1]

    def test_media_signatures_stop_verifying_after_a_change(self, auth_app):
        """The rotation only bites if the cached secret is dropped too —
        otherwise the process keeps signing with the revoked one."""
        import core.media_access as media_access

        owner = auth_app.test_client()
        self._setup(owner)
        stale = media_access.sign_media_query('clip.mp3')
        exp, sig = (p.split('=', 1)[1] for p in stale.split('&'))
        assert media_access.verify_media_signature('clip.mp3', exp, sig) is True

        self._change(owner)

        assert media_access.verify_media_signature('clip.mp3', exp, sig) is False

    def test_eviction_applies_to_every_gate(self, auth_app):
        """is_authenticated() is not the only gate: require_auth and
        require_feature used to read session['authenticated'] directly, so an
        evicted session kept passing them. Assert the eviction reaches an
        owner-gated route and a feature-gated one, not just /auth/status."""
        owner = auth_app.test_client()
        other = auth_app.test_client()
        self._setup(owner)
        other.post('/api/auth/login',
                   data=json.dumps({'password': 'oldpass123'}),
                   content_type='application/json')
        # require_auth route, and a require_feature route with the feature off.
        assert other.get('/api/settings').status_code == 200
        assert other.get('/api/stream/config').status_code == 200

        self._change(owner)

        assert other.get('/api/settings').status_code == 401
        assert other.get('/api/stream/config').status_code == 401
        # The owner who made the change keeps working.
        assert owner.get('/api/settings').status_code == 200


class TestAuthConfigDurability:
    """An unreadable auth.json must not become a permanent auth wipe."""

    def test_unreadable_config_is_never_overwritten(self):
        """A corrupt-but-present auth.json makes load fall through to the
        auth-disabled defaults. Persisting those would replace a real password
        hash with nulls, turning a transient read failure into permanent loss —
        so secret creation serves an ephemeral value and leaves the file alone.
        """
        import core.auth as auth_module

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = os.path.join(tmpdir, 'auth.json')
            truncated = '{"password_hash": "trunc'
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', auth_file), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET')):
                auth_module.setup_password('realpass123')
                assert 'password_hash' in json.loads(open(auth_file).read())

                # Simulate the post-power-cut state: present but unparseable.
                with open(auth_file, 'w') as f:
                    f.write(truncated)

                secret = auth_module.get_or_create_media_secret()

                assert secret  # usable for this process
                assert open(auth_file).read() == truncated

    def test_unreadable_config_blocks_anonymous_takeover(self):
        """With the config unreadable, auth reads as disabled and
        is_setup_complete() reads None — so /api/auth/setup, which is
        anonymously reachable, would otherwise let a visitor claim the station
        and destroy the owner's real credentials."""
        import core.auth as auth_module

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = os.path.join(tmpdir, 'auth.json')
            truncated = '{"password_hash": "trunc'
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', auth_file), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET')):
                auth_module.setup_password('realpass123')
                with open(auth_file, 'w') as f:
                    f.write(truncated)

                with pytest.raises(ValueError, match='could not be read'):
                    auth_module.setup_password('attacker99')
                with pytest.raises(RuntimeError, match='could not be read'):
                    auth_module.set_auth_enabled(False)

                assert open(auth_file).read() == truncated

    @pytest.mark.parametrize('payload', ['null', '123', '"x"', '[]'])
    def test_wrong_shape_config_is_treated_as_unreadable(self, payload):
        """Valid JSON of the wrong shape must not reach dict().

        `null`/scalars would raise TypeError out of every auth check (500 on
        every request, replayed from the cache), and `[]` would yield an empty
        config that reads as legitimate — so the write-guard would let it be
        written back over the real one.
        """
        import core.auth as auth_module

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = os.path.join(tmpdir, 'auth.json')
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', auth_file), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET')):
                auth_module.setup_password('realpass123')
                with open(auth_file, 'w') as f:
                    f.write(payload)

                # Auth checks stay callable instead of raising.
                assert auth_module.is_auth_enabled() is False
                assert auth_module.is_setup_complete() is False

                # ...and the file is still guarded against every writer.
                assert auth_module.get_or_create_media_secret()
                with pytest.raises(ValueError, match='could not be read'):
                    auth_module.setup_password('attacker99')

                assert open(auth_file).read() == payload

    def test_config_is_fsynced_before_publish(self):
        """The rename is only atomic if the bytes are on disk first: without
        the fsync a power cut can publish an empty auth.json, which reads as
        'auth disabled' everywhere downstream."""
        import core.auth as auth_module

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET')), \
                 patch('core.secure_file.os.fsync', wraps=os.fsync) as mock_fsync:
                auth_module.save_auth_config({'password_hash': 'x'})

            assert mock_fsync.called

    def test_secret_mint_cannot_overwrite_a_password_change(self):
        """All auth.json mutations must share one read-modify-write lock.

        A first media-secret mint used to load the old config, pause before its
        save, and then overwrite a completed password change with that stale
        password hash, epoch, and secret set.
        """
        from flask import Flask

        import core.auth as auth_module

        app = Flask(__name__)
        app.secret_key = 'auth-race-test'

        with tempfile.TemporaryDirectory() as tmpdir:
            auth_file = os.path.join(tmpdir, 'auth.json')
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', auth_file), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET')):
                auth_module.save_auth_config({
                    'password_hash': 'old-hash',
                    'auth_enabled': True,
                    'session_epoch': 1,
                })

                mint_saving = threading.Event()
                release_mint = threading.Event()
                change_done = threading.Event()
                errors = []
                original_save = auth_module._save_auth_config

                def pause_stale_mint(config):
                    if (config.get('password_hash') == 'old-hash'
                            and config.get('media_secret')
                            and not config.get('share_secret')):
                        mint_saving.set()
                        if not release_mint.wait(timeout=2):
                            raise TimeoutError('password change did not reach the forced race')
                    return original_save(config)

                def mint_secret():
                    try:
                        auth_module.get_or_create_media_secret()
                    except Exception as exc:  # surfaced in the main test thread
                        errors.append(exc)

                def change_password():
                    try:
                        with app.test_request_context():
                            auth_module.change_password('old-password', 'new-password')
                    except Exception as exc:  # surfaced in the main test thread
                        errors.append(exc)
                    finally:
                        change_done.set()

                with patch('core.auth._save_auth_config', side_effect=pause_stale_mint), \
                     patch('core.auth.verify_password', return_value=True), \
                     patch('core.auth.hash_password', return_value='new-hash'):
                    mint_thread = threading.Thread(target=mint_secret)
                    mint_thread.start()
                    assert mint_saving.wait(timeout=2)

                    change_thread = threading.Thread(target=change_password)
                    change_thread.start()
                    assert not change_done.wait(timeout=0.1)

                    release_mint.set()
                    mint_thread.join(timeout=2)
                    change_thread.join(timeout=2)

                assert not mint_thread.is_alive()
                assert not change_thread.is_alive()
                assert not errors
                final_config = auth_module.load_auth_config(check_reset=False)
                assert final_config['password_hash'] == 'new-hash'
                assert final_config['session_epoch'] > 1
                assert final_config.get('media_secret')
                assert final_config.get('share_secret')


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.fixture
    def auth_client(self):
        """Create a test client with temporary auth config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
                 patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
                 patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
                 patch('core.api_infra.db_manager'), \
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


class TestFeatureAccess:
    """Test per-feature access control."""

    @pytest.fixture
    def feature_client(self):
        """Create a test client with auth enabled, writable settings, and mock DB."""
        settings = {
            'audio': {'recording_mode': 'pulseaudio'},
            'location': {'latitude': 40.0, 'longitude': -75.0},
            'access': {
                'charts_public': False,
                'table_public': False,
                'live_feed_public': False
            }
        }
        mock_db = MagicMock()
        mock_db.get_hourly_activity.return_value = []
        mock_db.get_paginated_detections.return_value = ([], 0)

        with sandboxed_auth_env(mock_db, settings) as (api_module, settings_file):
            app, _ = api_module.create_app()
            app.config['TESTING'] = True

            with app.test_client() as client:
                # Setup auth and enable it
                client.post('/api/auth/setup',
                           data=json.dumps({'password': 'testpass123'}),
                           content_type='application/json')
                # Logout to test unauthenticated access
                client.post('/api/auth/logout')

                yield client, settings_file

    def _login(self, client):
        """Helper to login."""
        client.post('/api/auth/login',
                   data=json.dumps({'password': 'testpass123'}),
                   content_type='application/json')

    def _set_access(self, settings_file, **kwargs):
        """Helper to update access settings directly."""
        with open(settings_file) as f:
            data = json.load(f)
        if 'access' not in data:
            data['access'] = {'charts_public': False, 'table_public': False, 'live_feed_public': False}
        data['access'].update(kwargs)
        with open(settings_file, 'w') as f:
            json.dump(data, f)

    def _set_sources(self, settings_file, sources):
        """Helper to set audio.sources directly.

        Drops the legacy recording_mode key too: leaving it makes
        _migrate_audio_sources treat the file as pre-sources and replace these
        sources with a generated 'Local Mic'.
        """
        with open(settings_file) as f:
            data = json.load(f)
        audio = data.setdefault('audio', {})
        audio.pop('recording_mode', None)
        audio['sources'] = sources
        with open(settings_file, 'w') as f:
            json.dump(data, f)

    def test_public_features_default_empty(self, feature_client):
        """auth/status returns empty public_features by default."""
        client, _ = feature_client
        response = client.get('/api/auth/status')
        data = response.get_json()
        assert data['public_features'] == []

    def test_charts_protected_when_auth_enabled(self, feature_client):
        """GET /api/activity/hourly returns 401 when not authenticated."""
        client, _ = feature_client
        response = client.get('/api/activity/hourly')
        assert response.status_code == 401

    def test_charts_accessible_when_public(self, feature_client):
        """GET /api/activity/hourly returns 200 when charts_public is true."""
        client, settings_file = feature_client
        self._set_access(settings_file, charts_public=True)
        response = client.get('/api/activity/hourly')
        assert response.status_code == 200

    def test_table_protected_when_auth_enabled(self, feature_client):
        """GET /api/detections returns 401 when not authenticated."""
        client, _ = feature_client
        response = client.get('/api/detections')
        assert response.status_code == 401

    def test_table_accessible_when_public(self, feature_client):
        """GET /api/detections returns 200 when table_public is true."""
        client, settings_file = feature_client
        self._set_access(settings_file, table_public=True)
        response = client.get('/api/detections')
        assert response.status_code == 200

    def test_stream_config_protected(self, feature_client):
        """GET /api/stream/config returns 401 when not authenticated."""
        client, _ = feature_client
        response = client.get('/api/stream/config')
        assert response.status_code == 401

    def test_stream_config_accessible_when_public(self, feature_client):
        """GET /api/stream/config returns 200 when live_feed_public is true."""
        client, settings_file = feature_client
        self._set_access(settings_file, live_feed_public=True)
        response = client.get('/api/stream/config')
        assert response.status_code == 200

    def test_stream_config_hides_source_labels_from_anonymous(self, feature_client):
        """Owner-chosen labels can name the property or the mic's placement in
        it, which is why _strip_public_metadata drops source_label and
        /api/recorder/status is owner-only. Anonymous live-feed listeners get a
        positional name; the owner keeps their own."""
        client, settings_file = feature_client
        self._set_access(settings_file, live_feed_public=True)
        self._set_sources(settings_file, [
            {'id': 'source_0', 'type': 'pulseaudio', 'enabled': True,
             'label': 'Nursery window'},
            {'id': 'source_1', 'type': 'rtsp', 'enabled': True,
             'url': 'rtsp://cam/1', 'label': 'Elm Street feeder'},
        ])

        anon = client.get('/api/stream/config').get_json()['streams']
        assert [s['label'] for s in anon] == ['Source 1', 'Source 2']
        # The stream is still selectable — only the name is clamped.
        assert [s['source_id'] for s in anon] == ['source_0', 'source_1']

        self._login(client)
        owner = client.get('/api/stream/config').get_json()['streams']
        assert [s['label'] for s in owner] == ['Nursery window', 'Elm Street feeder']

    def test_auth_verify_allows_stream_when_public(self, feature_client):
        """auth/verify returns 200 for /stream/ URIs when live_feed is public."""
        client, settings_file = feature_client
        self._set_access(settings_file, live_feed_public=True)
        response = client.get('/api/auth/verify',
                             headers={'X-Original-URI': '/stream/stream.mp3'})
        assert response.status_code == 200

    def test_auth_verify_blocks_stream_when_private(self, feature_client):
        """auth/verify returns 401 for /stream/ URIs when live_feed is private."""
        client, _ = feature_client
        response = client.get('/api/auth/verify',
                             headers={'X-Original-URI': '/stream/stream.mp3'})
        assert response.status_code == 401

    def test_export_always_requires_auth(self, feature_client):
        """Export still requires auth even when table is public."""
        client, settings_file = feature_client
        self._set_access(settings_file, table_public=True)
        response = client.get('/api/detections/export')
        assert response.status_code == 401

    def test_delete_always_requires_auth(self, feature_client):
        """Delete still requires auth even when table is public."""
        client, settings_file = feature_client
        self._set_access(settings_file, table_public=True)
        response = client.delete('/api/detections/1')
        assert response.status_code == 401

    def test_settings_always_requires_auth(self, feature_client):
        """Settings endpoint requires auth regardless of feature toggles."""
        client, settings_file = feature_client
        self._set_access(settings_file, charts_public=True, table_public=True, live_feed_public=True)
        response = client.get('/api/settings')
        assert response.status_code == 401

    def test_save_access_requires_auth(self, feature_client):
        """PUT /api/settings/access requires authentication."""
        client, _ = feature_client
        response = client.put('/api/settings/access',
                             data=json.dumps({'charts_public': True}),
                             content_type='application/json')
        assert response.status_code == 401

    def test_save_access_validates_input(self, feature_client):
        """PUT /api/settings/access rejects unknown keys and non-boolean values."""
        client, _ = feature_client
        self._login(client)

        # Unknown key
        response = client.put('/api/settings/access',
                             data=json.dumps({'unknown_key': True}),
                             content_type='application/json')
        assert response.status_code == 400
        assert 'Unknown key' in response.get_json()['error']

        # Non-boolean value
        response = client.put('/api/settings/access',
                             data=json.dumps({'charts_public': 'yes'}),
                             content_type='application/json')
        assert response.status_code == 400
        assert 'must be a boolean' in response.get_json()['error']

    def test_save_access_merge_semantics(self, feature_client):
        """PUT /api/settings/access uses merge semantics - partial updates preserve other flags."""
        client, settings_file = feature_client
        self._login(client)

        # Set charts_public
        response = client.put('/api/settings/access',
                             data=json.dumps({'charts_public': True}),
                             content_type='application/json')
        assert response.status_code == 200
        assert response.get_json()['access']['charts_public'] is True

        # Set table_public - charts_public should still be True
        response = client.put('/api/settings/access',
                             data=json.dumps({'table_public': True}),
                             content_type='application/json')
        assert response.status_code == 200
        access = response.get_json()['access']
        assert access['charts_public'] is True
        assert access['table_public'] is True
        assert access['live_feed_public'] is False

    def test_recorder_status_requires_auth(self, feature_client):
        """GET /api/recorder/status returns 401 when not authenticated."""
        client, _ = feature_client
        response = client.get('/api/recorder/status')
        assert response.status_code == 401

    def test_recorder_status_accessible_when_authenticated(self, feature_client):
        """GET /api/recorder/status returns 200 when authenticated."""
        client, _ = feature_client
        self._login(client)
        response = client.get('/api/recorder/status')
        assert response.status_code == 200

    def test_recorder_status_returns_empty_when_no_status(self, feature_client):
        """GET /api/recorder/status returns empty dict when no status has been reported."""
        client, _ = feature_client
        self._login(client)
        response = client.get('/api/recorder/status')
        assert response.status_code == 200
        assert response.get_json() == {}

    @pytest.fixture
    def _with_recorder_status(self):
        """Set recorder status for test and clean up afterwards."""
        import core.api
        core.api._recorder_status = {'state': 'degraded', 'message': 'Source failed'}
        yield core.api._recorder_status
        core.api._recorder_status = {}

    def test_recorder_status_returns_data_after_broadcast(self, feature_client, _with_recorder_status):
        """GET /api/recorder/status returns status after it's been broadcast."""
        client, _ = feature_client
        self._login(client)

        response = client.get('/api/recorder/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['state'] == 'degraded'
        assert data['message'] == 'Source failed'

    def test_recorder_status_not_gated_by_live_feed(self, feature_client):
        """GET /api/recorder/status works when authenticated even with live_feed_public=false."""
        client, settings_file = feature_client
        self._set_access(settings_file, live_feed_public=False)
        self._login(client)
        response = client.get('/api/recorder/status')
        assert response.status_code == 200

    def test_stream_config_no_longer_includes_recorder_status(self, feature_client, _with_recorder_status):
        """GET /api/stream/config should not include recorder_status field."""
        client, settings_file = feature_client
        self._set_access(settings_file, live_feed_public=True)

        response = client.get('/api/stream/config')
        assert response.status_code == 200
        data = response.get_json()
        assert 'recorder_status' not in data


class TestGetClientIp:
    """_get_client_ip must key on proxy-set headers, not client-supplied ones.

    nginx sets X-Real-IP to the real peer (overwriting any client value) and
    appends the peer to X-Forwarded-For. Keying rate limiting on the LEFTMOST
    X-Forwarded-For entry let an attacker rotate it to evade the login lockout.
    """

    def _client_ip(self, headers=None, remote_addr='172.18.0.5'):
        from flask import Flask

        from core.auth import _get_client_ip
        app = Flask(__name__)
        with app.test_request_context(headers=headers or {},
                                      environ_base={'REMOTE_ADDR': remote_addr}):
            return _get_client_ip()

    def test_prefers_x_real_ip_over_forwarded_for(self):
        # X-Real-IP wins even when a (spoofable) X-Forwarded-For is present.
        assert self._client_ip(headers={
            'X-Real-IP': '203.0.113.7',
            'X-Forwarded-For': '6.6.6.6',
        }) == '203.0.113.7'

    def test_uses_rightmost_forwarded_for_hop(self):
        # Client prepends a fake IP; nginx appends the real peer on the right.
        # We must take the rightmost (proxy-added) hop, not the spoofed leftmost.
        assert self._client_ip(headers={
            'X-Forwarded-For': '6.6.6.6, 203.0.113.7',
        }) == '203.0.113.7'

    def test_falls_back_to_remote_addr(self):
        assert self._client_ip(headers={}, remote_addr='172.18.0.9') == '172.18.0.9'
