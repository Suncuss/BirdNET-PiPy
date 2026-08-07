"""
Authentication module for BirdNET-PiPy.

Provides password-based authentication for protecting settings and audio stream.
Uses bcrypt for password hashing and Flask sessions for session management.
"""

import json
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from threading import Lock

import bcrypt
from flask import jsonify, request, session
from flask.sessions import SecureCookieSessionInterface

from core.logging_config import get_logger
from core.native_lock import native_lock
from core.secure_file import atomic_write_private_json

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
_login_attempts_lock = Lock()  # hub-only: login routes run in request greenlets, never the DB lane


# Parsed auth.json, keyed by (path, mtime) so an external edit (or the test
# suite pointing AUTH_CONFIG_FILE elsewhere) invalidates naturally. Auth is
# consulted several times per request (default-deny gate, scope decorators,
# tier checks), so uncached disk reads would multiply per request.
_auth_config_cache = None  # (path, mtime, config)
# Native lock: read from request greenlets AND from the DB-lane worker
# (cache builders mint media signatures -> get_or_create_media_secret reads
# the config through this cache) — a patched lock loses wakeups across that
# boundary (see core/native_lock.py). Guards ONLY the cache tuple
# (compare/copy/assign); file I/O and logging stay outside it. First-mint
# and mutation serialization is _auth_config_write_lock's job (below).
_auth_config_lock = native_lock()

# Every auth.json writer replaces the complete object, so the entire
# read-modify-write transaction must be serialized. This covers first secret
# mints from the DB-lane worker as well as password/setup/toggle requests; a
# save-only lock would still let a stale reader overwrite a newer password,
# epoch, or rotated capability secret. The lock is native because both OS
# threads and request greenlets take it (see core/native_lock.py).
_auth_config_write_lock = native_lock()


def _default_auth_config():
    """The auth-disabled config substituted when no usable file is present."""
    return {
        'password_hash': None,
        'auth_enabled': False,
        'session_secret': None,
        'created_at': None,
        'last_modified': None
    }


def _load_auth_config(check_reset=True):
    """Load the auth config, reporting whether an existing file was unreadable.

    Args:
        check_reset: If True, check for password reset file first.
                    Set to False to avoid redundant checks.

    Returns:
        ``(config, unreadable)``. ``unreadable`` is True only when a config file
        is present but could not be read or parsed — a missing file (first run)
        reports False, because there the substituted defaults are the right
        answer. Every caller that writes the config back MUST check it:
        persisting substituted defaults over a real-but-unreadable file replaces
        the password hash and all three secrets with nulls.
    """
    global _auth_config_cache

    # Check for password reset file first (only when requested)
    if check_reset:
        check_password_reset()

    try:
        mtime = os.path.getmtime(AUTH_CONFIG_FILE)
    except FileNotFoundError:
        return _default_auth_config(), False
    except OSError as e:
        # Present but un-stattable (EACCES, EIO): unreadable, NOT a first run.
        logger.error("Failed to stat auth config", extra={'error': str(e)})
        return _default_auth_config(), True

    with _auth_config_lock:
        if _auth_config_cache and _auth_config_cache[:2] == (AUTH_CONFIG_FILE, mtime):
            # Copy so callers' mutate-then-save flows can't corrupt the cache.
            return dict(_auth_config_cache[2]), False
    try:
        with open(AUTH_CONFIG_FILE) as f:
            config = json.load(f)
    except Exception as e:
        logger.error("Failed to load auth config", extra={'error': str(e)})
        return _default_auth_config(), True

    if not isinstance(config, dict):
        # Parses as JSON but is the wrong shape — `null`, a bare scalar, or a
        # list. Both halves matter: dict(None) would raise out of every auth
        # check (500 on every request, and the cache would replay it), while
        # dict([]) would quietly yield an empty config that reads as legitimate
        # and gets written back over the real one. Unreadable covers both.
        logger.error("Auth config is not a JSON object",
                     extra={'type': type(config).__name__})
        return _default_auth_config(), True

    with _auth_config_lock:
        _auth_config_cache = (AUTH_CONFIG_FILE, mtime, config)
    return dict(config), False


