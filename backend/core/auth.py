"""
Authentication module for BirdNET-PiPy.

Provides password-based authentication for protecting settings and audio stream.
Uses bcrypt for password hashing and Flask sessions for session management.
"""

import os
import json
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict
from threading import Lock

import bcrypt
from flask import session, jsonify, request

from core.logging_config import get_logger

logger = get_logger(__name__)

# Base directory for config files
BASE_DIR = '/app'
AUTH_CONFIG_DIR = os.path.join(BASE_DIR, 'data', 'config')
AUTH_CONFIG_FILE = os.path.join(AUTH_CONFIG_DIR, 'auth.json')
RESET_PASSWORD_FILE = os.path.join(AUTH_CONFIG_DIR, 'RESET_PASSWORD')

# Session configuration
SESSION_LIFETIME_DAYS = 7

# Password requirements
MIN_PASSWORD_LENGTH = 8

# Rate limiting configuration
MAX_LOGIN_ATTEMPTS = 5  # Max attempts before lockout
LOCKOUT_DURATION_SECONDS = 300  # 5 minutes lockout
ATTEMPT_WINDOW_SECONDS = 300  # Window for counting attempts

# Rate limiting state (in-memory, resets on restart)
_login_attempts = defaultdict(list)  # IP -> list of timestamps
_login_attempts_lock = Lock()


