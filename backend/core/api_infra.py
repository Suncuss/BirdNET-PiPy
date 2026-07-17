"""Shared API infrastructure: the blueprint, the DB lane, and the access gates.

This module sits below the route modules (core/routes/) so they can share the
single ``api`` blueprint and the DB executor without importing ``core.api``
(which imports them). Nothing here is route-specific.
"""
from functools import wraps

from flask import Blueprint, jsonify, request

from core.auth import is_authenticated
from core.db import DatabaseManager
from core.db_executor import create_db_executor
from core.internal_auth import INTERNAL_SECRET_HEADER, verify_internal_secret
from core.logging_config import get_logger, setup_logging

# Configure logging BEFORE constructing DatabaseManager below: its __init__
# runs schema init/migrations and logs diagnostics, which would otherwise hit
# an unconfigured root logger (INFO dropped, warnings unformatted on stderr).
# setup_logging is idempotent, so later callers are no-ops.
setup_logging('api')
logger = get_logger(__name__)

api = Blueprint('api', __name__)
db_manager = DatabaseManager()
db_executor = create_db_executor('threading')

# Timeout for a single DB job. Slightly below gunicorn's --timeout 120 so a
# wedged query fails the calling request cleanly rather than triggering a
# worker kill that drops every concurrent request with it. The job itself
# is not cancelled (sqlite3 is blocking C code) — busy_timeout=30s caps
# the worst case at the SQL level — but the caller stops waiting.
_DB_JOB_TIMEOUT_SECONDS = 90


def _run_db(func, *args, **kwargs):
    return db_executor.submit(func, *args, **kwargs).result(
        timeout=_DB_JOB_TIMEOUT_SECONDS,
    )


def _submit_db(func, *args, **kwargs):
    return db_executor.submit(func, *args, **kwargs)


def reset_db_executor(async_mode):
    """Replace the import-time executor with one matching the app's async mode."""
    global db_executor
    db_executor.shutdown(wait=False)
    db_executor = create_db_executor(async_mode)


def is_internal_request():
    """Check if request originates from internal sources (docker network or localhost).

    This is used to protect internal-only endpoints like /api/broadcast/detection.
    Does NOT trust X-Forwarded-For headers since those can be spoofed.
    """
    remote_addr = request.remote_addr or ''

    # Docker bridge networks use 172.x.x.x (typically 172.17-31.x.x)
    # Docker compose networks also use 172.x.x.x range
    if remote_addr.startswith('172.'):
        return True

    # Localhost (IPv4 and IPv6)
    if remote_addr in ('127.0.0.1', '::1') or remote_addr.startswith('127.'):
        return True

    # Docker host.docker.internal typically resolves to host gateway
    # which appears as 172.x.x.1 - already covered above

    return False