def _next_session_epoch(config):
    """The next value for the session epoch: wall-clock, but strictly increasing.

    Wall-clock rather than a counter so the epoch cannot be *rewound*. The
    RESET_PASSWORD recovery deletes auth.json, and a counter would restart at 0
    — revalidating every cookie a previous password change had evicted. A
    timestamp never collides with those, and max(..., prev + 1) keeps it
    monotonic across two changes inside the same second.
    """
    return max(int(time.time()), config.get('session_epoch', 0) + 1)


def _refuse_write_on_unreadable(unreadable, action):
    """Whether a config write must be skipped, logging why.

    Guards every writer of auth.json: when the on-disk file is present but
    unreadable the in-hand config is the auth-disabled default, so writing it
    would turn a transient read failure into a permanent auth wipe — and, via
    the anonymous /api/auth/setup route, into a station takeover.
    """
    if not unreadable:
        return False
    logger.critical(
        "Auth config unreadable — refusing to %s. Restore or remove %s to recover.",
        action, AUTH_CONFIG_FILE
    )
    return True


def load_auth_config(check_reset=True):
    """Load authentication configuration from JSON file (mtime-cached).

    Args:
        check_reset: If True, check for password reset file first.
                    Set to False to avoid redundant checks.
    """
    return _load_auth_config(check_reset)[0]


def _save_auth_config(config):
    """Save auth configuration while ``_auth_config_write_lock`` is held."""
    global _auth_config_cache

    # Update timestamp
    config['last_modified'] = datetime.utcnow().isoformat() + 'Z'

    # fsync before the rename: without it a power cut can publish an empty or
    # partial auth.json, which reads as "auth disabled" downstream. The helper
    # also creates the temp file as 0600 before writing any secrets into it.
    atomic_write_private_json(AUTH_CONFIG_FILE, config, fsync=True)

    # Drop the read cache explicitly — mtime alone can miss a same-instant
    # rewrite on filesystems with coarse timestamp resolution.
    with _auth_config_lock:
        _auth_config_cache = None

    logger.info("Auth config saved")


def save_auth_config(config):
    """Atomically save authentication configuration."""
    with _auth_config_write_lock:
        _save_auth_config(config)


def _check_password_reset_unlocked():
    """Handle a reset marker while ``_auth_config_write_lock`` is held."""
    global _auth_config_cache
    if os.path.exists(RESET_PASSWORD_FILE):
        logger.warning("Password reset file detected, resetting authentication")

        # Delete auth config
        if os.path.exists(AUTH_CONFIG_FILE):
            os.remove(AUTH_CONFIG_FILE)
            with _auth_config_lock:
                _auth_config_cache = None
            logger.info("Auth config deleted")

        # Delete reset file
        os.remove(RESET_PASSWORD_FILE)
        logger.info("Reset file deleted")

        return True
    return False


def check_password_reset():
    """Check for password reset file and handle reset if present."""
    with _auth_config_write_lock:
        return _check_password_reset_unlocked()


def _load_auth_config_for_update():
    """Load the latest config inside an auth.json mutation transaction."""
    _check_password_reset_unlocked()
    return _load_auth_config(check_reset=False)


def _get_client_ip():
    """Get the client IP as seen by our trusted nginx proxy.

    Only headers our own nginx sets are trustworthy. nginx sets
    ``X-Real-IP $remote_addr`` (overwriting any client-supplied value) and
    appends the real peer to ``X-Forwarded-For`` (so the RIGHTMOST entry is the
    hop nginx added). The LEFTMOST X-Forwarded-For entries are fully
    client-controlled, so keying rate limiting on them let an attacker rotate
    the header to evade the login lockout. Prefer X-Real-IP, then the rightmost
    forwarded hop, then the direct peer.
    """
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip.strip()

    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        # Rightmost = appended by our nginx hop; left entries are spoofable.
        return forwarded_for.split(',')[-1].strip()

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


