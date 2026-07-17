"""Authentication endpoints: status, login/logout, setup, toggle, access flags.

Thin HTTP shims over core.auth (session + password handling) plus the
access-settings writer (which public features anonymous callers may see).
Registered on the shared ``api`` blueprint at import time.
"""
from flask import jsonify, request

from config.settings import get_default_settings
from core.api_infra import api
from core.api_utils import handle_api_errors
from core.auth import (
    authenticate,
    change_password,
    get_public_features,
    is_auth_enabled,
    is_authenticated,
    is_feature_public,
    is_public_access_enabled,
    is_setup_complete,
    logout,
    require_auth,
    set_auth_enabled,
    setup_password,
)
from core.logging_config import get_logger, log_api_request
from core.runtime_config import get_runtime_settings, invalidate_runtime_settings_cache
from core.settings_store import load_user_settings, save_user_settings

logger = get_logger(__name__)

# =============================================================================
# Authentication Endpoints
# =============================================================================

@api.route('/api/auth/status', methods=['GET'])
def get_auth_status():
    """Get authentication status for frontend."""
    auth_enabled = is_auth_enabled()
    public_access = (not auth_enabled) or is_public_access_enabled()
    # When the master public-access switch is off, no feature is effectively
    # public even if its per-feature flag is set.
    public_features = sorted(get_public_features()) if (auth_enabled and public_access) else []
    settings = get_runtime_settings()
    # Don't leak the station name to an anonymous visitor behind a full login
    # wall (auth on, public access off, not signed in). When public access is on
    # the name is part of the public view anyway, and the login screen shows it.
    show_station = public_access or is_authenticated()
    station_name = settings.get('display', {}).get('station_name', '') if show_station else ''
    return jsonify({
        'auth_enabled': auth_enabled,
        'setup_complete': is_setup_complete(),
        'authenticated': is_authenticated(),
        'public_access': public_access,
        'public_features': public_features,
        'station_name': station_name
    }), 200


@api.route('/api/auth/login', methods=['POST'])
@log_api_request
def auth_login():
    """Authenticate with password."""
    try:
        data = request.json
        if not data or 'password' not in data:
            return jsonify({'error': 'Password required'}), 400

        if not is_setup_complete():
            return jsonify({'error': 'Password not configured. Create a RESET_PASSWORD file in data/config/ to reset authentication.'}), 400

        if authenticate(data['password']):
            return jsonify({'success': True, 'message': 'Login successful'}), 200
        else:
            return jsonify({'error': 'Invalid password'}), 401

    except ValueError as e:
        # Rate limiting or other validation errors
        return jsonify({'error': str(e)}), 429 if 'Too many' in str(e) else 400
    except Exception as e:
        logger.error("Login error", extra={'error': str(e)})
        return jsonify({'error': 'Login failed'}), 500


@api.route('/api/auth/logout', methods=['POST'])
@log_api_request
def auth_logout():
    """Clear authentication session."""
    logout()
    return jsonify({'success': True, 'message': 'Logged out'}), 200


@api.route('/api/auth/setup', methods=['POST'])
@log_api_request
def auth_setup():
    """Set up initial password (first-time only)."""
    try:
        if is_setup_complete():
            return jsonify({'error': 'Password already set up'}), 400

        data = request.json
        if not data or 'password' not in data:
            return jsonify({'error': 'Password required'}), 400

        password = data['password']
        # Validation is handled by setup_password() - no duplicate check needed

        setup_password(password)

        # Auto-login after setup
        authenticate(password)

        return jsonify({'success': True, 'message': 'Password set successfully'}), 200

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error("Setup error", extra={'error': str(e)})
        return jsonify({'error': 'Setup failed'}), 500


@api.route('/api/auth/verify', methods=['GET'])
def auth_verify():
    """Internal endpoint for nginx auth_request. Returns 200 or 401."""
    if is_authenticated():
        return '', 200
    original_uri = request.headers.get('X-Original-URI', '')
    if original_uri.startswith('/stream/') and is_feature_public('live_feed'):
        return '', 200
    return '', 401


@api.route('/api/auth/toggle', methods=['POST'])
@log_api_request
@require_auth
def auth_toggle():
    """Enable or disable authentication."""
    try:
        data = request.json
        if data is None or 'enabled' not in data:
            return jsonify({'error': 'enabled field required'}), 400

        enabled = data['enabled']

        # Prevent enabling auth without a password set
        if enabled and not is_setup_complete():
            return jsonify({'error': 'Cannot enable authentication without setting a password first'}), 400

        set_auth_enabled(enabled)

        return jsonify({
            'success': True,
            'auth_enabled': enabled,
            'message': 'Authentication enabled' if enabled else 'Authentication disabled'
        }), 200

    except Exception as e:
        logger.error("Toggle auth error", extra={'error': str(e)})
        return jsonify({'error': 'Failed to toggle authentication'}), 500


@api.route('/api/settings/access', methods=['PUT'])
@log_api_request
@require_auth
@handle_api_errors
def save_access_settings():
    """Save per-feature access settings with merge semantics.

    Accepts partial payloads — only provided keys are updated.
    Valid keys: public_access, charts_public, table_public, live_feed_public
    (all booleans). public_access is the master switch for the anonymous limited
    view; the *_public keys broaden that view to specific feature areas.
    """
    data = request.json
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    valid_keys = {'public_access', 'charts_public', 'table_public', 'live_feed_public'}
    for key, value in data.items():
        if key not in valid_keys:
            return jsonify({'error': f'Unknown key: {key}'}), 400
        if not isinstance(value, bool):
            return jsonify({'error': f'{key} must be a boolean'}), 400

    current_settings = load_user_settings()
    if 'access' not in current_settings:
        current_settings['access'] = get_default_settings()['access']
    current_settings['access'].update(data)
    save_user_settings(current_settings)
    invalidate_runtime_settings_cache()

    return jsonify({
        'success': True,
        'access': current_settings['access']
    }), 200


@api.route('/api/auth/change-password', methods=['POST'])
@log_api_request
@require_auth
def auth_change_password():
    """Change the password (requires current password)."""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'Request body required'}), 400

        current = data.get('current_password')
        new = data.get('new_password')

        if not current or not new:
            return jsonify({'error': 'Both current_password and new_password required'}), 400

        # Validation is handled by change_password() - no duplicate check needed

        change_password(current, new)
        return jsonify({'success': True, 'message': 'Password changed successfully'}), 200

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error("Change password error", extra={'error': str(e)})
        return jsonify({'error': 'Failed to change password'}), 500