def load_auth_config(check_reset=True):
    """Load authentication configuration from JSON file.

    Args:
        check_reset: If True, check for password reset file first.
                    Set to False to avoid redundant checks.
    """
    # Check for password reset file first (only when requested)
    if check_reset:
        check_password_reset()

    if os.path.exists(AUTH_CONFIG_FILE):
        try:
            with open(AUTH_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load auth config", extra={'error': str(e)})

    # Return default config (auth disabled, no password set)
    return {
        'password_hash': None,
        'auth_enabled': False,
        'session_secret': None,
        'created_at': None,
        'last_modified': None
    }


def save_auth_config(config):
    """Atomically save authentication configuration to JSON file."""
    # Ensure directory exists
    os.makedirs(AUTH_CONFIG_DIR, exist_ok=True)

    # Update timestamp
    config['last_modified'] = datetime.utcnow().isoformat() + 'Z'

    # Atomic write using temp file
    temp_file = AUTH_CONFIG_FILE + '.tmp'
    with open(temp_file, 'w') as f:
        json.dump(config, f, indent=2)

    os.replace(temp_file, AUTH_CONFIG_FILE)

    # Set restrictive permissions (owner read/write only)
    try:
        os.chmod(AUTH_CONFIG_FILE, 0o600)
    except Exception as e:
        logger.warning("Could not set file permissions", extra={'error': str(e)})

    logger.info("Auth config saved")


def check_password_reset():
    """Check for password reset file and handle reset if present."""
    if os.path.exists(RESET_PASSWORD_FILE):
        logger.warning("Password reset file detected, resetting authentication")

        # Delete auth config
        if os.path.exists(AUTH_CONFIG_FILE):
            os.remove(AUTH_CONFIG_FILE)
            logger.info("Auth config deleted")

        # Delete reset file
        os.remove(RESET_PASSWORD_FILE)
        logger.info("Reset file deleted")

        return True
    return False


def _get_client_ip():
    """Get client IP address from request, handling proxies."""
    # Check X-Forwarded-For header (set by nginx reverse proxy)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(',')[0].strip()
    # Check X-Real-IP header (alternative proxy header)
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip.strip()
    # Fall back to remote_addr
    return request.remote_addr or 'unknown'


def _clean_old_attempts(ip):
    """Remove expired login attempts for an IP."""
    current_time = time.time()
    cutoff = current_time - ATTEMPT_WINDOW_SECONDS
    _login_attempts[ip] = [t for t in _login_attempts[ip] if t > cutoff]


def check_rate_limit(ip=None):
    """Check if an IP is rate limited.

    Args:
        ip: Client IP address. If None, gets from current request.

    Returns:
        tuple: (is_allowed, seconds_until_unlock)
               is_allowed is True if login attempt is allowed
               seconds_until_unlock is 0 if allowed, else seconds to wait
    """
    if ip is None:
        ip = _get_client_ip()

    with _login_attempts_lock:
        _clean_old_attempts(ip)
        attempts = _login_attempts[ip]

        if len(attempts) >= MAX_LOGIN_ATTEMPTS:
            # Check if lockout period has passed since last attempt
            oldest_in_window = min(attempts) if attempts else 0
            time_since_oldest = time.time() - oldest_in_window
            if time_since_oldest < LOCKOUT_DURATION_SECONDS:
                seconds_left = int(LOCKOUT_DURATION_SECONDS - time_since_oldest)
                return False, seconds_left

        return True, 0


def record_failed_attempt(ip=None):
    """Record a failed login attempt for rate limiting.

    Args:
        ip: Client IP address. If None, gets from current request.
    """
    if ip is None:
        ip = _get_client_ip()

    with _login_attempts_lock:
        _clean_old_attempts(ip)
        _login_attempts[ip].append(time.time())
        logger.warning("Failed login attempt recorded",
                       extra={'ip': ip, 'attempts': len(_login_attempts[ip])})


def clear_failed_attempts(ip=None):
    """Clear failed login attempts after successful login.

    Args:
        ip: Client IP address. If None, gets from current request.
    """
    if ip is None:
        ip = _get_client_ip()

    with _login_attempts_lock:
        if ip in _login_attempts:
            del _login_attempts[ip]
            logger.debug("Cleared failed attempts", extra={'ip': ip})


def get_or_create_session_secret():
    """Get existing session secret or create a new one."""
    config = load_auth_config()

    if config.get('session_secret'):
        return config['session_secret']

    # Generate new secret
    secret = secrets.token_hex(32)
    config['session_secret'] = secret

    if not config.get('created_at'):
        config['created_at'] = datetime.utcnow().isoformat() + 'Z'

    save_auth_config(config)
    logger.info("Generated new session secret")

    return secret


def hash_password(password):
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def verify_password(password, password_hash):
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception as e:
        logger.error("Password verification failed", extra={'error': str(e)})
        return False


def is_auth_enabled():
    """Check if authentication is enabled."""
    config = load_auth_config()
    return config.get('auth_enabled', False)


def is_setup_complete():
    """Check if password has been set up."""
    config = load_auth_config()
    return config.get('password_hash') is not None


def is_authenticated():
    """Check if the current session is authenticated."""
    if not is_auth_enabled():
        return True  # Auth disabled = always authenticated

    return session.get('authenticated', False)


def set_auth_enabled(enabled):
    """Enable or disable authentication."""
    config = load_auth_config()
    config['auth_enabled'] = enabled
    save_auth_config(config)
    logger.info("Authentication enabled" if enabled else "Authentication disabled")


def setup_password(password):
    """Set up the initial password (first-time setup)."""
    if is_setup_complete():
        raise ValueError("Password already set up")

    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    config = load_auth_config()
    config['password_hash'] = hash_password(password)
    config['auth_enabled'] = True

    if not config.get('session_secret'):
        config['session_secret'] = secrets.token_hex(32)

    if not config.get('created_at'):
        config['created_at'] = datetime.utcnow().isoformat() + 'Z'

    save_auth_config(config)
    logger.info("Password set up successfully")


def change_password(current_password, new_password):
    """Change the password (requires current password verification)."""
    config = load_auth_config()

    if not config.get('password_hash'):
        raise ValueError("No password set up")

    if not verify_password(current_password, config['password_hash']):
        raise ValueError("Current password is incorrect")

    if not new_password or len(new_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"New password must be at least {MIN_PASSWORD_LENGTH} characters")

    config['password_hash'] = hash_password(new_password)
    save_auth_config(config)
    logger.info("Password changed successfully")


def authenticate(password):
    """Authenticate with password and create session.

    Returns:
        True if authentication successful, False if password incorrect.

    Raises:
        ValueError: If no password set up or rate limited.
    """
    # Check rate limit first
    is_allowed, seconds_left = check_rate_limit()
    if not is_allowed:
        raise ValueError(f"Too many failed attempts. Try again in {seconds_left} seconds.")

    config = load_auth_config()

    if not config.get('password_hash'):
        raise ValueError("No password set up")

    if not verify_password(password, config['password_hash']):
        record_failed_attempt()
        return False

    # Successful login - clear failed attempts
    clear_failed_attempts()

    # Set session
    session['authenticated'] = True
    session['authenticated_at'] = datetime.utcnow().isoformat()
    session.permanent = True  # Use permanent session (respects PERMANENT_SESSION_LIFETIME)

    logger.info("User authenticated successfully")
    return True


def logout():
    """Clear the authentication session."""
    session.pop('authenticated', None)
    session.pop('authenticated_at', None)
    logger.info("User logged out")


def require_auth(f):
    """Decorator to protect API routes requiring authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # is_auth_enabled() calls load_auth_config() which checks password reset
        # So we don't need a separate check_password_reset() call here
        if not is_auth_enabled():
            return f(*args, **kwargs)

        # Check session authentication
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

        return f(*args, **kwargs)
    return decorated_function


def configure_session(app):
    """Configure Flask session settings for the app.

    Session cookie settings are configured to work with nginx reverse proxy:
    - Secure flag is controlled by SESSION_COOKIE_SECURE env var (default: false)
    - Set SESSION_COOKIE_SECURE=true when deploying behind HTTPS
    - When behind nginx with SSL termination, nginx sets X-Forwarded-Proto
    """
    # Get or create session secret
    secret = get_or_create_session_secret()

    app.secret_key = secret
    app.config['SESSION_COOKIE_NAME'] = 'birdnet_session'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=SESSION_LIFETIME_DAYS)

    # Secure flag = False: cookies sent over both HTTP and HTTPS
    # This works for:
    # - Local HTTP access (http://pi) - the common case
    # - Behind HTTPS proxy (ngrok, Cloudflare, etc.) - browser sees HTTPS, sends cookie
    # Setting True would break local HTTP access with no real benefit for this app.
    app.config['SESSION_COOKIE_SECURE'] = False

    logger.info("Session configured", extra={'lifetime_days': SESSION_LIFETIME_DAYS})