def _get_or_create_secret(key, label):
    """Get an existing secret from auth.json, or generate, persist and return one.

    Backs the session/media/share secret accessors — each is the same
    get-or-create-and-save logic over a different config key.
    """
    config, unreadable = _load_auth_config()

    if config.get(key):
        return config[key]

    with _auth_config_write_lock:
        # Re-read: another thread may have minted and saved while we waited.
        config, unreadable = _load_auth_config_for_update()
        if config.get(key):
            return config[key]

        secret = secrets.token_hex(32)

        if _refuse_write_on_unreadable(unreadable, f'persist a new {label} secret'):
            # Serve an ephemeral secret instead: it lasts this process only,
            # and the on-disk config stays recoverable.
            return secret

        config[key] = secret

        if not config.get('created_at'):
            config['created_at'] = datetime.utcnow().isoformat() + 'Z'

        _save_auth_config(config)
        logger.info("Generated new %s secret", label)

        return secret


def get_or_create_session_secret():
    """Get existing session secret or create a new one."""
    return _get_or_create_secret('session_secret', 'session')


def get_or_create_media_secret():
    """Get or create the secret used to sign media capability URLs.

    Separate from the session secret so it can be reasoned about (and rotated)
    independently. Persisted in auth.json so signed media URLs survive a
    restart within their TTL.
    """
    return _get_or_create_secret('media_secret', 'media')


def get_or_create_share_secret():
    """Get or create the secret used to sign detection share tokens.

    Dedicated (not the session/media secret) so share links can be reasoned
    about and mass-revoked independently — regenerating this secret invalidates
    every outstanding share link at once. Persisted in auth.json.
    """
    return _get_or_create_secret('share_secret', 'share')


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
    """Check if the current session is authenticated.

    Loads the config once and reads both the enabled flag and the session epoch
    off it — same cached-stat cost as checking the flag alone.
    """
    config = load_auth_config()

    if not config.get('auth_enabled', False):
        return True  # Auth disabled = always authenticated

    if not session.get('authenticated', False):
        return False

    # Sessions carry the epoch they were minted under. change_password() bumps
    # it, so a password change actually evicts every other signed-in device
    # instead of leaving stateless cookies valid forever. Sessions predating
    # the epoch (and configs predating it) both read as 0, so an upgrade does
    # not sign anyone out.
    return session.get('epoch', 0) == config.get('session_epoch', 0)


def set_auth_enabled(enabled):
    """Enable or disable authentication."""
    with _auth_config_write_lock:
        config, unreadable = _load_auth_config_for_update()
        if _refuse_write_on_unreadable(unreadable, 'toggle authentication'):
            raise RuntimeError(
                "Authentication config could not be read; refusing to overwrite it"
            )

        config['auth_enabled'] = enabled
        _save_auth_config(config)
    logger.info("Authentication enabled" if enabled else "Authentication disabled")


_FEATURE_KEY_MAP = {
    'charts_public': 'charts',
    'table_public': 'table',
    'live_feed_public': 'live_feed',
}


def get_public_features():
    """Get set of feature names configured as publicly accessible.

    Returns empty set if auth is disabled (everything is public anyway).
    """
    from core.runtime_config import get_runtime_setting
    access = get_runtime_setting('access', {})
    return {feature for key, feature in _FEATURE_KEY_MAP.items() if access.get(key)}


def is_feature_public(feature):
    """Check if a feature is publicly accessible.

    Returns True if auth is disabled (everything public). When auth is enabled,
    a feature is public only if the master public-access switch is on AND the
    feature is configured public — so turning public access off is a true
    kill-switch that overrides the per-feature flags.
    """
    if not is_auth_enabled():
        return True
    if not is_public_access_enabled():
        return False
    return feature in get_public_features()