def require_internal(f):
    """Restrict an endpoint to internal callers.

    Requires BOTH an internal source address AND the shared internal secret.
    The IP check alone was insufficient: nginx proxies external requests from a
    172.x docker address, so every proxied request looked "internal" and an
    external client could POST to /api/broadcast/*. The shared secret (known
    only to the main/inference processes via the shared data volume) is the
    real gate; the IP check stays as a cheap secondary filter.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        provided = request.headers.get(INTERNAL_SECRET_HEADER)
        if not is_internal_request() or not verify_internal_secret(provided):
            logger.warning("Rejected request to internal endpoint", extra={
                'remote_addr': request.remote_addr,
                'endpoint': request.endpoint,
                'had_secret': bool(provided),
            })
            return jsonify({'error': 'Internal endpoint only'}), 403
        return f(*args, **kwargs)
    decorated_function._access_gate = 'internal'
    return decorated_function


# Structural default-deny backstop. Endpoints an anonymous (auth-on, no session)
# caller may even REACH are an explicit allowlist; everything else is denied here
# before the view runs. So a newly added route is private by default even if its
# gate decorator is forgotten — closing the original "no decorator means public"
# failure mode. The per-route decorators still apply the fine-grained rules
# (public_access window, feature flags, share tokens, the internal secret); this
# is only the coarse "is this endpoint anonymous-reachable at all" gate.
# Forgetting to allowlist a new public route fails safe (it's denied, surfacing
# in testing); tests guard against stale entries and against any sensitive
# endpoint being added here (see test_access_control.TestDefaultDenyBackstop).
_ANON_REACHABLE_ENDPOINTS = frozenset({
    # Bounded public reads (require_scope('public:read') decides on public_access)
    'get_wikimedia_image', 'get_wikimedia_image_candidates', 'get_wikimedia_choice',
    'get_latest_observation', 'get_recent_observations', 'get_observation_summary',
    'get_dashboard', 'get_dashboard_summary', 'get_unique_detections', 'get_sightings',
    'get_bird_details', 'serve_bird_image', 'get_bird_recordings',
    'get_detection_distribution', 'get_all_species', 'get_available_species',
    # Feature-gated (require_feature decides on the charts/table/live_feed flags)
    'get_hourly_activity', 'get_activity_overview', 'get_detection_trends',
    'get_detections', 'get_stream_config',
    # Token/window-gated media + permalink (the handlers do their own checks)
    'serve_audio', 'serve_spectrogram', 'get_bird_recording',
    # Link-unfurl crawlers are anonymous; the handler mirrors the by-id gate
    # and falls back to a generic branded card when not entitled
    'get_recording_og_card',
    # Always-public bootstrap / auth / non-detection info
    'get_auth_status', 'auth_login', 'auth_logout', 'auth_setup', 'auth_verify',
    'health_check', 'get_system_storage', 'get_system_version', 'check_for_updates',
    # Internal-only (require_internal validates the shared secret; the caller has
    # no session, so it must be allowed past this anonymous gate to be checked)
    'broadcast_detection_endpoint', 'broadcast_recorder_status_endpoint',
})


@api.before_request
def _default_deny_anonymous():
    """Deny anonymous callers any endpoint not on the explicit allowlist."""
    if request.method == 'OPTIONS':
        return None  # let CORS/preflight through
    endpoint = (request.endpoint or '').rsplit('.', 1)[-1]
    if endpoint in _ANON_REACHABLE_ENDPOINTS:
        # Cheap set check first: allowlisted routes proceed for everyone, so
        # the auth lookup is left to the route's own decorator/handler, which
        # makes the final call anyway.
        return None
    if is_authenticated():
        return None  # owner, or auth disabled (everyone is owner)
    return jsonify({'error': 'Authentication required'}), 401


def _assert_route_access_declared(app):
    """Boot-time audit: every api route must declare its access story.

    A route declares access by carrying a gate decorator (require_auth /
    require_scope / require_feature / require_internal — each marks its wrapper
    with ``_access_gate``, which @wraps propagates outward) and/or by an
    ``_ANON_REACHABLE_ENDPOINTS`` entry. The default-deny before_request
    already fails closed for anonymous callers, but an *undeclared* route is
    almost always an oversight — the OG-card route drifted in on another branch
    with neither a decorator nor an allowlist entry, silently 401ing every
    link-preview crawler post-merge. Failing at boot turns that class of drift
    into an immediate, named error.

    Cross-checks the two declarations for consistency, in both directions:
    an anonymous-reachable gate (public:read / feature:* / internal) off the
    allowlist is dead code (the before_request denies first), and an
    owner-gated route on the allowlist is a stale entry that would outlive the
    route's protection if the decorator were ever dropped.
    """
    problems = []
    for name, view in app.view_functions.items():
        if not name.startswith(f'{api.name}.'):
            continue
        endpoint = name.rsplit('.', 1)[-1]
        gate = getattr(view, '_access_gate', None)
        allowlisted = endpoint in _ANON_REACHABLE_ENDPOINTS
        if gate is None and not allowlisted:
            problems.append(
                f"{endpoint}: no access declaration — add require_auth/"
                "require_scope/require_feature/require_internal, or an "
                "_ANON_REACHABLE_ENDPOINTS entry if its handler self-gates")
        elif gate == 'owner' and allowlisted:
            problems.append(
                f"{endpoint}: owner-gated but on the anonymous allowlist — "
                "remove the stale allowlist entry")
        elif gate is not None and gate != 'owner' and not allowlisted:
            problems.append(
                f"{endpoint}: gated '{gate}' (anonymous-reachable) but missing "
                "from _ANON_REACHABLE_ENDPOINTS — the default-deny backstop "
                "will 401 anonymous callers before the gate runs")
    if problems:
        raise RuntimeError(
            'Route access audit failed:\n  ' + '\n  '.join(sorted(problems)))