def require_feature(feature_name):
    """Decorator to protect routes by feature-level access control.

    Allows access if:
    1. The feature is configured as public, OR
    2. The user is authenticated via session
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if is_feature_public(feature_name) or is_authenticated():
                return f(*args, **kwargs)
            return jsonify({'error': 'Authentication required'}), 401
        # Access-declaration marker for the boot-time route audit (see
        # api._assert_route_access_declared). @wraps on any outer decorator
        # copies it forward to the registered view function.
        decorated_function._access_gate = f'feature:{feature_name}'
        return decorated_function
    return decorator


def get_request_tier():
    """Classify the current request as 'owner' or 'public'.

    'owner' = auth disabled OR a valid authenticated session (full access).
    'public' = auth enabled and not signed in (the bounded anonymous view).
    Handlers use this to clamp what anonymous callers may read.
    """
    return 'owner' if is_authenticated() else 'public'


def is_public_access_enabled():
    """Whether anonymous visitors get the limited public view.

    Defaults to True so existing installs are unchanged. Only meaningful when
    auth is enabled (when auth is off everyone is already 'owner'). Setting it
    False turns the whole anonymous surface into a login wall. Read via the
    copy-free accessor — this runs on every anonymous request and media fetch.
    """
    from core.runtime_config import get_runtime_setting
    return get_runtime_setting('access.public_access', True)


def require_scope(scope):
    """Gate a route by access scope — the default-deny model.

    scope='owner'       -> requires auth disabled or an authenticated session.
    scope='public:read' -> allowed for owner, or for an anonymous visitor when
                           public access is enabled; otherwise 401 (login wall).

    Unlike the old "no decorator = public" behavior, an endpoint without a
    scope decorator is never reachable by an anonymous caller, so newly added
    routes are private by default.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if is_authenticated():
                return f(*args, **kwargs)
            if scope == 'public:read' and is_public_access_enabled():
                return f(*args, **kwargs)
            return jsonify({'error': 'Authentication required'}), 401
        decorated_function._access_gate = scope
        return decorated_function
    return decorator


def setup_password(password):
    """Set up the initial password (first-time setup)."""
    with _auth_config_write_lock:
        config, unreadable = _load_auth_config_for_update()
        if config.get('password_hash') is not None:
            raise ValueError("Password already set up")

        if not password or len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

        if _refuse_write_on_unreadable(unreadable, 'set up a password'):
            # /api/auth/setup is anonymously reachable and gated only by
            # is_setup_complete(), which reads None off the substituted defaults —
            # so without this an unreadable config lets any visitor claim the
            # station and destroy the owner's real credentials.
            raise ValueError(
                "Authentication config could not be read; refusing to overwrite it"
            )

        config['password_hash'] = hash_password(password)
        config['auth_enabled'] = True
        # Claiming the station evicts anything already holding a session — this is
        # also the path RESET_PASSWORD recovery lands on, where the old config (and
        # its epoch) is gone but old cookies may still be in circulation.
        config['session_epoch'] = _next_session_epoch(config)

        if not config.get('session_secret'):
            config['session_secret'] = secrets.token_hex(32)

        if not config.get('created_at'):
            config['created_at'] = datetime.utcnow().isoformat() + 'Z'

        _save_auth_config(config)
    logger.info("Password set up successfully")


def change_password(current_password, new_password):
    """Change the password (requires current password verification)."""
    with _auth_config_write_lock:
        config, unreadable = _load_auth_config_for_update()
        if _refuse_write_on_unreadable(unreadable, 'change the password'):
            raise ValueError(
                "Authentication config could not be read; refusing to overwrite it"
            )

        if not config.get('password_hash'):
            raise ValueError("No password set up")

        if not verify_password(current_password, config['password_hash']):
            raise ValueError("Current password is incorrect")

        if not new_password or len(new_password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"New password must be at least {MIN_PASSWORD_LENGTH} characters")

        config['password_hash'] = hash_password(new_password)
        # Evict every other signed-in device: sessions minted under an older epoch
        # stop validating in is_authenticated().
        config['session_epoch'] = _next_session_epoch(config)

        # The cookie is not the only thing a stolen session can leave behind: it
        # can mint signed media URLs (valid 24-48h) and share tokens (30 days),
        # neither of which carries the epoch. Rotating these two secrets is the
        # documented mass-revocation lever, so a password change revokes them too.
        # The owner's outstanding share links stop working — the intended trade for
        # an action whose whole purpose is to evict someone.
        config['media_secret'] = secrets.token_hex(32)
        config['share_secret'] = secrets.token_hex(32)

        _save_auth_config(config)
        new_epoch = config['session_epoch']

    # media_access caches the secret for the process lifetime; share_tokens
    # deliberately re-reads per call and needs no invalidation.
    from core.media_access import reset_secret_cache
    reset_secret_cache()

    # ...except this one. The caller just proved knowledge of the password, so
    # re-stamp their session rather than logging them out of the page they are
    # standing on. (Reads the raw flag, not is_authenticated(): the epoch it
    # would compare against was just bumped.)
    if session.get('authenticated'):
        session['epoch'] = new_epoch

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
    session['epoch'] = config.get('session_epoch', 0)
    session.permanent = True  # Use permanent session (respects PERMANENT_SESSION_LIFETIME)

    logger.info("User authenticated successfully")
    return True


def logout():
    """Clear the authentication session."""
    session.pop('authenticated', None)
    session.pop('authenticated_at', None)
    session.pop('epoch', None)
    logger.info("User logged out")


def require_auth(f):
    """Decorator to protect API routes requiring authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Single source of truth for "signed in": is_authenticated() also
        # returns True when auth is disabled, and checks the session epoch so
        # a password change evicts this session too. Reading
        # session['authenticated'] directly here would silently opt these
        # routes out of that.
        if is_authenticated():
            return f(*args, **kwargs)

        return jsonify({'error': 'Authentication required'}), 401
    decorated_function._access_gate = 'owner'
    return decorated_function


def forwarded_scheme():
    """The scheme the request externally arrived over: X-Forwarded-Proto's
    first (outermost) hop when a proxy reports one, else the connection's own
    scheme. The header is client-influencable on direct access, so anything but
    plain http/https degrades to the connection's scheme.

    Single owner of this parse — the session cookie's Secure flag and the
    absolute share/OG URLs both key off it and must agree on the answer.
    """
    proto = request.headers.get('X-Forwarded-Proto', '').split(',')[0].strip().lower()
    return proto if proto in ('http', 'https') else request.scheme


class _AutoSecureCookieSessionInterface(SecureCookieSessionInterface):
    """Set the session cookie's Secure flag per-request, from how the request
    actually arrived: HTTPS (directly, or via a TLS-terminating proxy that
    nginx reports through X-Forwarded-Proto) marks the cookie Secure; plain
    HTTP (the common http://pi LAN case) leaves it off, since Secure there
    would break login entirely. A static True/False can't serve both: the same
    station is often reached over LAN HTTP and an HTTPS tunnel, and a static
    False lets an HTTPS deployment's cookie be replayed over a downgraded
    plain-HTTP hop."""

    def get_cookie_secure(self, app):
        return forwarded_scheme() == 'https'


def configure_session(app):
    """Configure Flask session settings for the app.

    Session cookie settings are configured to work with nginx reverse proxy;
    the Secure flag is decided per-request from X-Forwarded-Proto (see
    _AutoSecureCookieSessionInterface).
    """
    # Get or create session secret
    secret = get_or_create_session_secret()

    app.secret_key = secret
    app.config['SESSION_COOKIE_NAME'] = 'birdnet_session'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=SESSION_LIFETIME_DAYS)
    app.session_interface = _AutoSecureCookieSessionInterface()

    logger.info("Session configured", extra={'lifetime_days': SESSION_LIFETIME_DAYS})
