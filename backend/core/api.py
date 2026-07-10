import csv
import io
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse

import requests
from flask import (
    Blueprint,
    Flask,
    Response,
    jsonify,
    request,
    send_from_directory,
    session,
)
from flask_socketio import SocketIO, emit, join_room

from config.constants import (
    OVERLAP_OPTIONS,
    RECORDING_LENGTH_OPTIONS,
    UPDATE_CHANNELS,
    VALID_MODEL_TYPES,
)
from config.settings import (
    API_PORT,
    BASE_DIR,
    CUSTOM_BIRD_IMAGES_DIR,
    DEFAULT_AUDIO_PATH,
    DEFAULT_IMAGE_PATH,
    EXTRACTED_AUDIO_DIR,
    MODEL_TYPE,
    SPECTROGRAM_DIR,
    USER_SETTINGS_PATH,
    get_default_settings,
)
from core.api_utils import (
    handle_api_errors,
    log_data_metrics,
    recording_has_media,
    serve_file_with_fallback,
    validate_date_param,
    validate_limit_param,
)
from core.auth import (
    authenticate,
    change_password,
    configure_session,
    forwarded_scheme,
    get_public_features,
    get_request_tier,
    is_auth_enabled,
    is_authenticated,
    is_feature_public,
    is_public_access_enabled,
    is_setup_complete,
    logout,
    require_auth,
    require_feature,
    require_scope,
    set_auth_enabled,
    setup_password,
)
from core.bird_name_utils import (
    DEFAULT_BIRD_NAME_LANGUAGE,
    SUPPORTED_BIRD_NAME_LANGUAGES,
    add_display_common_name,
    add_display_species,
    clear_bird_name_caches,
    get_bird_name_language,
    get_localized_common_name,
)
from core.db import PRIVATE_DETECTION_FIELDS, DatabaseManager
from core.db_executor import create_db_executor
from core.ha_mode import get_runtime_mode, is_home_assistant_mode
from core.internal_auth import INTERNAL_SECRET_HEADER, verify_internal_secret
from core.logging_config import get_logger, log_api_request, setup_logging
from core.media_access import sign_media_query, verify_media_signature
from core.migration import (
    BirdNETPiMigrator,
    clear_migration_progress,
    get_migration_progress,
    set_migration_progress,
    start_migration_if_not_running,
)
from core.migration_audio import (
    check_disk_space,
    clear_audio_import_progress,
    clear_spectrogram_progress,
    generate_spectrograms_batch,
    get_audio_import_progress,
    get_spectrogram_progress,
    import_audio_files,
    list_available_folders,
    scan_audio_files,
    scan_files_needing_spectrograms,
    start_audio_import_if_not_running,
    start_spectrogram_generation_if_not_running,
)
from core.og_card import (
    OG_CARD_IMAGE_PATH,
    format_og_description,
    indefinite_article,
    render_og_card,
)
from core.runtime_config import (
    classify_setting_changes,
    deep_merge_settings,
    get_runtime_settings,
    get_setting_differences,
    invalidate_runtime_settings_cache,
)
from core.share_tokens import mint_share_token, share_token_subject, verify_share_token
from core.storage_manager import delete_detection_files
from core.timezone_service import get_timezone_str, local_now
from model_service.label_utils import get_species_list, resolve_to_scientific_name
from version import DISPLAY_NAME, __version__

# Setup logging
setup_logging('api')
logger = get_logger(__name__)

api = Blueprint('api', __name__)
db_manager = DatabaseManager()
db_executor = create_db_executor('threading')

# Singleton TimezoneFinder (loads ~40MB shape data on first use). The import
# itself is deferred into _get_timezone_finder(): it drags numpy/cffi/h3 into
# the worker, and the only caller is the settings handler resolving a newly
# saved location — a station that never edits its location never pays for it.
_timezone_finder = None
_tz_finder_lock = threading.Lock()


# Timeout for a single DB job. Slightly below gunicorn's --timeout 120 so a
# wedged query fails the calling request cleanly rather than triggering a
# worker kill that drops every concurrent request with it. The job itself
# is not cancelled (sqlite3 is blocking C code) — busy_timeout=30s caps
# the worst case at the SQL level — but the caller stops waiting.
_DB_JOB_TIMEOUT_SECONDS = 90

# Rows per DB batch for the streaming CSV export: small enough that a batch
# is a quick lane job holding ~1MB, large enough that a million-row export
# stays a few thousand round trips rather than a million.
_EXPORT_BATCH_ROWS = 1000


def _run_db(func, *args, **kwargs):
    return db_executor.submit(func, *args, **kwargs).result(
        timeout=_DB_JOB_TIMEOUT_SECONDS,
    )


def _submit_db(func, *args, **kwargs):
    return db_executor.submit(func, *args, **kwargs)


def load_user_settings():
    """Compatibility wrapper around runtime settings loader."""
    return get_runtime_settings(force_reload=True)


def _get_timezone_finder():
    """Lazy-import and lazy-load TimezoneFinder (loads ~40MB shape data)."""
    global _timezone_finder
    with _tz_finder_lock:
        if _timezone_finder is None:
            from timezonefinder import TimezoneFinder
            _timezone_finder = TimezoneFinder()
        return _timezone_finder


def get_timezone_for_location(lat: float, lon: float) -> str | None:
    """Offline timezone lookup. Returns IANA timezone or None on failure."""
    try:
        tf = _get_timezone_finder()
        timezone = tf.timezone_at(lat=lat, lng=lon)
        if timezone:
            logger.info(f"Resolved timezone: {timezone}")
            return timezone
        logger.warning(f"No timezone found for ({lat}, {lon})")
        return None
    except Exception as e:
        logger.error(f"Timezone lookup failed: {e}")
        return None


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
    from functools import wraps

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


# Simple in-memory cache
image_cache = {}
_image_cache_lock = threading.Lock()
CACHE_EXPIRATION = 172800  # Cache expiration time in seconds (48 hours)
MAX_CACHE_SIZE = 1000  # Maximum number of cached entries

# Single-flight coordination for Wikimedia lookups. These deliberately do NOT
# go through db_executor: that is a single SQLite lane, and a slow external
# HTTP call there would block unrelated database work. The HTTP runs inline in
# the request greenlet (under gevent, socket waits yield the event loop); this
# map only dedups concurrent cache-misses for the same (species, limit) so they
# share one upstream fetch instead of each hammering Wikimedia.
_wikimedia_inflight = {}
_wikimedia_inflight_lock = threading.Lock()
_WIKIMEDIA_FETCH_TIMEOUT = 30  # waiter cap; the leader does up to 10s+15s of HTTP

# Update check cache (only cache successful responses)
_update_check_cache = {
    'result': None,
    'timestamp': 0,
    'cache_key': None  # format: "channel:current_commit"
}
UPDATE_CHECK_CACHE_TTL = 3600  # 1 hour in seconds


_HA_CORE_API_BASE = "http://supervisor/core/api"


def _call_supervisor(method, path, timeout=10):
    """Call Home Assistant Supervisor API. Returns (data, error_message)."""
    token = os.environ.get('SUPERVISOR_TOKEN', '')
    try:
        resp = requests.request(
            method,
            f"http://supervisor{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json() if resp.content else {}
        return body.get('data', {}), None
    except requests.RequestException as e:
        return None, str(e)


def _find_addon_update_entity(addon_slug, token):
    """Find this addon's update.* entity_id via HA Core states.

    HA Core registers an UpdateEntity per addon with entity_picture set to
    /api/hassio/addons/<full_slug>/icon — a unique key per addon. Returns
    (entity_id, error_message).
    """
    try:
        resp = requests.get(
            f"{_HA_CORE_API_BASE}/states",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        resp.raise_for_status()
        states = resp.json()
    except requests.RequestException as e:
        return None, f'Failed to fetch HA Core states: {e}'
    except ValueError as e:
        return None, f'Invalid response from HA Core states: {e}'

    icon_url = f"/api/hassio/addons/{addon_slug}/icon"
    for state in states:
        entity_id = state.get('entity_id', '')
        if not entity_id.startswith('update.'):
            continue
        if state.get('attributes', {}).get('entity_picture') == icon_url:
            return entity_id, None

    return None, f'Could not find update entity for addon {addon_slug}'


def _build_update_check_result(update_available, current_commit, remote_commit,
                                commits_behind, current_branch, target_branch,
                                channel, preview_commits, fresh_sync, update_note):
    """Build the update check response dictionary."""
    return {
        'update_available': update_available,
        'current_commit': current_commit,
        'remote_commit': remote_commit,
        'commits_behind': commits_behind,
        'current_branch': current_branch,
        'target_branch': target_branch,
        'channel': channel,
        'preview_commits': preview_commits,
        'fresh_sync': fresh_sync,
        'update_note': update_note
    }


def _cache_and_return_update_result(result, cache_key, now):
    """Cache the result and return JSON response."""
    _update_check_cache['result'] = result
    _update_check_cache['timestamp'] = now
    _update_check_cache['cache_key'] = cache_key
    return jsonify(result), 200


def _cleanup_expired_cache():
    """Remove expired entries from image cache. Caller must hold _image_cache_lock."""
    current_time = time.time()
    expired_keys = [
        key for key, value in image_cache.items()
        if current_time - value['timestamp'] >= CACHE_EXPIRATION
    ]
    for key in expired_keys:
        del image_cache[key]
    if expired_keys:
        logger.debug("Cleaned up expired cache entries", extra={
            'removed_count': len(expired_keys)
        })


def get_cached_image(species_name, limit=1):
    cache_key = (species_name, limit)
    with _image_cache_lock:
        if cache_key in image_cache:
            cached_data = image_cache[cache_key]
            if time.time() - cached_data['timestamp'] < CACHE_EXPIRATION:
                logger.debug("Image cache hit", extra={
                    'species': species_name,
                    'limit': limit,
                    'age_seconds': int(time.time() - cached_data['timestamp'])
                })
                return cached_data['data']
    return None


def set_cached_image(species_name, data, limit=1):
    cache_key = (species_name, limit)
    with _image_cache_lock:
        # Periodically clean up expired entries when adding new ones
        if len(image_cache) >= MAX_CACHE_SIZE:
            _cleanup_expired_cache()
            # If still at max after cleanup, remove oldest entry
            if len(image_cache) >= MAX_CACHE_SIZE:
                oldest_key = min(image_cache, key=lambda k: image_cache[k]['timestamp'])
                del image_cache[oldest_key]

        image_cache[cache_key] = {
            'data': data,
            'timestamp': time.time()
        }

ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
IMAGE_MAGIC_PREFIXES = (b'\xff\xd8\xff', b'\x89PNG', b'RIFF', b'GIF8')


def _sanitize_species_filename(species_name):
    """Convert species name to a safe filename (spaces/special chars to underscores)."""
    sanitized = re.sub(r'[^\w\-]', '_', species_name)
    sanitized = re.sub(r'_+', '_', sanitized)
    return sanitized.strip('_')


def _get_custom_image_path(species_name):
    """Check if a custom image exists for the species. Returns (filepath, filename) or (None, None)."""
    sanitized = _sanitize_species_filename(species_name)
    for ext in ALLOWED_IMAGE_EXTENSIONS:
        filename = sanitized + ext
        filepath = os.path.join(CUSTOM_BIRD_IMAGES_DIR, filename)
        if os.path.exists(filepath):
            return filepath, filename
    return None, None


def _delete_custom_image(species_name):
    """Delete all custom images for species. Returns True if any were deleted."""
    sanitized = _sanitize_species_filename(species_name)
    deleted = False
    for ext in ALLOWED_IMAGE_EXTENSIONS:
        filepath = os.path.join(CUSTOM_BIRD_IMAGES_DIR, sanitized + ext)
        if os.path.exists(filepath):
            os.remove(filepath)
            deleted = True
    return deleted


CHOICE_SIDECAR_SUFFIX = '.choice.json'
SIDECAR_REQUIRED_KEYS = ('imageUrl', 'pageUrl', 'licenseType')
WIKIMEDIA_HOSTNAME_SUFFIX = '.wikimedia.org'


def _get_choice_sidecar_path(species_name):
    """Return the on-disk path for a species' Wikimedia-choice sidecar."""
    sanitized = _sanitize_species_filename(species_name)
    return os.path.join(CUSTOM_BIRD_IMAGES_DIR, sanitized + CHOICE_SIDECAR_SUFFIX)


def _load_choice_sidecar(species_name):
    """Load the Wikimedia-choice sidecar for a species. Returns dict or None on missing/corrupt."""
    path = _get_choice_sidecar_path(species_name)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Failed to load choice sidecar", extra={
            'species': species_name, 'error': str(e), 'path': path
        })
        return None

    if not isinstance(data, dict) or not all(k in data for k in SIDECAR_REQUIRED_KEYS):
        logger.warning("Choice sidecar missing required keys", extra={
            'species': species_name, 'path': path
        })
        return None
    return data


def _save_choice_sidecar(species_name, payload):
    """Atomically write a sidecar JSON for the species. Caller validates payload contents."""
    if not all(k in payload for k in SIDECAR_REQUIRED_KEYS):
        raise ValueError(f"Sidecar payload missing required keys: {SIDECAR_REQUIRED_KEYS}")
    os.makedirs(CUSTOM_BIRD_IMAGES_DIR, exist_ok=True)
    path = _get_choice_sidecar_path(species_name)
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    return path


def _delete_choice_sidecar(species_name):
    """Idempotently remove the sidecar. Returns True if a file was deleted."""
    path = _get_choice_sidecar_path(species_name)
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False


def _is_wikimedia_url(url):
    """Defense-in-depth check: only accept https URLs whose host is on wikimedia.org."""
    if not isinstance(url, str) or not url.startswith('https://'):
        return False
    try:
        host = (urlparse(url).hostname or '').lower()
    except ValueError:
        return False
    return host == 'wikimedia.org' or host.endswith(WIKIMEDIA_HOSTNAME_SUFFIX)


def _validate_image_magic_bytes(file_stream):
    """Validate that the file starts with known image magic bytes."""
    header = file_stream.read(4)
    file_stream.seek(0)
    return any(header[:len(m)] == m for m in IMAGE_MAGIC_PREFIXES)


WIKIMEDIA_TITLE_BLOCKLIST = re.compile(
    r'\b(eggs?|nests?|skeletons?|skulls?|bones?|feathers?|specimens?)\b',
    re.IGNORECASE,
)


WIKIMEDIA_THUMB_WIDTH = 400  # Wikimedia returns a CDN-cached thumbnail at this width.


def _parse_wikimedia_imageinfo(file_title, image_info):
    """Convert a wikimedia imageinfo entry to a candidate dict (URL + attribution + license).

    `thumbUrl` is populated when imageinfo is queried with iiurlwidth — clients should
    prefer it over `imageUrl` for grid tiles to avoid downloading full-res originals.
    """
    extmetadata = image_info.get('extmetadata', {})
    candidate = {
        'fileTitle': file_title,
        'imageUrl': image_info.get('url'),
        'thumbUrl': image_info.get('thumburl') or image_info.get('url'),
        'pageUrl': f"https://commons.wikimedia.org/wiki/{file_title.replace(' ', '_')}",
        'licenseType': extmetadata.get('LicenseShortName', {}).get('value', 'Unknown License'),
        'authorName': 'Unknown Author',
        'authorUrl': None,
    }
    author_html = extmetadata.get('Artist', {}).get('value', 'Unknown Author')
    author_match = re.search(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', author_html)
    if author_match:
        candidate['authorUrl'] = author_match.group(1)
        if candidate['authorUrl'].startswith('//'):
            candidate['authorUrl'] = 'https:' + candidate['authorUrl']
        candidate['authorName'] = author_match.group(2)
    else:
        candidate['authorName'] = re.sub('<[^<]+?>', '', author_html)
    return candidate


def _wikimedia_error(message, status, retry_after=None):
    """Structured failure for a Wikimedia lookup so callers can map it to an
    HTTP status (and surface Retry-After on 429) instead of guessing from a
    free-text string."""
    return {'message': message, 'status': status, 'retry_after': retry_after}


def _wikimedia_error_response(payload, error):
    """Build (response, status) for a Wikimedia failure, echoing the upstream
    Retry-After on a 429 so the client can back off instead of retrying blind."""
    resp = jsonify(payload)
    if error.get('status') == 429 and error.get('retry_after'):
        resp.headers['Retry-After'] = str(int(error['retry_after']))
    return resp, error.get('status', 502)


def _parse_retry_after(response):
    """Return Retry-After seconds as a float, or None if absent/unparseable."""
    raw = response.headers.get('Retry-After') if response is not None else None
    if raw and raw.strip().isdigit():
        return float(raw.strip())
    return None


def _do_fetch_wikimedia_candidates(species_name, limit):
    """Perform the actual two-step Wikimedia lookup (search + imageinfo).

    Returns (candidates_list, error_or_None) where error is a dict from
    _wikimedia_error(). Never raises — all failures become an error dict.
    """
    # Wikimedia requires a meaningful User-Agent with contact info (enforced
    # since 2024). The contact URL keeps us in the 200 req/min tier instead of
    # the 10 req/min "unidentified" tier.
    # Per Wikimedia policy: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
    headers = {
        'User-Agent': (
            f'{DISPLAY_NAME}/{__version__} '
            f'(+https://github.com/Suncuss/BirdNET-PiPy) '
            f'python-requests/{requests.__version__}'
        )
    }
    api_url = "https://commons.wikimedia.org/w/api.php"

    try:
        search_response = requests.get(
            api_url,
            params={
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": f"{species_name} filetype:bitmap -egg -skeleton",
                "srnamespace": "6",  # File namespace
                "srlimit": str(limit),
            },
            headers=headers,
            timeout=10,
        )
        search_response.raise_for_status()
        search_results = search_response.json().get('query', {}).get('search', [])

        if not search_results:
            return [], _wikimedia_error('No results found', 404)

        # Server-side `-egg -skeleton` is best-effort; filter titles too.
        ordered_titles = [
            hit['title'] for hit in search_results
            if not WIKIMEDIA_TITLE_BLOCKLIST.search(hit['title'])
        ]
        if not ordered_titles:
            return [], _wikimedia_error('No results found', 404)

        info_response = requests.get(
            api_url,
            params={
                "action": "query",
                "format": "json",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "iiurlwidth": str(WIKIMEDIA_THUMB_WIDTH),
                "titles": "|".join(ordered_titles),
            },
            headers=headers,
            timeout=15,
        )
        info_response.raise_for_status()
        pages = info_response.json().get('query', {}).get('pages', {})

        # Pages are keyed by page-id; index by title to preserve search order.
        title_to_info = {
            page['title']: page['imageinfo'][0]
            for page in pages.values()
            if 'imageinfo' in page and page['imageinfo']
        }

        candidates = []
        for title in ordered_titles:
            info = title_to_info.get(title)
            if info is None or not info.get('url'):
                continue
            candidates.append(_parse_wikimedia_imageinfo(title, info))

        if not candidates:
            return [], _wikimedia_error('No image info found', 502)

        return candidates, None

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 502
        if status == 429:
            return [], _wikimedia_error(
                'Rate limited by Wikimedia', 429, _parse_retry_after(e.response)
            )
        return [], _wikimedia_error(f'Wikimedia returned HTTP {status}', 502)
    except requests.RequestException as e:
        # Includes JSONDecodeError (subclass of RequestException) from the
        # empty-body responses Wikimedia serves during a rate-limit cooldown.
        return [], _wikimedia_error(f'Error fetching Wikimedia image: {e}', 502)


def fetch_wikimedia_candidates(species_name, limit=8):
    """Fetch up to `limit` Wikimedia image candidates for a species.

    Returns (candidates_list, error_or_None); error is a _wikimedia_error()
    dict. The candidates list preserves Wikimedia search order (top-of-search
    first) and is empty on any failure. Concurrent misses for the same
    (species, limit) share a single upstream fetch (see _wikimedia_inflight).
    """
    cached = get_cached_image(species_name, limit=limit)
    if cached is not None:
        return cached, None

    key = (species_name, limit)
    with _wikimedia_inflight_lock:
        # Re-check under the lock: a flight that finished between our miss and
        # acquiring the lock may have just populated the cache.
        cached = get_cached_image(species_name, limit=limit)
        if cached is not None:
            return cached, None
        entry = _wikimedia_inflight.get(key)
        is_leader = entry is None
        if is_leader:
            entry = {'event': threading.Event(), 'result': None}
            _wikimedia_inflight[key] = entry

    if not is_leader:
        # Follower: wait for the leader's result rather than firing our own hit.
        if not entry['event'].wait(timeout=_WIKIMEDIA_FETCH_TIMEOUT):
            return [], _wikimedia_error('Wikimedia lookup timed out', 504)
        return entry['result'] or ([], _wikimedia_error('Wikimedia lookup failed', 502))

    # Leader: do the fetch, cache on success, then wake followers — always, so a
    # crash can't strand them waiting until the timeout.
    try:
        result = _do_fetch_wikimedia_candidates(species_name, limit)
    except Exception as e:  # defensive: _do_fetch shouldn't raise, but never hang followers
        result = ([], _wikimedia_error(f'Wikimedia lookup failed: {e}', 502))
    candidates, _ = result
    if candidates:
        set_cached_image(species_name, candidates, limit=limit)
    with _wikimedia_inflight_lock:
        entry['result'] = result
        _wikimedia_inflight.pop(key, None)
    entry['event'].set()
    return result


def fetch_wikimedia_image(species_name):
    """Backward-compatible single-result wrapper. Returns (dict_or_None, error_or_None)."""
    candidates, error = fetch_wikimedia_candidates(species_name, limit=1)
    if candidates:
        return candidates[0], None
    return None, error

@api.route('/api/wikimedia_image', methods=['GET'])
@require_scope('public:read')
def get_wikimedia_image():
    species_name = request.args.get('species', '')
    if not species_name:
        return jsonify({'error': 'Species name is required'}), 400

    custom_path, _ = _get_custom_image_path(species_name)
    has_custom = custom_path is not None

    # Honor saved Wikimedia choice when sidecar is present (skip upstream fetch).
    sidecar = _load_choice_sidecar(species_name)
    if sidecar:
        return jsonify({
            'imageUrl': sidecar['imageUrl'],
            # Legacy sidecars (schemaVersion 1) have no thumbUrl — fall back to
            # the full imageUrl so the gallery still renders, just heavier. New
            # saves carry a thumbUrl; re-saving a legacy choice upgrades it.
            'thumbUrl': sidecar.get('thumbUrl') or sidecar['imageUrl'],
            'pageUrl': sidecar['pageUrl'],
            'authorName': sidecar.get('authorName', 'Unknown Author'),
            'authorUrl': sidecar.get('authorUrl'),
            'licenseType': sidecar.get('licenseType', 'Unknown License'),
            'fileTitle': sidecar.get('fileTitle'),
            'hasCustomImage': has_custom,
            'source': 'sidecar',
        })

    # The gallery passes for_display_only=1: it renders the local custom image
    # when one exists and ignores the Wikimedia metadata, so skip the upstream
    # lookup for custom-upload species (a sidecar would have returned above).
    # BirdDetails omits the flag because it still wants the revert-fallback data.
    display_only = request.args.get('for_display_only', '').lower() in ('1', 'true', 'yes')
    if display_only and has_custom:
        return jsonify({'hasCustomImage': True}), 200

    image_data, error = fetch_wikimedia_image(species_name)

    if error:
        if has_custom:
            return jsonify({'hasCustomImage': True}), 200
        return _wikimedia_error_response({'error': error['message']}, error)

    image_data['hasCustomImage'] = has_custom
    image_data['source'] = 'wikimedia-search'

    logger.debug("Wikimedia image fetched", extra={
        'species': species_name,
        'has_image': bool(image_data),
        'has_custom_image': has_custom
    })
    return jsonify(image_data)


@api.route('/api/wikimedia_image/candidates', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_wikimedia_image_candidates():
    """Return up to `limit` Wikimedia candidates plus the user's currently-saved choice."""
    species_name = request.args.get('species', '').strip()
    if not species_name:
        return jsonify({'error': 'Species name is required'}), 400

    try:
        limit = int(request.args.get('limit', 8))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 20))

    candidates, error = fetch_wikimedia_candidates(species_name, limit=limit)

    custom_path, _ = _get_custom_image_path(species_name)
    has_custom = custom_path is not None
    sidecar = _load_choice_sidecar(species_name)
    selected_file_title = sidecar.get('fileTitle') if sidecar else None

    payload = {
        'species': species_name,
        'candidates': candidates,
        'selectedFileTitle': selected_file_title,
        'hasCustomImage': has_custom,
    }
    if error and not candidates:
        payload['error'] = error['message']
        return _wikimedia_error_response(payload, error)
    return jsonify(payload)


@api.route('/api/bird/<species_name>/wikimedia_choice', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_wikimedia_choice(species_name):
    sidecar = _load_choice_sidecar(species_name)
    if sidecar is None:
        return jsonify({'error': 'No saved choice', 'hasChoice': False}), 404
    return jsonify(sidecar)


@api.route('/api/bird/<species_name>/wikimedia_choice', methods=['PUT'])
@log_api_request
@require_auth
@handle_api_errors
def put_wikimedia_choice(species_name):
    payload = request.get_json(silent=True) or {}
    required = ('fileTitle', 'imageUrl', 'pageUrl', 'authorName', 'licenseType')
    missing = [k for k in required if not payload.get(k)]
    if missing:
        return jsonify({'error': f'Missing keys: {", ".join(missing)}'}), 400

    if not _is_wikimedia_url(payload['imageUrl']) or not _is_wikimedia_url(payload['pageUrl']):
        return jsonify({'error': 'imageUrl and pageUrl must be wikimedia.org https URLs'}), 400

    author_url = payload.get('authorUrl')
    if author_url is not None and not isinstance(author_url, str):
        return jsonify({'error': 'authorUrl must be a string or null'}), 400

    # thumbUrl is optional (older clients omit it). Validate it when present;
    # otherwise store the full imageUrl so the sidecar always has a usable
    # thumbnail field for the gallery to display.
    thumb_url = payload.get('thumbUrl')
    if thumb_url is not None and (not isinstance(thumb_url, str) or not _is_wikimedia_url(thumb_url)):
        return jsonify({'error': 'thumbUrl must be a wikimedia.org https URL'}), 400

    sidecar = {
        'schemaVersion': 2,
        'source': 'wikimedia',
        'fileTitle': payload['fileTitle'],
        'imageUrl': payload['imageUrl'],
        'thumbUrl': thumb_url or payload['imageUrl'],
        'pageUrl': payload['pageUrl'],
        'authorName': payload['authorName'],
        'authorUrl': author_url,
        'licenseType': payload['licenseType'],
        'savedAt': local_now().isoformat(),
    }
    _save_choice_sidecar(species_name, sidecar)
    logger.info("Wikimedia choice saved", extra={
        'species': species_name, 'fileTitle': payload['fileTitle']
    })
    return jsonify(sidecar)


@api.route('/api/bird/<species_name>/wikimedia_choice', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def delete_wikimedia_choice(species_name):
    """Idempotently remove a saved Wikimedia choice."""
    _delete_choice_sidecar(species_name)
    logger.info("Wikimedia choice deleted", extra={'species': species_name})
    return jsonify({'hasChoice': False})

@api.route('/api/observations/latest', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_latest_observation():
    observation = _run_db(db_manager.get_latest_detections, 1)
    if observation:
        settings = load_user_settings()
        localized = _localize_detection(observation[0], settings=settings)
        log_data_metrics('get_latest_observation', localized, {
            'species': localized.get('common_name'),
            'timestamp': localized.get('timestamp')
        })
        return jsonify(localized)
    # Return 200 with null for empty database - frontend shows "No observations available yet."
    return jsonify(None)

@api.route('/api/observations/recent', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_recent_observations():
    unique = request.args.get('unique', 'false').lower() == 'true'
    settings = load_user_settings()
    observations = _localize_detection_list(
        _run_db(db_manager.get_latest_detections, 7, unique=unique),
        settings=settings,
    )
    log_data_metrics('get_recent_observations', observations)
    return jsonify(observations)

@api.route('/api/observations/summary', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_observation_summary():
    now = local_now()
    settings = load_user_settings()
    stats = _run_db(
        db_manager.get_summary_stats_all_periods,
        now.replace(hour=0, minute=0, second=0, microsecond=0),
        now - timedelta(weeks=1),
        now - timedelta(days=30),
    )
    summary = {
        period: _localize_summary(stats[period], settings=settings)
        for period in ('today', 'week', 'month', 'allTime')
    }
    log_data_metrics('get_observation_summary', summary, {
        'today_count': summary.get('today', {}).get('totalObservations', 0),
        'all_time_species': summary.get('allTime', {}).get('uniqueSpecies', 0)
    })
    return jsonify(summary)

@api.route('/api/activity/hourly', methods=['GET'])
@log_api_request
@require_feature('charts')
@validate_date_param()
@handle_api_errors
def get_hourly_activity():
    date = request.args.get('date', default=local_now().strftime('%Y-%m-%d'))
    activity = _run_db(db_manager.get_hourly_activity, date)
    log_data_metrics('get_hourly_activity', activity, {
        'date': date,
        'hours_with_activity': sum(1 for h in activity if h['count'] > 0)
    })
    return jsonify(activity)

@api.route('/api/activity/overview', methods=['GET'])
@log_api_request
@require_feature('charts')
@validate_date_param()
@handle_api_errors
def get_activity_overview():
    date = request.args.get('date', default=local_now().strftime('%Y-%m-%d'))
    order = request.args.get('order', default='most')
    if order not in ('most', 'least'):
        order = 'most'
    settings = load_user_settings()
    overview = _run_db(db_manager.get_activity_overview, date, order=order)
    overview = _localize_activity_items(overview, settings=settings)
    log_data_metrics('get_activity_overview', overview, {
        'date': date,
        'species_count': len(overview) if overview else 0
    })
    return jsonify(overview)

# Dashboard response cache. Dashboard only includes the initially visible
# summary period (today); hidden summary tabs lazy-load through
# /api/dashboard/summary. TTL slightly above the poll interval so consecutive
# polls hit the cache.
_DASHBOARD_CACHE_TTL_SECONDS = 10
_dashboard_cache_lock = threading.Lock()
_dashboard_cache: dict = {
    'payload': None,
    'expires_at': 0.0,
    'inflight': None,  # in-flight job, or None
    'dirty': False,    # soft-expired while a job was in flight; see _expire_cache_entry
}

# Per-period TTLs. 'today' is pinned to the dashboard TTL (the dashboard
# payload embeds the today summary, so the two must stay in lockstep);
# week/month/allTime are the most expensive queries the API runs (full-table
# scans on a Pi Zero) and stay warm for minutes/hours — see
# expire_dashboard_cache() for why detections don't touch them.
_SUMMARY_CACHE_TTL_SECONDS = {
    'today': _DASHBOARD_CACHE_TTL_SECONDS,
    'week': 300,
    'month': 3600,
    'allTime': 3600,
}
# The TTL table defines the period set: adding a period means giving it a TTL.
_SUMMARY_PERIODS = tuple(_SUMMARY_CACHE_TTL_SECONDS)
_summary_cache_lock = threading.Lock()
_summary_cache: dict = {
    period: {
        'payload': None,
        'expires_at': 0.0,
        'inflight': None,
        'dirty': False,
    }
    for period in _SUMMARY_PERIODS
}

# Bird Gallery response cache. The Most/Least Frequent and Species Catalog
# tabs run multi-second GROUP BY scans over the whole detections table. The
# gallery is opened on demand, not polled — so broadcast_detection() leaves it
# entirely alone (it doesn't even soft-expire it the way it does the dashboard
# entry): touching it per detection would keep it permanently cold. New
# detections age out via the TTL; bulk changes clear it explicitly (see
# invalidate_gallery_cache).
_GALLERY_SIGHTINGS_LIMIT = 12
_GALLERY_CACHE_TTL_SECONDS = 90
_GALLERY_KEY_FREQUENT = 'sightings:frequent'
_GALLERY_KEY_RARE = 'sightings:rare'
_GALLERY_KEY_SPECIES = 'species:all'
_gallery_cache_lock = threading.Lock()
_gallery_cache: dict = {
    key: {'payload': None, 'expires_at': 0.0, 'inflight': None, 'dirty': False}
    for key in (_GALLERY_KEY_FREQUENT, _GALLERY_KEY_RARE, _GALLERY_KEY_SPECIES)
}


def _summary_period_start(period, now):
    if period == 'today':
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'week':
        return now - timedelta(weeks=1)
    if period == 'month':
        return now - timedelta(days=30)
    if period == 'allTime':
        return datetime.min
    raise ValueError(f"invalid summary period: {period}")


def _reset_cache_entry(entry):
    """Clear a single-flight cache entry's payload, TTL, and in-flight job."""
    entry['payload'] = None
    entry['expires_at'] = 0.0
    entry['inflight'] = None
    entry['dirty'] = False


def _expire_cache_entry(entry):
    """Expire a single-flight cache entry without discarding anything.

    Zeroes 'expires_at' but keeps 'payload' and — crucially — 'inflight': a
    rebuild already in progress keeps its slot, so it still completes and is
    served to its waiting callers (contrast _reset_cache_entry, which revokes
    the in-flight job's write). 'dirty' records that the expiry may predate
    an in-flight job's DB snapshot: _serve_single_flight's write then leaves
    the entry expired, so the next poll rebuilds instead of serving a
    pre-expiry snapshot for a full TTL. Freshness, not correctness.
    """
    entry['expires_at'] = 0.0
    entry['dirty'] = True


def invalidate_summary_cache():
    """Drop cached lazy summary-tab payloads."""
    with _summary_cache_lock:
        for entry in _summary_cache.values():
            _reset_cache_entry(entry)


def invalidate_dashboard_cache():
    """Drop the cached dashboard payload so the next request recomputes.

    Clearing 'inflight' here is what makes an invalidation race-safe: any
    job in flight when invalidate fires loses its slot, so the single-flight
    write (guarded on `inflight is job`) skips, leaving the cache empty for
    the next caller to refresh.

    This is the correctness path — for data that changed out from under the
    cache (deletes, migration imports, localization changes). New detections
    are a freshness event and use expire_dashboard_cache() instead.
    """
    with _dashboard_cache_lock:
        _reset_cache_entry(_dashboard_cache)
    invalidate_summary_cache()


def expire_dashboard_cache():
    """Expire the dashboard payload and 'today' summary; leave the rest warm.

    The freshness path for new detections (see _expire_cache_entry for the
    keep-payload/keep-inflight semantics). week/month/allTime are left alone
    entirely: one detection moves those counters by +1, and hard-expiring
    them per detection is what used to keep every summary permanently cold
    on active stations (detections arrive faster than the poll interval).
    """
    with _dashboard_cache_lock:
        _expire_cache_entry(_dashboard_cache)
    with _summary_cache_lock:
        _expire_cache_entry(_summary_cache['today'])


def invalidate_gallery_cache():
    """Drop cached Bird Gallery payloads (Most/Least Frequent + Species Catalog).

    Called when detections change in bulk (delete, migration import) or when a
    settings change alters localization — but never from broadcast_detection();
    see the _gallery_cache comment for that rationale.
    """
    with _gallery_cache_lock:
        for entry in _gallery_cache.values():
            _reset_cache_entry(entry)


def _serve_single_flight(entry, lock, ttl, builder, *args):
    """Serve a cached payload from `entry`, recomputing via `builder` under a
    single-flight guard so concurrent misses share one DB job.

    `entry` is a dict with 'payload'/'expires_at'/'inflight'/'dirty'. Only the
    caller whose job is still the 'inflight' slot writes the cache: if an
    invalidation cleared 'inflight' mid-compute, the `is job` guard fails and
    the write is skipped, so a job racing an invalidation cannot poison the
    cache. A soft expiry (_expire_cache_entry) instead keeps the job but marks
    the entry 'dirty', so the completed payload is served without earning a
    fresh TTL — its DB snapshot may predate whatever fired the expiry.
    """
    with lock:
        cached = entry['payload']
        if cached is not None and entry['expires_at'] > time.time():
            return cached

        job = entry['inflight']
        if job is None:
            job = _submit_db(builder, *args)
            entry['inflight'] = job
            # This job's DB snapshot postdates any expiry recorded so far.
            entry['dirty'] = False

    try:
        payload = job.result(timeout=_DB_JOB_TIMEOUT_SECONDS)
    except Exception:
        with lock:
            if entry['inflight'] is job:
                entry['inflight'] = None
        raise

    with lock:
        if entry['inflight'] is job:
            entry['payload'] = payload
            entry['expires_at'] = 0.0 if entry['dirty'] else time.time() + ttl
            entry['inflight'] = None

    return payload


def _build_summary_period_payload(period, *, settings=None, now=None):
    now = now or local_now()
    settings = settings or load_user_settings()
    summary = db_manager.get_summary_stats_for_period(
        _summary_period_start(period, now),
        now=now,
    )
    return _localize_summary(summary, settings=settings)


def _get_summary_period_payload(period):
    return _serve_single_flight(
        _summary_cache[period], _summary_cache_lock,
        _SUMMARY_CACHE_TTL_SECONDS[period], _build_summary_period_payload, period,
    )


def _build_sightings_payload(most_frequent):
    """Build a localized Most/Least Frequent payload for the gallery cache."""
    settings = load_user_settings()
    sightings = db_manager.get_species_sightings(
        limit=_GALLERY_SIGHTINGS_LIMIT, most_frequent=most_frequent,
    )
    # Cached + shared across tiers -> always emit the anonymous-safe variant.
    return _localize_detection_list(sightings, settings=settings, public_only=True)


def _build_species_all_payload():
    """Build the localized Species Catalog payload for the gallery cache."""
    settings = load_user_settings()
    species = db_manager.get_all_unique_species()
    return _localize_species_list(species, settings=settings)


def _build_dashboard_payload():
    """Compute the dashboard payload with only the visible summary period."""
    now = local_now()
    today = now.strftime('%Y-%m-%d')
    settings = load_user_settings()

    recent_all = db_manager.get_latest_detections(7)
    recent_unique = db_manager.get_latest_detections(7, unique=True)
    # Cached + shared across tiers -> always emit the anonymous-safe variant
    # (the dashboard never displays source_label, so owners lose nothing here).
    recent_all = _localize_detection_list(recent_all, settings=settings, public_only=True)
    recent_unique = _localize_detection_list(recent_unique, settings=settings, public_only=True)
    latest = recent_all[0] if recent_all else None

    summary = {
        'today': _build_summary_period_payload('today', settings=settings, now=now)
    }

    hourly_activity = db_manager.get_hourly_activity(today)
    activity_overview = _localize_activity_overview(
        db_manager.get_activity_overview_both(today),
        settings=settings,
    )

    return {
        'latestObservation': latest,
        'recentObservations': {'all': recent_all, 'unique': recent_unique},
        'summary': summary,
        'hourlyActivity': hourly_activity,
        'activityOverview': activity_overview
    }


@api.route('/api/dashboard', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_dashboard():
    """Consolidated dashboard endpoint — all DB data in one request.

    Cached for _DASHBOARD_CACHE_TTL_SECONDS via _serve_single_flight, so a
    thundering herd of polls from multiple tabs costs one DB pass, not N.
    """
    payload = _serve_single_flight(
        _dashboard_cache, _dashboard_cache_lock,
        _DASHBOARD_CACHE_TTL_SECONDS, _build_dashboard_payload,
    )
    return jsonify(payload)


@api.route('/api/dashboard/summary', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_dashboard_summary():
    """Return one dashboard summary period for lazy-loaded Summary tabs."""
    period = request.args.get('period', default='today')
    if period not in _SUMMARY_PERIODS:
        return jsonify({
            'error': f'Invalid period. Must be one of: {", ".join(_SUMMARY_PERIODS)}'
        }), 400

    summary = _get_summary_period_payload(period)
    log_data_metrics('get_dashboard_summary', summary, {
        'period': period,
        'total_observations': summary.get('totalObservations', 0),
        'unique_species': summary.get('uniqueSpecies', 0),
    })
    return jsonify(summary)


@api.route('/api/sightings/unique', methods=['GET'])
@require_scope('public:read')
@log_api_request
@validate_date_param(required=True)
@handle_api_errors
def get_unique_detections():
    date_str = request.args.get('date')
    # Anonymous callers are limited to the recent window: a past-date query would
    # otherwise let them date-walk historical species-by-day metadata. The gallery
    # only ever requests today's date, so this doesn't affect the public UI.
    if (
        get_request_tier() == 'public'
        and date_str
        and date_str < _public_window_cutoff_date()
    ):
        return jsonify([])
    settings = load_user_settings()
    # Get the unique detections from the database
    unique_detections = _run_db(
        db_manager.get_detections_by_date_range,
        date_str,
        date_str,
        unique=True,
    )
    unique_detections = _localize_detection_list(unique_detections, settings=settings)
    log_data_metrics('get_unique_detections', unique_detections, {
        'date': date_str,
        'unique_species': len(unique_detections)
    })
    return jsonify(unique_detections)

@api.route('/api/sightings', methods=['GET'])
@require_scope('public:read')
@validate_limit_param(default=_GALLERY_SIGHTINGS_LIMIT)
@handle_api_errors
def get_sightings():
    """Consolidated endpoint for different types of sightings

    Query params:
    - type: 'frequent' or 'rare' (default: 'frequent')
    - limit: number of results (default: 12)
    """
    sighting_type = request.args.get('type', 'frequent')
    limit = request.args.get('limit', default=_GALLERY_SIGHTINGS_LIMIT, type=int)

    if sighting_type not in ('frequent', 'rare'):
        return jsonify({"error": "Invalid sighting type. Use 'frequent' or 'rare'"}), 400
    most_frequent = sighting_type == 'frequent'

    if limit == _GALLERY_SIGHTINGS_LIMIT:
        key = _GALLERY_KEY_FREQUENT if most_frequent else _GALLERY_KEY_RARE
        return jsonify(_serve_single_flight(
            _gallery_cache[key], _gallery_cache_lock,
            _GALLERY_CACHE_TTL_SECONDS, _build_sightings_payload, most_frequent,
        ))

    settings = load_user_settings()
    sightings = _run_db(
        db_manager.get_species_sightings, limit=limit, most_frequent=most_frequent,
    )
    return jsonify(_localize_detection_list(sightings, settings=settings))


def _share_token_authorizes_file(token, filename):
    """True if a share token's own detection owns this audio/spectrogram file."""
    detection_id = share_token_subject(token)
    if detection_id is None:
        return False
    detection = _run_db(db_manager.get_detection_by_id, detection_id)
    if detection is None:
        return False
    return filename in (
        detection.get('audio_filename'),
        detection.get('spectrogram_filename'),
    )


def _media_request_authorized(filename):
    """Whether the current request may fetch this media file.

    Owners (and auth-off installs) always may. A share token authorizes its own
    detection's two files even when public access is off (a private station can
    still share one detection's clip). Otherwise an anonymous caller needs a
    valid signed URL, and only while public access is on — so the deterministic
    filenames listed in public payloads can't be turned into a bulk download.

    Checked BEFORE serve_file_with_fallback, which returns a 200 placeholder on
    any miss: letting that run for an unauthorized request would leak access (and
    mask a broken gate) instead of returning 401.
    """
    if is_authenticated():
        return True
    share = request.args.get('s')
    if share and _share_token_authorizes_file(share, filename):
        return True
    if not is_public_access_enabled():
        return False
    return verify_media_signature(
        filename, request.args.get('exp'), request.args.get('sig'),
    )


@api.route('/api/audio/<filename>')
def serve_audio(filename):
    if not _media_request_authorized(filename):
        return jsonify({'error': 'Authentication required'}), 401
    return serve_file_with_fallback(EXTRACTED_AUDIO_DIR, filename, DEFAULT_AUDIO_PATH, "audio")

@api.route('/api/spectrogram/<filename>')
def serve_spectrogram(filename):
    if not _media_request_authorized(filename):
        return jsonify({'error': 'Authentication required'}), 401
    return serve_file_with_fallback(SPECTROGRAM_DIR, filename, DEFAULT_IMAGE_PATH, "spectrogram")

@api.route('/api/bird/<species_name>', methods=['GET'])
@require_scope('public:read')
@log_api_request
def get_bird_details(species_name):
    settings = load_user_settings()
    sci, common = _resolve_species_filter(species_name)
    details = _run_db(db_manager.get_bird_details, common, scientific_name=sci)
    if details:
        details = _localize_detection(details, settings=settings)
        logger.debug("Bird details retrieved", extra={
            'species': species_name,
            'resolved_scientific': sci,
            'total_detections': details.get('detectionCount', 0)
        })
        return jsonify(details)
    return jsonify({"error": "Bird species not found"}), 404

@api.route('/api/bird/<species_name>/image', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def upload_bird_image(species_name):
    """Upload a custom image for a bird species."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    # Validate extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({'error': f'Invalid file type. Allowed: {", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))}'}), 400

    # Validate file size
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_IMAGE_SIZE:
        return jsonify({'error': f'File too large. Maximum size is {MAX_IMAGE_SIZE // (1024 * 1024)}MB'}), 400

    if size == 0:
        return jsonify({'error': 'File is empty'}), 400

    # Validate magic bytes
    if not _validate_image_magic_bytes(file):
        return jsonify({'error': 'File does not appear to be a valid image'}), 400

    os.makedirs(CUSTOM_BIRD_IMAGES_DIR, exist_ok=True)
    _delete_custom_image(species_name)
    final_path = os.path.join(CUSTOM_BIRD_IMAGES_DIR, _sanitize_species_filename(species_name) + ext)
    file.save(final_path)

    logger.info("Custom bird image uploaded", extra={'species': species_name})
    return jsonify({'hasCustomImage': True})


@api.route('/api/bird/<species_name>/image', methods=['GET'])
@require_scope('public:read')
def serve_bird_image(species_name):
    """Serve a custom bird image."""
    _, filename = _get_custom_image_path(species_name)
    if filename:
        return send_from_directory(CUSTOM_BIRD_IMAGES_DIR, filename)
    return jsonify({'error': 'No custom image found'}), 404


@api.route('/api/bird/<species_name>/image', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def delete_bird_image(species_name):
    """Delete a custom bird image. Idempotent - always returns 200."""
    _delete_custom_image(species_name)
    logger.info("Custom bird image deleted", extra={'species': species_name})
    return jsonify({'hasCustomImage': False})


# Extra recordings fetched beyond the requested page so that filtering out rows
# whose audio/spectrogram files are missing from disk still fills the page.
RECORDINGS_MEDIA_OVERFETCH = 16

# Hard ceiling on how many recordings a single request may return. An omitted or
# oversized ``limit`` previously fell through to the DB as ``LIMIT -1`` (unbounded),
# letting a caller pull a species' entire detection history — and every audio
# filename — in one request: the cleanest full-DB scrape path. The frontend only
# ever asks for small pages (<=16), so this ceiling never affects the UI.
RECORDINGS_MAX_LIMIT = 500

# Tighter per-request cap for anonymous (auth-on, not-signed-in) callers, so the
# public bird-detail view still works (it asks for <=16) but a scripted crawl
# gets only a recent slice per species, not the archive. Owners are uncapped
# beyond RECORDINGS_MAX_LIMIT.
RECORDINGS_PUBLIC_MAX = 30

# Recency window for anonymous callers: the public view shows only the recent
# slice, so an anonymous caller can't pull a species' old all-time clips (incl.
# high-confidence ones via 'best' sort), nor id-walk historical detections via
# the by-id permalink. Owners and share-token holders are not windowed.
RECORDINGS_PUBLIC_WINDOW_DAYS = 30


def _public_window_cutoff():
    """ISO timestamp lower bound for the anonymous recent window.

    Floored to midnight (whole days) so every consumer agrees on one boundary:
    the recordings/by-id ``since`` filters, the media-signature gate
    (``_within_public_window``), and the Detections table — which floors an
    anonymous ``start_date`` to ``YYYY-MM-DD``. Without the floor the table
    floored by date but the signature gate compared the full timestamp, so rows
    earlier in the cutoff day than the current time were shown to anonymous
    callers with unplayable (unsigned) media. Whole-day granularity keeps the
    window ~30 calendar days and makes the two agree exactly.
    """
    cutoff_day = (local_now() - timedelta(days=RECORDINGS_PUBLIC_WINDOW_DAYS)).date()
    return f'{cutoff_day.isoformat()}T00:00:00'


def _public_window_cutoff_date():
    """The window boundary as a bare ``YYYY-MM-DD``, for date-granular params.

    Lives next to _public_window_cutoff so the "first 10 chars of the ISO
    timestamp = the date" layout knowledge stays in one place — consumers
    comparing bare dates (table start_date, sightings/unique date-walk) must
    use the SAME day the timestamp consumers use.
    """
    return _public_window_cutoff()[:10]


def _within_public_window(detection, cutoff=None):
    """Whether a detection is recent enough to be in the anonymous public view.

    ``cutoff`` may be passed in (computed once per request) to avoid recomputing
    the window boundary for every row of a list payload.
    """
    timestamp = detection.get('timestamp')
    return bool(timestamp) and str(timestamp) >= (cutoff or _public_window_cutoff())


@api.route('/api/bird/<species_name>/recordings', methods=['GET'])
@require_scope('public:read')
@log_api_request
def get_bird_recordings(species_name):
    """Get recordings for a species with sorting options.

    Query params:
    - sort: 'recent' (default, timestamp DESC) or 'best' (confidence DESC)
    - limit: optional max number of records (omit for all)
    """
    sort = request.args.get('sort', 'recent')
    requested_limit = request.args.get('limit', type=int)  # None if not provided

    # Validate sort parameter
    if sort not in ['recent', 'best']:
        return jsonify({"error": "Sort must be 'recent' or 'best'"}), 400

    # Always bound the query. An omitted or oversized limit must never become an
    # unbounded scan (SQLite LIMIT -1) — that let an unauthenticated caller dump
    # a species' entire history (and every audio filename) in one request.
    if requested_limit is None:
        limit = RECORDINGS_MAX_LIMIT
    else:
        limit = max(1, min(requested_limit, RECORDINGS_MAX_LIMIT))

    # Anonymous (auth-on, not signed in) callers get a tighter, recency-windowed
    # slice per species — the bird-detail UI only asks for <=16, so this keeps the
    # public view working while denying a scripted per-species history dump and
    # old all-time 'best' clips.
    since = None
    if get_request_tier() == 'public':
        limit = min(limit, RECORDINGS_PUBLIC_MAX)
        since = _public_window_cutoff()

    settings = load_user_settings()
    sci, common = _resolve_species_filter(species_name)

    # Skip recordings whose audio/spectrogram files are gone from disk (storage
    # cleanup removes the files but keeps the row; spectrogram generation can
    # also fail independently). Over-fetch a small constant beyond the requested
    # page so dropping those doesn't leave the grid short — the displayed records
    # normally sit inside cleanup's protected window, so few (if any) are dropped.
    fetch_limit = limit + RECORDINGS_MEDIA_OVERFETCH
    fetched = _run_db(
        db_manager.get_bird_recordings,
        common,
        sort,
        fetch_limit,
        scientific_name=sci,
        since=since,
    )
    present = [
        r for r in fetched
        if recording_has_media(r, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR)
    ]
    # Trim to the requested page (present[:None] is a no-op for the unlimited
    # case), then localize only the records we actually return.
    recordings = _localize_detection_list(present[:limit], settings=settings)

    logger.debug("Bird recordings retrieved", extra={
        'species': species_name,
        'resolved_scientific': sci,
        'sort': sort,
        'limit': limit,
        'fetched_count': len(fetched),
        'records_count': len(recordings)
    })
    return jsonify(recordings)

def _detection_view_entitled(detection, detection_id):
    """May the current request read this one detection (by-id permalink AND its
    OG share card — single owner of the rule so the two can never drift)?

    Owner always; a valid ``?s=`` share token grants exactly this detection
    (any age, even when public access is off); otherwise anonymous may read it
    only within the public recent window — so the historical archive can't be
    id-walked. Callers shape their own denial (404 vs. generic card) so the
    endpoint stays existence-oracle-free.
    """
    if detection is None:
        return False
    if is_authenticated():
        return True
    share = request.args.get('s')
    if share and verify_share_token(share, detection_id):
        return True
    return is_public_access_enabled() and _within_public_window(detection)


@api.route('/api/bird/<species_name>/recording/<int:recording_id>', methods=['GET'])
@log_api_request
def get_bird_recording(species_name, recording_id):
    """Get a single recording by ID for share / deep-link permalinks.

    Unlike the paged ``/recordings`` endpoint, this resolves a recording by its
    stable ID regardless of the recent/best sort window, so a shared link
    works even when the detection isn't among the top results. The recording
    must belong to the requested species (keeps permalinks coherent), else 404.

    ``has_media`` reports whether the audio/spectrogram files still exist:
    storage cleanup can delete them while keeping the row, so the client shows
    a graceful "no longer available" notice instead of a dead player.
    """
    # Mirror the recordings list filter: by scientific_name when the route name
    # resolves to a known species, otherwise by the legacy common_name.
    sci, common = _resolve_species_filter(species_name)

    detection = _run_db(db_manager.get_detection_by_id, recording_id)
    if detection is None:
        return jsonify({"error": "Recording not found"}), 404

    belongs = (
        detection.get('scientific_name') == sci if sci
        else detection.get('common_name') == common
    )
    if not belongs:
        # Return the SAME 404 as a missing id (not "...for this species"): a
        # distinct message let a caller distinguish "id exists under another
        # species" from "id doesn't exist", an existence oracle for DB size.
        return jsonify({"error": "Recording not found"}), 404

    # Access control (manual, not @require_scope, so a share token grants access
    # even when public access is off — see _detection_view_entitled). 404 (not
    # 401) on denial so the endpoint can't be probed for which ids exist.
    if not _detection_view_entitled(detection, recording_id):
        return jsonify({"error": "Recording not found"}), 404

    settings = load_user_settings()
    recording = _localize_detection(detection, settings=settings)
    recording['has_media'] = recording_has_media(
        recording, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR,
    )
    # Same-species sibling detections from the same source recording, so the
    # player's analysis-window bar can label every 3s window that fired — not
    # just this row's. Added after _localize_detection on purpose: it's safe
    # for public/share viewers (timestamps + confidence of the same species
    # within the same few seconds of audio; no ids, no location, no source).
    recording['group_detections'] = _run_db(
        db_manager.get_group_detection_windows, detection)
    return jsonify(recording)


@api.route('/api/detections/<int:detection_id>/share', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def create_share_link(detection_id):
    """Mint a share token for one detection (owner only).

    The token authorizes read of exactly this detection (its id is a signed
    claim) plus its two media files — see core.share_tokens. The frontend builds
    the shareable URL from the returned token, so base-href/ingress prefixes are
    handled client-side.
    """
    detection = _run_db(db_manager.get_detection_by_id, detection_id)
    if detection is None:
        return jsonify({'error': 'Recording not found'}), 404

    token = mint_share_token(detection_id)
    return jsonify({'token': token})


# hostname/IPv4 (dots, hyphens), IPv6 ([...]), optional :port — nothing else,
# so a forged forwarding header can't smuggle a path, userinfo, or markup into
# the absolute URLs reflected on the OG card.
_FORWARDED_HOST_RE = re.compile(r'^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:]+\](:\d{1,5})?$')


def _external_base_url():
    """Best-effort external origin (``scheme://host``) for absolute share/OG URLs.

    nginx forwards the externally requested scheme/host via X-Forwarded-Proto /
    X-Forwarded-Host (see ``frontend/nginx.conf``); fall back to the request's
    own scheme/host for direct access. Proxy chains can comma-join these, so we
    take the first (outermost) hop.

    Both headers are ultimately client-controlled (nginx copies the client's
    own ``Host`` into X-Forwarded-Host), so constrain them to a plain
    http(s)://host[:port] shape — a forged header degrades to the request's own
    scheme/host instead of planting an arbitrary URL on the card.
    """
    proto = forwarded_scheme()
    host = request.headers.get('X-Forwarded-Host', '').split(',')[0].strip()
    if not _FORWARDED_HOST_RE.match(host):
        host = request.host
    return f"{proto}://{host}"


@api.route('/api/og/recording/<int:recording_id>', methods=['GET'])
@log_api_request
def get_recording_og_card(recording_id):
    """Server-rendered Open Graph card for a detection permalink.

    A shared link (``/bird/<name>/recording/<id>``) is a client-rendered SPA
    route, so link-unfurl crawlers — which read ``<head>`` meta tags but never
    run JS — get only the static ``index.html`` and preview the link as a bare
    URL. nginx routes *only* known crawler user-agents here (humans still get
    the SPA); this returns a tiny HTML doc whose ``<head>`` carries
    per-detection OG/Twitter tags.

    Resolution is by ID alone (the species segment is decorative) to avoid
    URL-encoding pitfalls with species names containing spaces. A stale/deleted
    detection falls back to a generic branded card so the link still previews.
    Every card carries the app's branded bird illustration as ``og:image`` so it
    unfurls as a large-thumbnail card (which also reveals the description on
    iMessage). A per-detection image isn't used: the only per-detection raster is
    a WebP spectrogram, which unfurlers don't reliably render.

    Access mirrors the by-id permalink gate (owner / share token / public
    recent window): the card is derived from the same data the permalink would
    serve, so it must not reveal more. Crawlers are anonymous, so on an
    auth-enabled station a detection outside the anonymous view unfurls as the
    SAME generic branded card as a nonexistent id — the link still previews
    (title + illustration), it names no species, and the route can't be
    id-walked as an existence oracle for private detections.
    """
    base = _external_base_url()
    image_url = f"{base}{OG_CARD_IMAGE_PATH}"

    detection = _run_db(db_manager.get_detection_by_id, recording_id)
    if not _detection_view_entitled(detection, recording_id):
        return Response(render_og_card(
            title="Bird detections",
            description="Live bird detections from a BirdNET listening station.",
            url=f"{base}/",
            image_url=image_url,
        ), mimetype='text/html')

    settings = load_user_settings()
    recording = _localize_detection(detection, settings=settings)

    common = recording.get('common_name') or 'Unknown species'
    display = recording.get('display_common_name') or common
    # Canonical SPA permalink. Use common_name (which the SPA route resolves
    # against) for the path segment, properly URL-encoded.
    share_url = f"{base}/bird/{quote(common, safe='')}/recording/{recording_id}"

    # iMessage's no-image summary card mostly shows the title, so it leads with
    # the app and the species ("BirdNET-PiPy overheard a Northern Cardinal").
    # "overheard" (not "spotted") keeps it accurate — detection is acoustic, the
    # bird is heard, never seen. The scientific name / confidence / time ride
    # along in the description for platforms (Slack, Discord, …) that show it.
    title = f"BirdNET-PiPy overheard {indefinite_article(display)} {display}"

    return Response(render_og_card(
        title=title,
        description=format_og_description(recording),
        url=share_url,
        image_url=image_url,
    ), mimetype='text/html')


@api.route('/api/bird/<species_name>/detection_distribution', methods=['GET'])
@require_scope('public:read')
@validate_date_param()
@handle_api_errors
def get_detection_distribution(species_name):
    view = request.args.get('view', 'month')
    date = request.args.get('date', local_now().strftime('%Y-%m-%d'))
    sci, common = _resolve_species_filter(species_name)
    distribution = _run_db(
        db_manager.get_detection_distribution,
        common, view, date, scientific_name=sci,
    )
    return jsonify(distribution)

@api.route('/api/species/all', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_all_species():
    """Get all unique bird species ever detected (Species Catalog).

    Served from the single-flight gallery cache; each species carries
    ``last_detected`` so the frontend needs no per-species detail fetch.
    """
    species_list = _serve_single_flight(
        _gallery_cache[_GALLERY_KEY_SPECIES], _gallery_cache_lock,
        _GALLERY_CACHE_TTL_SECONDS, _build_species_all_payload,
    )
    log_data_metrics('get_all_species', species_list)
    return jsonify(species_list)


@api.route('/api/detections/trends', methods=['GET'])
@log_api_request
@require_feature('charts')
@handle_api_errors
def get_detection_trends():
    """Get daily detection counts for trend visualization.

    Query params:
    - start_date: Start date (YYYY-MM-DD) - required
    - end_date: End date (YYYY-MM-DD) - required

    Returns:
        JSON: {'labels': ['2024-01-01', ...], 'data': [count, ...]}
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Validate required parameters
    if not start_date or not end_date:
        return jsonify({'error': 'Both start_date and end_date are required'}), 400

    # Validate date formats
    for date_param, date_value in [('start_date', start_date), ('end_date', end_date)]:
        try:
            datetime.strptime(date_value, '%Y-%m-%d')
        except ValueError:
            return jsonify({'error': f'Invalid {date_param} format. Use YYYY-MM-DD'}), 400

    # Validate date order
    if start_date > end_date:
        return jsonify({'error': 'start_date must be before or equal to end_date'}), 400

    trends = _run_db(db_manager.get_daily_detection_counts, start_date, end_date)

    log_data_metrics('get_detection_trends', trends, {
        'start_date': start_date,
        'end_date': end_date,
        'days': len(trends.get('labels', []))
    })

    return jsonify(trends)


@api.route('/api/detections', methods=['GET'])
@log_api_request
@require_feature('table')
@handle_api_errors
def get_detections():
    """Get paginated bird detections with optional filtering.

    Query params:
    - page: Page number, 1-indexed (default: 1)
    - per_page: Results per page, max 100 (default: 25)
    - start_date: Start date filter (YYYY-MM-DD)
    - end_date: End date filter (YYYY-MM-DD)
    - species: Filter by common_name
    - hour: Filter by hour of day, integer 0-23
    - sort: Sort field - timestamp, confidence, common_name (default: timestamp)
    - order: Sort order - asc, desc (default: desc)
    """
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=25, type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    species = request.args.get('species')
    sort = request.args.get('sort', default='timestamp')
    order = request.args.get('order', default='desc')

    # Validate date formats if provided
    for date_param, date_value in [('start_date', start_date), ('end_date', end_date)]:
        if date_value:
            try:
                datetime.strptime(date_value, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': f'Invalid {date_param} format. Use YYYY-MM-DD'}), 400

    # Validate hour filter if provided (parsed manually so a non-integer
    # value is a hard 400 rather than being silently dropped).
    hour = None
    hour_raw = request.args.get('hour')
    if hour_raw not in (None, ''):
        try:
            hour = int(hour_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid hour. Use an integer 0-23'}), 400
        if not 0 <= hour <= 23:
            return jsonify({'error': 'Invalid hour. Use an integer 0-23'}), 400

    # Cap per_page at 100 (same as db method)
    per_page = min(max(1, per_page), 100)

    # Anonymous callers (when the owner has published the table) see only the
    # recent window — consistent with the rest of the public view, so table_public
    # can't expose the full historical archive and every visible row's media stays
    # playable (its signature is minted). Owners see the full table. Applies to
    # both query paths below.
    if get_request_tier() == 'public':
        cutoff_date = _public_window_cutoff_date()
        if not start_date or start_date < cutoff_date:
            start_date = cutoff_date

    settings = load_user_settings()
    bird_name_language = get_bird_name_language(settings)
    sci, common = _resolve_species_filter(species)

    if sort == 'common_name' and bird_name_language != DEFAULT_BIRD_NAME_LANGUAGE:
        # Localized labels don't follow database ordering, so order the
        # distinct species by display name here (a few hundred keys) and let
        # SQL assemble just the requested page from that order — materializing
        # every matching row for an in-memory sort OOMs small devices once
        # the table reaches hundreds of thousands of rows. The species list
        # is unfiltered on purpose: the page query below applies the filters,
        # and species outside them just yield empty buckets.
        ordered_species = _localized_species_order(
            _run_db(db_manager.get_distinct_species_pairs),
            settings,
            descending=order.lower() != 'asc',
        )
        detections, total_count = _run_db(
            db_manager.get_paginated_detections_localized,
            ordered_species,
            page=page,
            per_page=per_page,
            start_date=start_date,
            end_date=end_date,
            species=common,
            scientific_name=sci,
            hour=hour,
        )
    else:
        detections, total_count = _run_db(
            db_manager.get_paginated_detections,
            page=page,
            per_page=per_page,
            start_date=start_date,
            end_date=end_date,
            species=common,
            sort=sort,
            order=order,
            scientific_name=sci,
            hour=hour,
        )
    detections = _localize_detection_list(detections, settings=settings)

    total_pages = (total_count + per_page - 1) // per_page if per_page > 0 else 0

    return jsonify({
        'detections': detections,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_items': total_count,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
    })


@api.route('/api/detections/export', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def export_detections_csv():
    """Export all detections as a CSV file, streamed in batches.

    Requires authentication. The response is generated batch by batch so an
    export of a very large table holds only one batch in memory at a time.

    Query params (optional):
    - start_date: Start date filter (YYYY-MM-DD)
    - end_date: End date filter (YYYY-MM-DD)
    - species: Filter by common_name
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    species = request.args.get('species')

    # Validate date formats if provided
    for date_param, date_value in [('start_date', start_date), ('end_date', end_date)]:
        if date_value:
            try:
                datetime.strptime(date_value, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': f'Invalid {date_param} format. Use YYYY-MM-DD'}), 400

    sci, common = _resolve_species_filter(species)

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            'id', 'timestamp', 'group_timestamp', 'scientific_name', 'common_name',
            'confidence', 'latitude', 'longitude', 'cutoff', 'sensitivity', 'overlap',
            'week', 'extra', 'audio_source'
        ])

        before_timestamp = before_id = None
        try:
            while True:
                # Each batch is its own short executor-lane job, so a long
                # export shares the single DB lane with live requests instead
                # of holding it (and every row in memory) for the download.
                batch = _run_db(
                    db_manager.get_detections_for_export_batch,
                    start_date=start_date,
                    end_date=end_date,
                    species=common,
                    scientific_name=sci,
                    before_timestamp=before_timestamp,
                    before_id=before_id,
                    limit=_EXPORT_BATCH_ROWS,
                )
                for detection in batch:
                    # Handle extra field - ensure NULL/None becomes '{}'
                    extra_value = detection.get('extra')
                    if extra_value is None:
                        extra_value = '{}'

                    writer.writerow([
                        detection.get('id', ''),
                        detection.get('timestamp', ''),
                        detection.get('group_timestamp', ''),
                        detection.get('scientific_name', ''),
                        detection.get('common_name', ''),
                        detection.get('confidence', ''),
                        detection.get('latitude', ''),
                        detection.get('longitude', ''),
                        detection.get('cutoff', ''),
                        detection.get('sensitivity', ''),
                        detection.get('overlap', ''),
                        detection.get('week', ''),
                        extra_value,
                        detection.get('audio_source', '')
                    ])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
                if len(batch) < _EXPORT_BATCH_ROWS:
                    return
                before_timestamp = batch[-1]['timestamp']
                before_id = batch[-1]['id']
        except Exception:
            # Response headers are already sent; log why the download broke
            # off and let the stream abort so the client sees a failed
            # transfer rather than a silently complete-looking file.
            logger.exception("CSV export aborted mid-stream")
            raise

    # Generate filename with timestamp
    timestamp = local_now().strftime('%Y%m%d_%H%M%S')
    filename = f'birdnet_detections_{timestamp}.csv'

    return Response(
        generate(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@api.route('/api/detections/<int:detection_id>', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def delete_detection(detection_id):
    """Delete a detection and its associated files.

    Requires authentication.
    """
    # delete_detection returns the detection row so we can clean up the
    # associated audio + spectrogram files below.
    detection = _run_db(db_manager.delete_detection, detection_id)

    if not detection:
        return jsonify({'error': 'Detection not found'}), 404

    invalidate_dashboard_cache()
    invalidate_gallery_cache()

    # Clean up associated files using shared utility
    delete_result = delete_detection_files(detection)

    # Build files_deleted list for response
    files_deleted = []
    if delete_result['deleted_audio']:
        files_deleted.append(detection['audio_filename'])
    if delete_result['deleted_spectrogram']:
        files_deleted.append(detection['spectrogram_filename'])

    logger.info("Detection deleted with files", extra={
        'detection_id': detection_id,
        'species': detection['common_name'],
        'files_deleted': files_deleted
    })

    return jsonify({
        'status': 'deleted',
        'id': detection_id,
        'species': detection['common_name'],
        'files_deleted': files_deleted
    })


@api.route('/api/detections/batch', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def delete_detections_batch():
    """Delete multiple detections and their associated files.

    Requires authentication.
    Request body: { "ids": [1, 2, 3, ...] }
    Max 100 items per request.
    """
    data = request.json
    if not data or 'ids' not in data:
        return jsonify({'error': 'Missing ids array'}), 400

    ids = data['ids']
    if not isinstance(ids, list):
        return jsonify({'error': 'ids must be an array'}), 400

    if len(ids) == 0:
        return jsonify({'error': 'ids array is empty'}), 400

    if len(ids) > 100:
        return jsonify({'error': 'Maximum 100 items per batch'}), 400

    deleted = []
    failed = []

    for detection_id in ids:
        if not isinstance(detection_id, int):
            failed.append({'id': detection_id, 'error': 'Invalid ID type'})
            continue

        detection = _run_db(db_manager.delete_detection, detection_id)
        if not detection:
            failed.append({'id': detection_id, 'error': 'Not found'})
            continue

        # Clean up associated files using shared utility
        delete_detection_files(detection)

        deleted.append(detection_id)

    if deleted:
        invalidate_dashboard_cache()
        invalidate_gallery_cache()

    logger.info("Batch deletion completed", extra={
        'deleted_count': len(deleted),
        'failed_count': len(failed)
    })

    return jsonify({
        'deleted': len(deleted),
        'failed': len(failed),
        'deleted_ids': deleted,
        'errors': failed
    })


# Cache for available species (loaded from model labels file)
# Keyed by model type so switching models invalidates cache
_available_species_cache = {}


def _resolve_species_filter(name):
    """Map a route-supplied English bird name to a DB filter pair.

    Returns ``(scientific_name, common_name)`` where exactly one is populated.
    When the resolver recognises the input (canonical common_name, V2 label_en,
    or label_en_uk), we filter the underlying query by ``scientific_name`` —
    this is what merges V2's "Eurasian Blackbird" and V3's "Common Blackbird"
    history for the same Turdus merula into a single result.

    When the resolver misses (unknown English string, legacy migration row),
    we fall back to filtering by ``common_name`` so the user keeps access to
    data the species table doesn't know about.
    """
    if not name:
        return None, None
    sci = resolve_to_scientific_name(name)
    return (sci, None) if sci else (None, name)


def _strip_private_fields(detection):
    # Endpoint-level guard (defense in depth). The data layer already drops
    # PRIVATE_DETECTION_FIELDS in DatabaseManager._normalize_detection; this also
    # covers any path that builds a payload from coordinates obtained another
    # way. Both layers share the same tuple (imported from core.db) so the
    # private-field list has a single source of truth.
    if isinstance(detection, dict):
        for field in PRIVATE_DETECTION_FIELDS:
            detection.pop(field, None)
    return detection


def _add_media_signatures(detection, cutoff=None):
    """Attach short-lived signed query strings (``audio_sig``/``spectrogram_sig``)
    so an anonymous client can fetch exactly this detection's audio/spectrogram.

    Only minted for detections within the public recency window. So an
    anonymous caller never receives a working media URL for an OLD clip via ANY
    payload path (sightings, sightings/unique date-walk, dashboard samples, etc.),
    not just the recordings list. Owners still play old clips via their session
    (the bare-filename request is authorized by the cookie); share links use the
    token, not the signature. Handles both field-name conventions (recordings use
    ``audio_filename``; the dashboard/recent path renames to ``bird_song_file_name``).
    See core.media_access.
    """
    if not isinstance(detection, dict) or not _within_public_window(detection, cutoff):
        return detection
    audio_fn = detection.get('audio_filename') or detection.get('bird_song_file_name')
    if audio_fn:
        detection['audio_sig'] = sign_media_query(audio_fn)
    spectrogram_fn = (
        detection.get('spectrogram_filename') or detection.get('spectrogram_file_name')
    )
    if spectrogram_fn:
        detection['spectrogram_sig'] = sign_media_query(spectrogram_fn)
    return detection


# Extra-blob keys safe to expose to anonymous callers. Anything else (notably
# source_label, a user-chosen name that can hint at the station's location or
# layout) is dropped from public payloads, along with the raw audio_source id.
_PUBLIC_EXTRA_KEYS = {'weather'}


def _strip_public_metadata(detection):
    """Drop owner-only metadata (source label/id; any non-weather extra key)
    from a payload bound for an anonymous caller."""
    if not isinstance(detection, dict):
        return detection
    detection.pop('audio_source', None)
    extra = detection.get('extra')
    if isinstance(extra, dict):
        detection['extra'] = {
            key: value for key, value in extra.items()
            if key.lower() in _PUBLIC_EXTRA_KEYS
        }
    return detection


def _localize_detection(detection, settings=None, is_public=None, cutoff=None):
    # add_display_common_name returns a copy, so popping here never mutates the
    # underlying DB row.
    # is_public=None derives the tier from the current request; callers
    # serializing a list pass it (and cutoff) in once, computed per-request,
    # rather than re-deriving them for every row. Off-request-thread callers
    # (the cached payload builders) MUST pass is_public explicitly — there is
    # no request context to derive from.
    if is_public is None:
        is_public = get_request_tier() == 'public'
    localized = _strip_private_fields(add_display_common_name(
        detection,
        language=get_bird_name_language(settings),
        settings=settings,
    ))
    # Anonymous callers get the safe variant: owner-only metadata stripped, and
    # signed media URLs minted (owners fetch media by bare filename via their
    # session, so signatures would be dead payload weight for them). Cached
    # payloads (dashboard/sightings) are built once and shared across tiers, so
    # their builders force is_public=True to keep the cached copy the safe one.
    if is_public:
        _add_media_signatures(localized, cutoff)
        _strip_public_metadata(localized)
    return localized


def _localize_detection_list(detections, settings=None, public_only=False):
    # public_only forces the anonymous-safe variant without consulting the
    # request tier: cached payloads (dashboard/sightings) are built off the
    # request thread, so there is no request context to classify.
    is_public = public_only or get_request_tier() == 'public'
    cutoff = _public_window_cutoff()
    return [
        _localize_detection(detection, settings=settings, is_public=is_public,
                            cutoff=cutoff)
        for detection in detections
    ]


def _localized_species_order(species_pairs, settings=None, *, descending=False):
    """Order scientific names by their localized display name.

    Takes get_distinct_species_pairs output and produces the species order
    that get_paginated_detections_localized pages by, so the species-column
    sort never materializes detection rows. Species sharing a display name
    get a deterministic scientific_name tiebreak.
    """
    language = get_bird_name_language(settings)
    return [sci for _, sci in sorted(
        (
            (get_localized_common_name(sci, common, language=language,
                                       settings=settings).casefold(), sci)
            for sci, common in species_pairs
        ),
        reverse=descending,
    )]


def _localize_species_list(species_list, settings=None):
    # The species catalog is built off the request thread (single-flight gallery
    # cache) and shared across tiers, so it must NOT resolve a request tier per
    # row: get_request_tier() -> is_authenticated() -> session access has no
    # request context on the db-executor thread and raises "Working outside of
    # request context", which hard-500s /api/species/all whenever auth is enabled
    # (the failed build never warms the cache, so every subsequent request 500s
    # too, for owners as well as anonymous callers). public_only=True forces the
    # anonymous-safe variant like the dashboard/sightings builders; catalog rows
    # carry no owner-only metadata (common/scientific name + last_detected
    # only), so the stripping is a no-op on the data.
    localized = _localize_detection_list(species_list, settings=settings, public_only=True)
    localized.sort(key=lambda species: species.get('display_common_name', species.get('common_name', '')))
    return localized


def _localize_summary(summary, settings=None):
    """Add ``mostCommonBirdDisplay`` and ``rarestBirdDisplay`` fields.

    Looks up the translation by ``{key}ScientificName`` (the stable key from
    the DB CTE), so V2's "Eurasian Blackbird" and V3's "Common Blackbird" for
    the same Turdus merula both translate to "Amsel" under German. Falls back
    to the English ``{key}`` value when no scientific name is available
    (legacy rows) or when the summary is empty.
    """
    localized_summary = dict(summary)

    for key in ('mostCommonBird', 'rarestBird'):
        bird_name = localized_summary.get(key)
        sci_name = localized_summary.get(f'{key}ScientificName')
        if bird_name and bird_name != 'N/A':
            localized_summary[f'{key}Display'] = get_localized_common_name(
                sci_name,
                bird_name,
                language=get_bird_name_language(settings),
                settings=settings,
            )
        else:
            localized_summary[f'{key}Display'] = bird_name

    return localized_summary


def _localize_activity_overview(activity_overview, settings=None):
    if not activity_overview:
        return activity_overview

    return {
        key: [add_display_species(item, settings=settings) for item in items]
        for key, items in activity_overview.items()
    }


def _localize_activity_items(items, settings=None):
    return [add_display_species(item, settings=settings) for item in items]


def load_available_species():
    """Load all available species from the species table.

    Returns list of dicts with scientific_name and common_name.
    Results are cached per model type since the species table doesn't change at runtime.
    """
    model_type = load_user_settings().get('model', {}).get('type', MODEL_TYPE)

    if model_type in _available_species_cache:
        return _available_species_cache[model_type]

    species_list = get_species_list(model_type)
    _available_species_cache[model_type] = species_list
    logger.info("Loaded available species", extra={
        'count': len(species_list),
        'model_type': model_type,
    })
    return species_list


@api.route('/api/species/available', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_available_species():
    """Get all species available in the BirdNET model.

    Used for building include/exclude filter lists in the UI.
    Returns list of {scientific_name, common_name} sorted by common_name.
    Species count depends on model type: ~6K for V2.4, ~11K for V3.0.
    """
    settings = load_user_settings()
    search = request.args.get('search', '').lower()
    species_list = _localize_species_list(load_available_species(), settings=settings)

    # Filter by search term if provided
    if search:
        species_list = [
            s for s in species_list
            if (
                search in s['scientific_name'].lower()
                or search in s['common_name'].lower()
                or search in s.get('display_common_name', '').lower()
            )
        ]

    return jsonify({
        'species': species_list,
        'total': len(load_available_species()),
        'filtered': len(species_list)
    })

@api.route('/api/stream/config', methods=['GET'])
@log_api_request
@require_feature('live_feed')
@handle_api_errors
def get_stream_config():
    """Provide stream configuration for frontend based on enabled sources."""
    settings = load_user_settings()
    audio = settings.get('audio') or {}
    sources = audio.get('sources', [])
    enabled = [s for s in sources if s.get('enabled', True)]

    streams = []
    for source in enabled:
        sid = source.get('id', '')
        streams.append({
            'source_id': sid,
            'label': source.get('label') or sid,
            'url': f'stream/{sid}.mp3',
        })

    return jsonify({'streams': streams})

@api.route('/api/broadcast/detection', methods=['POST'])
@require_internal
def broadcast_detection_endpoint():
    """Endpoint to broadcast detection via WebSocket.

    Internal-only endpoint - only accessible from docker network or localhost.
    Called by the main processing container to broadcast detections to WebSocket clients.
    """
    try:
        detection_data = request.json
        broadcast_detection(detection_data)
        # Log is handled in broadcast_detection() function to avoid duplication
        return jsonify({'status': 'broadcasted'}), 200
    except Exception as e:
        logger.error("Failed to broadcast detection", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500

@api.route('/api/broadcast/recorder-status', methods=['POST'])
@require_internal
def broadcast_recorder_status_endpoint():
    """Receive recorder health status from main container and broadcast to owners.

    Internal-only endpoint - only accessible from docker network or localhost.
    Called by the main processing container on recorder state changes. The status
    is emitted only to the owner room (authenticated sockets), since it carries
    source labels and error text that must not reach anonymous live_feed clients.
    """
    global _recorder_status
    try:
        _recorder_status = request.json
        if socketio:
            socketio.emit('recorder_status', _recorder_status, room=_OWNER_ROOM)
        logger.debug("Recorder status broadcasted", extra={
            'state': _recorder_status.get('state')
        })
        return jsonify({'status': 'broadcasted'}), 200
    except Exception as e:
        logger.error("Failed to broadcast recorder status", extra={
            'error': str(e)
        })
        return jsonify({'error': str(e)}), 500

@api.route('/api/recorder/status', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def get_recorder_status():
    """Return current recorder health status.

    Requires authentication — the payload may contain source labels,
    types, and error details that should not be exposed publicly.
    Decoupled from live feed so it is not gated by live_feed_public.
    """
    return jsonify(_recorder_status or {})

def write_flag(flag_name, content=None):
    """Write flag file to trigger host action.

    Args:
        flag_name: Name of the flag file (e.g., 'restart-backend', 'update-requested')
        content: Optional content to write. If None, writes timestamp.
                 For update-requested, content should be the target branch name.
    """
    flag_dir = os.path.join(BASE_DIR, 'data', 'flags')
    os.makedirs(flag_dir, exist_ok=True)
    flag_file = os.path.join(flag_dir, flag_name)
    with open(flag_file, 'w') as f:
        f.write(content if content else local_now().isoformat())
    logger.debug("Flag file written", extra={
        'flag': flag_name,
        'content': content,
        'path': flag_file
    })

# GitHub API configuration
GITHUB_OWNER = "Suncuss"
GITHUB_REPO = "BirdNET-PiPy"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
HA_SOURCE_COMMIT_ENV = "BIRDNET_PIPY_SOURCE_COMMIT"
HA_SOURCE_COMMIT_FILE = os.path.join(BASE_DIR, "birdnet_pipy_source_commit.txt")

# How long to wait for HA Core's update entity to refresh after triggering
# homeassistant.update_entity (fire-and-forget) before giving up.
_HA_ENTITY_POLL_TIMEOUT_SECONDS = 15
_HA_ENTITY_POLL_INTERVAL_SECONDS = 0.5

def load_version_info():
    """Load version information from version.json"""
    version_file = os.path.join(BASE_DIR, 'data', 'version.json')

    if not os.path.exists(version_file):
        logger.warning("version.json not found", extra={'path': version_file})
        return None

    try:
        with open(version_file) as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load version.json", extra={'error': str(e)})
        return None


def load_ha_source_commit():
    """Load BirdNET-PiPy source commit baked into HA add-on image."""
    commit_from_env = os.environ.get(HA_SOURCE_COMMIT_ENV, "").strip()
    if commit_from_env:
        return commit_from_env

    if not os.path.exists(HA_SOURCE_COMMIT_FILE):
        return None

    try:
        with open(HA_SOURCE_COMMIT_FILE) as f:
            commit = f.read().strip()
            return commit or None
    except Exception as e:
        logger.warning("Failed to load Home Assistant source commit", extra={
            'path': HA_SOURCE_COMMIT_FILE,
            'error': str(e),
        })
        return None


def call_github_api(endpoint, timeout=10):
    """Call GitHub API and return JSON response"""
    url = f"{GITHUB_API_BASE}/{endpoint}"
    headers = {
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': f'{DISPLAY_NAME}/{__version__}'
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.Timeout:
        return None, "GitHub API request timed out"
    except requests.exceptions.RequestException as e:
        return None, f"GitHub API error: {str(e)}"

def get_commits_comparison(base_commit, target_branch='main'):
    """Compare local commit with remote branch using GitHub API"""
    # NOTE: GitHub API requires three dots (...), not two dots (..)
    # Two-dot syntax causes 404 error
    endpoint = f"compare/{base_commit}...{target_branch}"
    data, error = call_github_api(endpoint)
    if error:
        return None, error

    return {
        'ahead_by': data.get('ahead_by', 0),
        'behind_by': data.get('behind_by', 0),
        'status': data.get('status', 'unknown'),
        'commits': [
            {
                'hash': c['sha'][:7],
                'message': c['commit']['message'].split('\n')[0],
                'date': c['commit']['committer']['date']
            }
            for c in data.get('commits', [])[:10]  # Limit to 10 commits
        ],
        'target_commit': data.get('commits', [{}])[-1].get('sha', '')[:7] if data.get('commits') else ''
    }, None

def get_latest_remote_commit(branch='main'):
    """Get the latest commit on the remote branch"""
    endpoint = f"commits/{branch}"
    data, error = call_github_api(endpoint)

    if error:
        return None, error

    return {
        'sha': data.get('sha', '')[:7],
        'message': data['commit']['message'].split('\n')[0],
        'date': data['commit']['committer']['date']
    }, None

def fetch_update_notes(branch='main'):
    """Fetch deployment/UPDATE_NOTES.json from remote repository

    Returns:
        dict: Update notes with 'message' and 'show_to_versions_before' fields
        None: If file not found or empty/invalid
    """
    url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{branch}/deployment/UPDATE_NOTES.json"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 404:
            logger.debug("UPDATE_NOTES.json not found in remote repository")
            return None
        response.raise_for_status()

        data = response.json()
        message = data.get('message')

        # Return None if no message (same behavior as before)
        if not message:
            return None

        return {
            'message': message,
            'show_to_versions_before': data.get('show_to_versions_before')
        }
    except requests.exceptions.RequestException as e:
        logger.warning("Failed to fetch UPDATE_NOTES.json", extra={'error': str(e)})
        return None
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in UPDATE_NOTES.json")
        return None

def should_show_update_note(current_commit, note_data):
    """Determine if update note should be shown based on version targeting

    Args:
        current_commit: User's current commit hash
        note_data: Dict with 'message' and 'show_to_versions_before'

    Returns:
        bool: True if note should be shown
    """
    if not note_data or not note_data.get('message'):
        return False

    target_commit = note_data.get('show_to_versions_before')

    # If no version targeting, always show
    if not target_commit:
        return True

    # Compare commits: GET /compare/{current_commit}...{target_commit}
    # GitHub API semantics:
    #   - status 'ahead': target is ahead of current (user is on older version)
    #   - status 'behind': target is behind current (user is on newer version)
    #   - status 'identical': commits are the same
    #   - status 'diverged': branches diverged, can't determine order
    #   - ahead_by: how many commits target is ahead of current
    comparison, error = get_commits_comparison(current_commit, target_commit)

    if error:
        # If comparison fails (e.g., commit not found), show the message to be safe
        logger.warning("Could not compare commits for update note", extra={
            'current_commit': current_commit,
            'target_commit': target_commit,
            'error': error
        })
        return True

    status = comparison.get('status', '')
    ahead_by = comparison.get('ahead_by', 0)

    # Handle diverged case: can't determine order, show to be safe
    if status == 'diverged':
        return True

    # Show if user is strictly BEFORE the target (target is ahead of user)
    # 'identical' means user is AT the target commit - don't show (they already have it)
    return status == 'ahead' or ahead_by > 0

VALID_NOTIFICATION_FIELDS = {
    'apprise_urls', 'every_detection', 'rate_limit_seconds',
    'first_of_day', 'new_species', 'rare_species', 'rare_threshold', 'rare_window_days',
    'audio_status'
}

def _validate_notification_settings(notif):
    """Validate notification settings fields.

    Returns error string if invalid, None if valid.
    """
    if not isinstance(notif, dict):
        return 'notifications must be a JSON object'
    unknown = set(notif.keys()) - VALID_NOTIFICATION_FIELDS
    if unknown:
        return f'Unknown notification fields: {", ".join(sorted(unknown))}'
    for bool_field in ('every_detection', 'first_of_day', 'new_species',
                       'rare_species', 'audio_status'):
        if bool_field in notif and not isinstance(notif[bool_field], bool):
            return f'notifications.{bool_field} must be a boolean'
    if 'apprise_urls' in notif:
        urls = notif['apprise_urls']
        if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
            return 'notifications.apprise_urls must be a list of strings'
    if 'rate_limit_seconds' in notif:
        rls = notif['rate_limit_seconds']
        if not isinstance(rls, (int, float)) or rls < 0:
            return 'notifications.rate_limit_seconds must be a non-negative number'
    if 'rare_threshold' in notif:
        rt = notif['rare_threshold']
        if not isinstance(rt, int) or rt < 0:
            return 'notifications.rare_threshold must be a non-negative integer'
    if 'rare_window_days' in notif:
        rwd = notif['rare_window_days']
        if not isinstance(rwd, int) or rwd < 1:
            return 'notifications.rare_window_days must be a positive integer'
    return None


def save_user_settings(settings_dict):
    """Save settings to JSON file atomically"""
    json_path = USER_SETTINGS_PATH
    temp_file = json_path + '.tmp'

    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    # Atomic write
    with open(temp_file, 'w') as f:
        json.dump(settings_dict, f, indent=2)

    os.rename(temp_file, json_path)
    logger.info("User settings saved", extra={
        'path': json_path
    })


def _persist_no_restart_setting(section, key, value):
    """Persist one settings field and refresh the runtime cache (no restart).

    Shared by the instant-save settings endpoints (units, time-format,
    playback): the affected services read the value live from the settings
    file, so writing it and invalidating the runtime-settings cache is enough.
    """
    current_settings = load_user_settings()
    if section not in current_settings:
        current_settings[section] = {}
    current_settings[section][key] = value
    save_user_settings(current_settings)
    invalidate_runtime_settings_cache()


@api.route('/api/settings', methods=['GET'])
@log_api_request
@require_auth
def get_settings():
    """Get all user settings"""
    try:
        settings = load_user_settings()
        return jsonify(settings), 200
    except Exception as e:
        logger.error("Failed to get settings", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500


@api.route('/api/settings/defaults', methods=['GET'])
@log_api_request
@require_auth
def get_default_settings_endpoint():
    """Get default settings (single source of truth for frontend reset).

    Auth-gated: the only caller is the Settings page's fallback when the
    authenticated GET /api/settings load fails, so an unauthenticated client
    has no reason to read this — and the payload carries the default station
    coordinates, which should not be exposed pre-auth.
    """
    try:
        defaults = get_default_settings()
        # Set configured to true for reset (user is explicitly resetting)
        defaults['location']['configured'] = True
        return jsonify(defaults), 200
    except Exception as e:
        logger.error("Failed to get default settings", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500


@api.route('/api/settings/channel', methods=['PUT'])
@log_api_request
@require_auth
def update_channel_setting():
    """Update the update channel setting without triggering a restart.

    The channel setting only affects update checks, not the running service,
    so no restart is needed.
    """
    try:
        if is_home_assistant_mode():
            return jsonify({
                'error': 'Update channels are not supported in Home Assistant mode'
            }), 400

        data = request.json
        if not data or 'channel' not in data:
            return jsonify({'error': 'channel field required'}), 400

        channel = data['channel']
        if channel not in UPDATE_CHANNELS:
            return jsonify({'error': 'Invalid channel. Must be "release" or "latest"'}), 400

        # Load current settings, update channel, save
        current_settings = load_user_settings()
        if 'updates' not in current_settings:
            current_settings['updates'] = {}
        current_settings['updates']['channel'] = channel
        save_user_settings(current_settings)
        invalidate_runtime_settings_cache()

        logger.info("Update channel changed", extra={'channel': channel})

        return jsonify({
            'success': True,
            'channel': channel
        }), 200

    except Exception as e:
        logger.error("Failed to update channel setting", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500


@api.route('/api/settings/units', methods=['PUT'])
@log_api_request
@require_auth
def update_units_setting():
    """Update the display units setting without triggering a restart.

    The units setting only affects frontend display, not the running service,
    so no restart is needed.
    """
    try:
        data = request.json
        if not data or 'use_metric_units' not in data:
            return jsonify({'error': 'use_metric_units field required'}), 400

        use_metric = data['use_metric_units']
        if not isinstance(use_metric, bool):
            return jsonify({'error': 'use_metric_units must be a boolean'}), 400

        _persist_no_restart_setting('display', 'use_metric_units', use_metric)

        logger.info("Display units changed", extra={'use_metric_units': use_metric})

        return jsonify({
            'success': True,
            'use_metric_units': use_metric
        }), 200

    except Exception as e:
        logger.error("Failed to update units setting", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500


@api.route('/api/settings/time-format', methods=['PUT'])
@log_api_request
@require_auth
def update_time_format_setting():
    """Update the display time-format setting without triggering a restart.

    Frontend-only preference for 12-hour vs 24-hour clock display.
    Only explicit user choices are persisted; the absence of a value means
    "detect from browser locale" and is the default for new installs.
    """
    try:
        data = request.json
        if not data or 'time_format' not in data:
            return jsonify({'error': 'time_format field required'}), 400

        time_format = data['time_format']
        if time_format not in ('12h', '24h'):
            return jsonify({'error': "time_format must be '12h' or '24h'"}), 400

        _persist_no_restart_setting('display', 'time_format', time_format)

        logger.info("Display time format changed", extra={'time_format': time_format})

        return jsonify({
            'success': True,
            'time_format': time_format
        }), 200

    except Exception as e:
        logger.error("Failed to update time format setting", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500


@api.route('/api/settings/playback', methods=['PUT'])
@log_api_request
@require_auth
def update_playback_setting():
    """Update the recording-normalization setting without triggering a restart.

    The main container reads playback.normalize from the settings file when it
    saves each detection clip, so the change applies to the next recording with
    no restart.
    """
    try:
        data = request.json
        if not data or 'normalize' not in data:
            return jsonify({'error': 'normalize field required'}), 400

        normalize = data['normalize']
        if not isinstance(normalize, bool):
            return jsonify({'error': 'normalize must be a boolean'}), 400

        _persist_no_restart_setting('playback', 'normalize', normalize)

        logger.info("Recording normalization changed", extra={'normalize': normalize})

        return jsonify({
            'success': True,
            'normalize': normalize
        }), 200

    except Exception as e:
        logger.error("Failed to update playback setting", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500


@api.route('/api/settings/notifications', methods=['PUT'])
@log_api_request
@require_auth
def update_notification_settings():
    """Update notification settings without triggering a restart.

    The main container reads notification config from the settings file
    on each detection, so changes take effect immediately.
    Uses merge semantics: only provided fields are updated.
    """
    try:
        data = request.json
        if not data or not isinstance(data, dict):
            return jsonify({'error': 'Request body must be a JSON object'}), 400

        error = _validate_notification_settings(data)
        if error:
            return jsonify({'error': error}), 400

        # Merge into current settings
        current_settings = load_user_settings()
        current_settings['notifications'].update(data)
        # Deduplicate URLs while preserving order
        urls = current_settings['notifications'].get('apprise_urls')
        if urls:
            current_settings['notifications']['apprise_urls'] = list(dict.fromkeys(urls))
        save_user_settings(current_settings)
        invalidate_runtime_settings_cache()

        logger.info("Notification settings updated", extra={
            'changed_fields': list(data.keys())
        })

        return jsonify({
            'success': True,
            'notifications': current_settings['notifications']
        }), 200

    except Exception as e:
        logger.error("Failed to update notification settings", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500


@api.route('/api/settings', methods=['PUT'])
@log_api_request
@require_auth
def update_settings():
    """Update user settings and apply changes without container restart."""
    try:
        incoming_settings = request.json
        if not incoming_settings:
            return jsonify({'error': 'No settings data provided'}), 400

        current_settings = load_user_settings()
        new_settings = deep_merge_settings(current_settings, incoming_settings)

        # Validate audio settings
        if 'audio' in incoming_settings:
            incoming_audio = incoming_settings['audio']

            # Validate sources array if provided
            sources = incoming_audio.get('sources')
            if sources is not None:
                if not isinstance(sources, list):
                    return jsonify({'error': 'sources must be an array'}), 400
                seen_ids = set()
                mic_count = 0
                for source in sources:
                    sid = source.get('id', '')
                    if not sid or not sid.startswith('source_'):
                        return jsonify({'error': f'Invalid source id: {sid}. Must match source_<int>'}), 400
                    if sid in seen_ids:
                        return jsonify({'error': f'Duplicate source id: {sid}'}), 400
                    seen_ids.add(sid)

                    stype = source.get('type', '')
                    if stype not in ('pulseaudio', 'rtsp'):
                        return jsonify({'error': f'Invalid source type: {stype}. Must be pulseaudio or rtsp'}), 400
                    if stype == 'rtsp':
                        url = source.get('url', '')
                        if not url or not url.startswith(('rtsp://', 'rtsps://')):
                            return jsonify({'error': f'RTSP source {sid} must have a valid rtsp:// or rtsps:// URL'}), 400
                    if stype == 'pulseaudio':
                        mic_count += 1
                if mic_count > 1:
                    return jsonify({'error': 'Only one microphone source is allowed'}), 400

                # Validate next_source_id if provided
                next_id = incoming_audio.get('next_source_id')
                if next_id is not None and seen_ids:
                    max_suffix = max(
                        (int(sid.split('_', 1)[1]) for sid in seen_ids),
                        default=-1
                    )
                    if next_id <= max_suffix:
                        return jsonify({'error': f'next_source_id ({next_id}) must be greater than max existing id suffix ({max_suffix})'}), 400

            # Validate recording_length
            recording_length = incoming_audio.get('recording_length')
            if recording_length is not None and recording_length not in RECORDING_LENGTH_OPTIONS:
                return jsonify({'error': 'Invalid recording_length. Must be 9, 12, or 15 seconds'}), 400

            # Validate overlap
            overlap = incoming_audio.get('overlap')
            if overlap is not None and overlap not in OVERLAP_OPTIONS:
                return jsonify({'error': 'Invalid overlap. Must be 0.0, 0.5, 1.0, 1.5, 2.0, or 2.5 seconds'}), 400

        # Validate model type
        if 'model' in incoming_settings:
            model_type = new_settings['model'].get('type')
            if model_type and model_type not in VALID_MODEL_TYPES:
                return jsonify({'error': f'Invalid model type. Must be one of: {", ".join(VALID_MODEL_TYPES)}'}), 400

        # Validate display settings
        if 'display' in incoming_settings:
            bird_name_language = new_settings.get('display', {}).get('bird_name_language')
            if bird_name_language and bird_name_language not in SUPPORTED_BIRD_NAME_LANGUAGES:
                supported = ', '.join(sorted(SUPPORTED_BIRD_NAME_LANGUAGES))
                return jsonify({
                    'error': f'Invalid bird_name_language. Must be one of: {supported}'
                }), 400

        # Validate notification settings
        if 'notifications' in incoming_settings:
            error = _validate_notification_settings(incoming_settings['notifications'])
            if error:
                return jsonify({'error': error}), 400

        # Compute timezone when location is being saved and timezone is missing or location changed
        # This ensures all containers have correct timezone on next restart
        if 'location' in incoming_settings:
            location = new_settings.get('location', {})
            lat = location.get('latitude')
            lon = location.get('longitude')
            if lat is not None and lon is not None:
                # Load current settings to check for changes and preserve timezone
                current_loc = current_settings.get('location', {})
                location_changed = (
                    current_loc.get('latitude') != lat or
                    current_loc.get('longitude') != lon
                )
                timezone_missing = not location.get('timezone') and not current_loc.get('timezone')

                if timezone_missing or location_changed:
                    # Compute new timezone when location changed or never had one
                    timezone = get_timezone_for_location(lat, lon)
                    if timezone:
                        new_settings['location']['timezone'] = timezone
                    # If lookup fails, leave timezone unset - user can retry by saving again
                elif not location.get('timezone') and current_loc.get('timezone'):
                    # Preserve existing timezone if not in incoming payload
                    new_settings['location']['timezone'] = current_loc['timezone']

        changed_paths = get_setting_differences(current_settings, new_settings)
        change_plan = classify_setting_changes(changed_paths, current_settings, new_settings)

        # Save settings to JSON file and clear caches
        save_user_settings(new_settings)
        invalidate_runtime_settings_cache()
        # display.* preferences feed _localize_* in the cached payload;
        # location.* (lat/lon/timezone) feeds local_now() which sets the
        # today/week/month boundaries and the hourly-activity date. Any
        # other section (notifications, MQTT, audio sources, etc.) leaves
        # the rendered payload unchanged, so dropping the cache then would
        # force a needless 4.5s recompute.
        _DASHBOARD_INVALIDATING_PREFIXES = ('display.', 'location.')
        if any(path.startswith(_DASHBOARD_INVALIDATING_PREFIXES) for path in changed_paths):
            invalidate_dashboard_cache()
            invalidate_gallery_cache()
        clear_bird_name_caches()

        logger.info("Settings updated", extra={
            'changed_sections': list(incoming_settings.keys()),
            'changed_paths': changed_paths,
            'full_restart_required': change_plan['full_restart_required']
        })

        if not changed_paths:
            message = 'No changes detected.'
        elif change_plan['full_restart_required']:
            message = 'Settings applied. Restarting...'
        else:
            message = 'Settings applied.'

        return jsonify({
            'status': 'updated',
            'message': message,
            'settings': new_settings,
            'changes': {
                'changed_paths': changed_paths,
                'hot_applied': change_plan['hot_applied'],
                'component_restarts': change_plan['component_restarts'],
                'full_restart_required': change_plan['full_restart_required'],
                'full_restart_paths': change_plan['full_restart_paths'],
            }
        }), 200

    except Exception as e:
        logger.error("Failed to update settings", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500

@api.route('/api/notifications/test', methods=['POST'])
@log_api_request
@require_auth
def test_notification():
    """Send a test notification to verify Apprise URL configuration."""
    try:
        data = request.json or {}
        apprise_url = data.get('apprise_url')

        if not apprise_url:
            return jsonify({'error': 'No Apprise URL provided. Include {"apprise_url": "..."} in the request body.'}), 400

        from core.notification_service import send_test_notification
        success, message = send_test_notification(apprise_url)

        if success:
            return jsonify({'success': True, 'message': message}), 200
        else:
            return jsonify({'error': message}), 500

    except Exception as e:
        logger.error("Test notification error", extra={'error': str(e)})
        return jsonify({'error': str(e)}), 500


@api.route('/api/stream/test', methods=['POST'])
@log_api_request
@require_auth
def test_stream():
    """Test a stream URL to verify it's accessible."""
    try:
        data = request.json or {}
        url = data.get('url', '').strip()

        if not url:
            return jsonify({'error': 'No URL provided'}), 400

        from core.audio_manager import test_stream_url
        success, message = test_stream_url(url)

        return jsonify({'success': success, 'message': message}), 200

    except Exception as e:
        logger.error("Stream test error", extra={'error': str(e)})
        return jsonify({'error': str(e)}), 500


@api.route('/api/system/storage', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_system_storage():
    """Get disk storage information for the data directory (matches df output)"""
    data_path = os.path.join(BASE_DIR, 'data')

    try:
        # Use statvfs to match df's calculation (excludes reserved blocks)
        stat = os.statvfs(data_path)
        block_size = stat.f_frsize

        total_bytes = stat.f_blocks * block_size
        free_bytes = stat.f_bfree * block_size
        avail_bytes = stat.f_bavail * block_size  # Available to non-root (what df shows)
        used_bytes = total_bytes - free_bytes

        total_gb = total_bytes / (1024 ** 3)
        used_gb = used_bytes / (1024 ** 3)
        avail_gb = avail_bytes / (1024 ** 3)

        # Match df's percentage: used / (used + available)
        percent_used = (used_bytes / (used_bytes + avail_bytes)) * 100

        return jsonify({
            'total_gb': round(total_gb, 1),
            'used_gb': round(used_gb, 1),
            'free_gb': round(avail_gb, 1),
            'percent_used': round(percent_used, 0)
        }), 200
    except Exception as e:
        logger.error("Failed to get storage info", extra={'error': str(e)})
        return jsonify({'error': f'Failed to get storage info: {str(e)}'}), 500


def _public_version_view(response):
    """Drop the build fingerprint (exact commit + branch) for anonymous callers.

    The precise commit and branch let anyone match a pinned build to a known CVE.
    Only the owner needs them (Settings displays them); the public view keeps
    ``version`` + ``runtime_mode`` so the background update check still works
    without popping a login modal.
    """
    if get_request_tier() == 'public':
        for field in ('current_commit', 'current_commit_date', 'current_branch'):
            response.pop(field, None)
    return response


@api.route('/api/system/version', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_system_version():
    """Get current system version info for native or HA mode."""
    try:
        response = {}
        runtime_mode = get_runtime_mode()

        if runtime_mode == 'ha':
            app_source_commit = load_ha_source_commit()
            response = {
                'version': os.environ.get('BUILD_VERSION', 'unknown'),
                'current_commit': app_source_commit or 'unknown',
                'current_commit_date': 'unknown',
                'current_branch': 'home_assistant',
                'remote_url': f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}',
                'runtime_mode': runtime_mode,
            }
            return jsonify(_public_version_view(response)), 200

        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available. Run build.sh to generate version.json'
            }), 500

        return jsonify(_public_version_view({
            'version': version_info.get('version', 'unknown'),
            'current_commit': version_info.get('commit', 'unknown'),
            'current_commit_date': version_info.get('commit_date', 'unknown'),
            'current_branch': version_info.get('branch', 'unknown'),
            'remote_url': version_info.get('remote_url', f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}'),
            'runtime_mode': runtime_mode,
        })), 200
    except Exception as e:
        return jsonify({'error': f'Failed to get version info: {str(e)}'}), 500

def get_channel_branch():
    """Get the target branch based on update channel setting.

    Returns:
        tuple: (channel, branch) where channel is 'release' or 'latest'
               and branch is 'main' or 'staging'
    """
    settings = load_user_settings()
    channel = settings.get('updates', {}).get('channel', 'release')

    # Normalize old "stable" setting and unknown values to "release" (safe default)
    if channel not in ('release', 'latest'):
        channel = 'release'

    # Map channel to branch
    branch = 'main' if channel == 'release' else 'staging'
    return channel, branch


@api.route('/api/system/update-check', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def check_for_updates():
    """Check if updates are available using GitHub API.

    Compares current commit against the HEAD of the configured channel's branch:
    - release channel: compares against main branch
    - latest channel: compares against staging branch

    Query params:
    - force: Set to 'true' to bypass cache (used by manual "Check for Updates" button)
    """
    try:
        if is_home_assistant_mode():
            force = request.args.get('force', 'false').lower() == 'true'
            if force:
                _call_supervisor('POST', '/store/reload', timeout=30)

            info, error = _call_supervisor('GET', '/addons/self/info')
            if error:
                return jsonify({'error': f'Failed to check for updates: {error}'}), 502

            return jsonify({
                'update_available': bool(info.get('update_available')),
                'runtime_mode': 'ha',
                'current_version': info.get('version', 'unknown'),
                'latest_version': info.get('version_latest'),
                'update_note': None,
            }), 200

        force = request.args.get('force', 'false').lower() == 'true'

        # Load current version info
        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available. Run build.sh to generate version.json'
            }), 500

        current_commit = version_info.get('commit', '')
        current_branch = version_info.get('branch', 'main')

        # Get target branch based on channel setting
        channel, target_branch = get_channel_branch()

        # Build cache key and check cache (skip if force=true)
        cache_key = f"{channel}:{current_commit}"
        now = time.time()

        if not force and _update_check_cache['cache_key'] == cache_key:
            if now - _update_check_cache['timestamp'] < UPDATE_CHECK_CACHE_TTL:
                logger.debug("Returning cached update check result", extra={
                    'cache_key': cache_key,
                    'cache_age_seconds': int(now - _update_check_cache['timestamp'])
                })
                return jsonify(_update_check_cache['result']), 200

        logger.info("Update check initiated", extra={
            'current_commit': current_commit,
            'current_branch': current_branch,
            'channel': channel,
            'target_branch': target_branch,
            'force': force
        })

        if not current_commit or current_commit == 'unknown':
            return jsonify({
                'error': 'Current commit hash not available in version.json'
            }), 500

        # Get comparison from GitHub API
        comparison, error = get_commits_comparison(current_commit, target_branch)
        fresh_sync = False

        if error:
            # Check if error indicates commit not found (repo history changed)
            if 'No commit found' in error or '404' in error or '422' in error:
                logger.info("Commit not found in remote - repo history may have changed", extra={
                    'current_commit': current_commit,
                    'error': error
                })
                # Fall back to comparing with latest remote commit
                remote_info, remote_error = get_latest_remote_commit(target_branch)
                if remote_error:
                    logger.error("Failed to get remote commit", extra={'error': remote_error})
                    return jsonify({'error': f'Failed to check for updates: {remote_error}'}), 500

                remote_commit = remote_info['sha']
                # If commits differ, update is available (fresh sync required)
                update_available = current_commit[:7] != remote_commit[:7]
                fresh_sync = update_available

                logger.info("Fresh sync check result", extra={
                    'current_commit': current_commit,
                    'remote_commit': remote_commit,
                    'update_available': update_available,
                    'fresh_sync': fresh_sync
                })

                # Fetch update notes if update is available
                update_note = None
                if update_available:
                    note_data = fetch_update_notes(target_branch)
                    if should_show_update_note(current_commit, note_data):
                        update_note = note_data.get('message')

                result = _build_update_check_result(
                    update_available, current_commit, remote_commit,
                    commits_behind=None,  # Unknown for fresh sync
                    current_branch=current_branch, target_branch=target_branch,
                    channel=channel, preview_commits=[],  # No history available
                    fresh_sync=fresh_sync, update_note=update_note
                )
                return _cache_and_return_update_result(result, cache_key, now)
            else:
                # Do NOT cache error responses - let them retry
                logger.error("GitHub API comparison failed", extra={'error': error})
                return jsonify({'error': f'Failed to check for updates: {error}'}), 500

        # Determine if update is available
        # ahead_by: how many commits the target branch is ahead of current
        # behind_by: how many commits the target branch is behind current (channel switch case)
        commits_behind = comparison.get('ahead_by', 0)
        status = comparison.get('status', 'unknown')

        # Update is available if:
        # 1. Target is ahead of us (normal update), OR
        # 2. Commits are different (channel switch - target may be behind but we want to switch)
        # Only 'identical' status means no update needed
        update_available = status != 'identical'

        logger.info("GitHub API comparison result", extra={
            'comparison_status': status,
            'ahead_by': comparison.get('ahead_by'),
            'behind_by': comparison.get('behind_by'),
            'commits_behind': commits_behind,
            'update_available': update_available
        })

        # Get latest remote commit info
        remote_info, _ = get_latest_remote_commit(target_branch)
        remote_commit = remote_info['sha'] if remote_info else comparison.get('target_commit', 'unknown')

        if remote_info:
            logger.info("Latest remote commit", extra={
                'remote_commit': remote_commit,
                'remote_message': remote_info.get('message', 'N/A')
            })

        # Fetch update notes if update is available
        update_note = None
        if update_available:
            note_data = fetch_update_notes(target_branch)
            if should_show_update_note(current_commit, note_data):
                update_note = note_data.get('message')

        result = _build_update_check_result(
            update_available, current_commit, remote_commit,
            commits_behind, current_branch, target_branch,
            channel, comparison['commits'], fresh_sync, update_note
        )
        return _cache_and_return_update_result(result, cache_key, now)

    except Exception as e:
        # Do NOT cache error responses - let them retry
        return jsonify({'error': f'Failed to check for updates: {str(e)}'}), 500

@api.route('/api/system/update', methods=['POST'])
@require_auth
@log_api_request
@handle_api_errors
def trigger_system_update():
    """Trigger system update by writing flag file.

    Writes the target branch name to the flag file so the service script
    knows which branch to update to:
    - release channel: writes 'main'
    - latest channel: writes 'staging'

    Note: Update availability is already verified by frontend via /api/system/update-check
    before this endpoint is called. No need to re-check here.
    """
    try:
        if is_home_assistant_mode():
            # Supervisor forbids an addon from updating itself directly
            # (supervisor/api/store.py: "App {slug} can't update itself!").
            # Workaround: call HA Core's update.install service, which routes
            # the request through Core so Supervisor sees Core as the caller.
            addon_info, info_error = _call_supervisor('GET', '/addons/self/info')
            if info_error:
                return jsonify({
                    'error': f'Failed to determine Home Assistant addon slug: {info_error}'
                }), 502

            addon_slug = addon_info.get('slug')
            if not addon_slug:
                return jsonify({'error': 'Failed to determine Home Assistant addon slug'}), 502

            token = os.environ.get('SUPERVISOR_TOKEN', '')
            entity_id, lookup_error = _find_addon_update_entity(addon_slug, token)
            if lookup_error:
                return jsonify({'error': lookup_error}), 502

            # Refresh HA Core's update entity so its latest_version is current.
            # Without this, update.install fails with "No update available" when
            # installed_version == latest_version (cached state right after a
            # version bump). The update_entity service is fire-and-forget — it
            # triggers a debounced coordinator refresh and returns immediately,
            # so we then poll the entity state until the new latest_version
            # propagates. (We avoid /store/reload because it kicks off
            # addon-group jobs that race with update.install.)
            try:
                requests.post(
                    f"{_HA_CORE_API_BASE}/services/homeassistant/update_entity",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"entity_id": entity_id},
                    timeout=15,
                )
            except requests.RequestException as e:
                logger.warning("Failed to refresh HA update entity (continuing)", extra={
                    'entity_id': entity_id,
                    'error': str(e),
                })

            deadline = time.monotonic() + _HA_ENTITY_POLL_TIMEOUT_SECONDS
            entity_ready = False
            while True:
                try:
                    state_resp = requests.get(
                        f"{_HA_CORE_API_BASE}/states/{entity_id}",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=5,
                    )
                    if state_resp.ok:
                        attrs = state_resp.json().get('attributes', {})
                        installed = attrs.get('installed_version')
                        latest = attrs.get('latest_version')
                        if installed and latest and installed != latest:
                            entity_ready = True
                            break
                except requests.RequestException:
                    pass
                if time.monotonic() >= deadline:
                    break
                time.sleep(_HA_ENTITY_POLL_INTERVAL_SECONDS)

            if not entity_ready:
                return jsonify({
                    'error': 'Home Assistant has not yet refreshed the addon update state. Try again in a moment.'
                }), 502

            # HA Core's REST service call blocks until update.install
            # finishes, but installing OUR addon kills this process mid-flight
            # — so a ReadTimeout or ConnectionError after dispatch is the
            # expected outcome, not a failure. Only treat HTTP error responses
            # (which arrive before Supervisor swaps us out) as real failures.
            try:
                resp = requests.post(
                    f"{_HA_CORE_API_BASE}/services/update/install",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"entity_id": entity_id},
                    timeout=10,
                )
                resp.raise_for_status()
            except (requests.ConnectionError, requests.Timeout) as e:
                logger.info(
                    "HA addon update dispatched; connection closed as expected during self-update",
                    extra={'entity_id': entity_id, 'error': str(e)},
                )
            except requests.RequestException as e:
                response = getattr(e, 'response', None)
                core_message = None
                if response is not None:
                    try:
                        core_message = response.json().get('message')
                    except (ValueError, AttributeError):
                        core_message = None
                logger.error("Failed to trigger HA addon update", extra={
                    'error': str(e),
                    'status_code': getattr(response, 'status_code', None),
                    'response_text': (getattr(response, 'text', None) or '')[:500],
                })
                error_message = 'Failed to trigger Home Assistant addon update'
                if core_message:
                    error_message = f'{error_message}: {core_message}'
                return jsonify({'error': error_message}), 502

            logger.info("HA addon update triggered via Core service", extra={
                'entity_id': entity_id,
            })
            return jsonify({
                'status': 'update_triggered',
                'message': 'Home Assistant addon update initiated.',
                'estimated_downtime': '2-5 minutes',
            }), 200

        # Load current version info for logging
        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available'
            }), 500

        # Get target branch based on channel setting
        channel, target_branch = get_channel_branch()

        # Write update flag with target branch as content
        write_flag('update-requested', target_branch)

        logger.info("System update triggered", extra={
            'current_commit': version_info.get('commit', 'unknown'),
            'channel': channel,
            'target_branch': target_branch
        })

        return jsonify({
            'status': 'update_triggered',
            'message': 'System update initiated. Services will restart shortly.',
            'estimated_downtime': '2-5 minutes',
            'channel': channel,
            'target_branch': target_branch
        }), 200

    except Exception as e:
        return jsonify({'error': f'Failed to trigger update: {str(e)}'}), 500


@api.route('/api/system/restart', methods=['POST'])
@require_auth
@log_api_request
@handle_api_errors
def trigger_service_restart():
    """Trigger service restart for native mode or HA add-on mode."""
    if is_home_assistant_mode():
        _data, error = _call_supervisor('POST', '/addons/self/restart')
        if error:
            logger.error("Failed to restart HA add-on", extra={'error': error})
            return jsonify({'error': 'Failed to restart Home Assistant add-on'}), 502
        logger.info("Home Assistant add-on restart triggered via API")
        return jsonify({
            'status': 'restart_requested',
            'message': 'Home Assistant add-on restart initiated. Services will restart shortly.',
            'estimated_downtime': '10-30 seconds',
        }), 200

    write_flag('restart-backend')
    logger.info("Service restart triggered via API")
    return jsonify({
        'status': 'restart_requested',
        'message': 'Service restart initiated. Services will restart shortly.',
        'estimated_downtime': '10-30 seconds'
    }), 200


# =============================================================================
# Log Viewer Endpoint
# =============================================================================

@api.route('/api/system/logs', methods=['GET'])
@require_auth
@handle_api_errors
def get_system_logs():
    """Return merged, filtered log entries from all services."""
    from core.log_reader import get_logs

    service = request.args.get('service')
    search = request.args.get('search')
    limit = request.args.get('limit', type=int)

    result = get_logs(service=service, search=search, limit=limit)
    return jsonify(result)


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


# =============================================================================
# Migration Endpoints (BirdNET-Pi import)
# =============================================================================

# Directory for storing temporary migration files
MIGRATION_TEMP_DIR = os.path.join(BASE_DIR, 'data', 'temp', 'migration')

def cleanup_migration_temp_dir():
    """Remove orphaned migration temp files from previous sessions."""
    if not os.path.isdir(MIGRATION_TEMP_DIR):
        return 0

    removed = 0
    for filename in os.listdir(MIGRATION_TEMP_DIR):
        if not (filename.startswith('migration_') and filename.endswith('.db')):
            continue
        file_path = os.path.join(MIGRATION_TEMP_DIR, filename)
        if not os.path.isfile(file_path):
            continue
        try:
            os.remove(file_path)
            removed += 1
        except Exception as e:
            logger.warning("Failed to remove migration temp file", extra={
                'path': file_path,
                'error': str(e)
            })

    if removed:
        logger.info("Cleaned orphaned migration temp files", extra={
            'removed': removed
        })
    return removed


def get_migration_temp_path():
    """Get temp file path from session, if it exists and is valid."""
    temp_path = session.get('migration_temp_path')
    if temp_path and os.path.exists(temp_path):
        return temp_path
    return None


def cleanup_migration_temp():
    """Remove temp file and clear session."""
    temp_path = session.pop('migration_temp_path', None)
    if temp_path and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
            logger.debug("Migration temp file cleaned up", extra={'path': temp_path})
        except Exception as e:
            logger.warning("Failed to cleanup migration temp file", extra={
                'path': temp_path,
                'error': str(e)
            })


@api.route('/api/migration/validate', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_validate():
    """Upload and validate a BirdNET-Pi database file.

    Accepts multipart/form-data with a 'file' field containing the birds.db file.

    Returns:
        JSON with validation result, record count, duplicate count, and preview records
    """
    # Check if file was uploaded
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Validate file extension
    if not file.filename.endswith('.db'):
        return jsonify({'error': 'File must be a .db SQLite database file'}), 400

    # Clean up any previous temp file
    cleanup_migration_temp()

    # Create temp directory if needed
    os.makedirs(MIGRATION_TEMP_DIR, exist_ok=True)

    # Save to temp file with unique name
    temp_filename = f"migration_{uuid.uuid4().hex}.db"
    temp_path = os.path.join(MIGRATION_TEMP_DIR, temp_filename)

    try:
        # Chunked copy instead of file.save(): save() is a disk->disk copy of
        # the whole DB (hundreds of MB on a Pi SD card) and disk I/O is not
        # gevent-patched, so yield between chunks to keep the single gevent
        # worker responsive.
        chunk_size = 1024 * 1024
        with open(temp_path, 'wb') as dst:
            while True:
                chunk = file.stream.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk)
                _cooperative_yield()
        logger.info("Migration file uploaded", extra={
            'original_filename': file.filename,
            'temp_path': temp_path
        })

        # Validate the database
        migrator = BirdNETPiMigrator(db_manager)
        validation = migrator.validate_source_database(temp_path)

        if not validation['valid']:
            # Clean up invalid file
            os.remove(temp_path)
            return jsonify({
                'valid': False,
                'error': validation['error']
            }), 400

        # Get preview (skip duplicate counting - too slow for large databases)
        preview = migrator.get_preview(temp_path, limit=10)

        # Store temp path and record count in session for import step
        session['migration_temp_path'] = temp_path
        session['migration_total_records'] = validation['record_count']

        return jsonify({
            'valid': True,
            'record_count': validation['record_count'],
            'preview': preview
        }), 200

    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        logger.error("Migration validation error", extra={'error': str(e)}, exc_info=True)
        return jsonify({'error': f'Failed to validate database: {str(e)}'}), 500


def _run_migration_background(temp_path, total_records, skip_duplicates):
    """Run migration in background thread.

    Args:
        temp_path: Path to the validated source database (used as migration ID)
        total_records: Total number of records to import
        skip_duplicates: Whether to skip duplicate records
    """
    try:
        migrator = BirdNETPiMigrator(db_manager)
        result = migrator.migrate(
            temp_path,
            skip_duplicates=skip_duplicates,
            temp_path=temp_path,
            total_records=total_records,
            yield_control=_cooperative_yield
        )

        logger.info("Migration import completed", extra={
            'migration_id': temp_path,
            'imported': result['imported'],
            'skipped': result['skipped'],
            'errors': result['errors']
        })

        if result.get('imported', 0) > 0:
            invalidate_dashboard_cache()
            invalidate_gallery_cache()

    except Exception as e:
        logger.error("Migration import error", extra={
            'migration_id': temp_path,
            'error': str(e)
        }, exc_info=True)
        set_migration_progress(temp_path, {
            'status': 'failed',
            'error': str(e)
        })

    finally:
        # Clean up temp file after migration completes
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug("Migration temp file cleaned up", extra={'path': temp_path})
            except Exception as e:
                logger.warning("Failed to cleanup migration temp file", extra={
                    'path': temp_path,
                    'error': str(e)
                })

        # Clear progress tracking after a delay to allow final status poll
        def cleanup_progress():
            import time
            time.sleep(300)  # Keep progress available for 5 minutes
            clear_migration_progress(temp_path)
            logger.debug("Migration progress cleared", extra={'migration_id': temp_path})

        cleanup_thread = threading.Thread(target=cleanup_progress, daemon=True)
        cleanup_thread.start()


@api.route('/api/migration/import', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_import():
    """Start importing records from a previously validated BirdNET-Pi database.

    The import runs in the background. Use /api/migration/status to check progress.

    Request body (optional):
        {
            "skip_duplicates": true  // default: true
        }

    Returns:
        JSON with status: started and migration_id for tracking
    """
    # Get temp file from session
    temp_path = get_migration_temp_path()
    if not temp_path:
        return jsonify({'error': 'No validated file found. Please upload and validate first.'}), 400

    total_records = session.get('migration_total_records', 0)

    # Get options from request (handle missing or non-JSON body)
    data = {}
    if request.is_json:
        data = request.json or {}
    skip_duplicates = data.get('skip_duplicates', True)

    # Clear session early - we either start the migration or it's already running
    # This prevents cancel from interfering with a running migration
    session.pop('migration_temp_path', None)
    session.pop('migration_total_records', None)

    # Atomically check if we can start and initialize progress
    # This prevents race conditions with duplicate requests
    # temp_path is used as the migration_id (unique per upload via uuid)
    can_start, running_id = start_migration_if_not_running(temp_path, total_records)

    if not can_start:
        # Already running - return the ID of the running job so client can poll
        return jsonify({
            'status': 'already_running',
            'migration_id': running_id,
            'message': 'Database migration is already in progress'
        }), 200

    # Start background thread
    thread = threading.Thread(
        target=_run_migration_background,
        args=(temp_path, total_records, skip_duplicates),
        daemon=True
    )
    thread.start()

    logger.info("Migration import started in background", extra={
        'migration_id': temp_path,
        'total_records': total_records
    })

    return jsonify({
        'status': 'started',
        'migration_id': temp_path,
        'total_records': total_records
    }), 200


@api.route('/api/migration/status', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def migration_status():
    """Get the current status of a running migration.

    Query params:
        migration_id: The migration ID returned from /api/migration/import

    Returns:
        JSON with current progress (status, processed, total, imported, skipped, errors)
    """
    migration_id = request.args.get('migration_id')
    if not migration_id:
        return jsonify({'error': 'migration_id parameter required'}), 400

    progress = get_migration_progress(migration_id)
    if not progress:
        return jsonify({
            'status': 'not_found',
            'message': 'No migration found with this ID'
        }), 404

    return jsonify(progress), 200


@api.route('/api/migration/cancel', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_cancel():
    """Cancel migration and clean up.

    Call this if user cancels after validation but before import.
    Note: Cannot stop a running import (it will complete in background),
    but this will clean up the temp file if called.
    """
    temp_path = get_migration_temp_path()

    if temp_path:
        # Clear any progress tracking (keyed by temp_path)
        clear_migration_progress(temp_path)
        cleanup_migration_temp()
        logger.info("Migration cancelled and temp file cleaned up")
        return jsonify({'status': 'cancelled', 'message': 'Migration cancelled'}), 200
    else:
        return jsonify({'status': 'ok', 'message': 'No migration in progress'}), 200


# =============================================================================
# Migration Stage 2: Audio Import Endpoints
# =============================================================================

@api.route('/api/migration/audio/folders', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_folders():
    """List available folders that contain audio files.

    Returns folders in the data directory that contain audio files
    and are not system folders.

    Returns:
        JSON with list of available folders
    """
    folders = list_available_folders()
    return jsonify({'folders': folders}), 200


@api.route('/api/migration/audio/scan', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_scan():
    """Scan source folder for matching audio files.

    Request body:
        source_folder: Relative path to folder within data directory (required)

    Returns:
        JSON with matched files count, unmatched count, total size, and disk space info
    """
    data = request.get_json() or {}
    source_folder = data.get('source_folder')

    if not source_folder:
        return jsonify({
            'error': 'Missing source_folder parameter',
            'hint': 'Please select a folder containing your BirdNET-Pi audio files.'
        }), 400

    scan_result = scan_audio_files(db_manager, source_folder)

    # Check disk space if we have matched files
    disk_check = check_disk_space(scan_result['total_size_bytes'])

    return jsonify({
        'source_folder': scan_result.get('source_folder', ''),
        'source_exists': scan_result['source_exists'],
        'total_records': scan_result['total_records'],
        'matched_count': scan_result['matched_count'],
        'unmatched_count': scan_result['unmatched_count'],
        'total_size_bytes': scan_result['total_size_bytes'],
        'disk_usage': disk_check
    }), 200


@api.route('/api/migration/audio/import', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_import():
    """Start importing matched audio files.

    Request body:
        source_folder: Relative path to folder within data directory (required)

    The import runs in the background. Use /api/migration/audio/status to check progress.

    Returns:
        JSON with status: started and import_id for tracking
    """
    data = request.get_json() or {}
    source_folder = data.get('source_folder')

    if not source_folder:
        return jsonify({
            'error': 'Missing source_folder parameter',
            'hint': 'Please select a folder containing your BirdNET-Pi audio files.'
        }), 400

    # Re-scan to get matched files (ensures fresh data)
    scan_result = scan_audio_files(db_manager, source_folder)

    if not scan_result['matched_files']:
        return jsonify({
            'error': 'No matching audio files found in the selected folder.',
            'hint': 'Make sure the folder contains audio files that match your imported database records.'
        }), 400

    # Check disk space
    disk_check = check_disk_space(scan_result['total_size_bytes'])
    if not disk_check['has_enough_space']:
        return jsonify({
            'error': 'Not enough disk space to import these files.',
            'hint': 'Free up some space or import fewer files.',
            'required_bytes': scan_result['total_size_bytes'],
            'available_bytes': disk_check['available_bytes']
        }), 400

    # Generate unique import ID
    import_id = f"audio_import_{uuid.uuid4().hex}"
    total_files = len(scan_result['matched_files'])

    # Atomically check if we can start
    can_start, running_id = start_audio_import_if_not_running(import_id, total_files)
    if not can_start:
        return jsonify({
            'status': 'already_running',
            'import_id': running_id,  # Return the ID of the running job
            'message': 'Audio import is already in progress'
        }), 200

    # Start background thread
    def run_import():
        try:
            import_audio_files(db_manager, scan_result['matched_files'], import_id,
                                yield_control=_cooperative_yield)
        finally:
            # Clear progress tracking after a delay
            def cleanup_progress():
                import time
                time.sleep(300)  # Keep progress available for 5 minutes
                clear_audio_import_progress(import_id)
                logger.debug("Audio import progress cleared", extra={'import_id': import_id})

            cleanup_thread = threading.Thread(target=cleanup_progress, daemon=True)
            cleanup_thread.start()

    thread = threading.Thread(target=run_import, daemon=True)
    thread.start()

    logger.info("Audio import started in background", extra={
        'import_id': import_id,
        'total_files': total_files
    })

    return jsonify({
        'status': 'started',
        'import_id': import_id,
        'total_files': total_files
    }), 200


@api.route('/api/migration/audio/status', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_status():
    """Get the current status of an audio import.

    Query params:
        import_id: The import ID returned from /api/migration/audio/import

    Returns:
        JSON with current progress (status, processed, total, imported, skipped, errors)
    """
    import_id = request.args.get('import_id')
    if not import_id:
        return jsonify({'error': 'import_id parameter required'}), 400

    progress = get_audio_import_progress(import_id)
    if not progress:
        return jsonify({
            'status': 'not_found',
            'message': 'No audio import found with this ID'
        }), 404

    return jsonify(progress), 200


@api.route('/api/migration/audio/skip', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_skip():
    """Skip the audio import stage.

    Returns:
        JSON with status: skipped
    """
    logger.info("Audio import stage skipped")
    return jsonify({'status': 'skipped', 'message': 'Audio import skipped'}), 200


# =============================================================================
# Migration Stage 3: Spectrogram Generation Endpoints
# =============================================================================

@api.route('/api/migration/spectrogram/scan', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_spectrogram_scan():
    """Scan for audio files needing spectrograms.

    Checks EXTRACTED_AUDIO_DIR for audio files without matching spectrograms.

    Returns:
        JSON with count of files needing spectrograms and estimated size
    """
    scan_result = scan_files_needing_spectrograms()

    return jsonify({
        'count': scan_result['count'],
        'estimated_size_bytes': scan_result['estimated_size_bytes'],
        'disk_usage': scan_result['disk_usage']
    }), 200


@api.route('/api/migration/spectrogram/generate', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_spectrogram_generate():
    """Start generating spectrograms for audio files.

    Must call /api/migration/spectrogram/scan first.
    The generation runs in the background. Use /api/migration/spectrogram/status to check progress.

    Returns:
        JSON with status: started and generation_id for tracking
    """
    # Scan for files needing spectrograms
    scan_result = scan_files_needing_spectrograms()

    if not scan_result['files_needing']:
        return jsonify({
            'status': 'no_files',
            'message': 'No files need spectrograms'
        }), 200

    # Check disk space
    if not scan_result['disk_usage']['has_enough_space']:
        return jsonify({
            'error': 'Insufficient disk space',
            'required_bytes': scan_result['estimated_size_bytes'],
            'available_bytes': scan_result['disk_usage']['available_bytes']
        }), 400

    # Generate unique generation ID
    generation_id = f"spectrogram_gen_{uuid.uuid4().hex}"
    total_files = scan_result['count']

    # Atomically check if we can start
    can_start, running_id = start_spectrogram_generation_if_not_running(generation_id, total_files)
    if not can_start:
        return jsonify({
            'status': 'already_running',
            'generation_id': running_id,  # Return the ID of the running job
            'message': 'Spectrogram generation is already in progress'
        }), 200

    # Start background thread
    def run_generation():
        try:
            generate_spectrograms_batch(scan_result['files_needing'], generation_id,
                                        yield_control=_cooperative_yield)
        finally:
            # Clear progress tracking after a delay
            def cleanup_progress():
                import time
                time.sleep(300)  # Keep progress available for 5 minutes
                clear_spectrogram_progress(generation_id)
                logger.debug("Spectrogram progress cleared", extra={'generation_id': generation_id})

            cleanup_thread = threading.Thread(target=cleanup_progress, daemon=True)
            cleanup_thread.start()

    thread = threading.Thread(target=run_generation, daemon=True)
    thread.start()

    logger.info("Spectrogram generation started in background", extra={
        'generation_id': generation_id,
        'total_files': total_files
    })

    return jsonify({
        'status': 'started',
        'generation_id': generation_id,
        'total_files': total_files
    }), 200


@api.route('/api/migration/spectrogram/status', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def migration_spectrogram_status():
    """Get the current status of spectrogram generation.

    Query params:
        generation_id: The generation ID returned from /api/migration/spectrogram/generate

    Returns:
        JSON with current progress (status, processed, total, generated, errors)
    """
    generation_id = request.args.get('generation_id')
    if not generation_id:
        return jsonify({'error': 'generation_id parameter required'}), 400

    progress = get_spectrogram_progress(generation_id)
    if not progress:
        return jsonify({
            'status': 'not_found',
            'message': 'No spectrogram generation found with this ID'
        }), 404

    return jsonify(progress), 200


@api.route('/api/migration/spectrogram/skip', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_spectrogram_skip():
    """Skip the spectrogram generation stage.

    Returns:
        JSON with status: skipped
    """
    logger.info("Spectrogram generation stage skipped")
    return jsonify({'status': 'skipped', 'message': 'Spectrogram generation skipped'}), 200


@api.route('/api/health', methods=['GET'])
def health_check():
    """Unauthenticated liveness probe. Deliberately DB-free: a DB touch would
    couple liveness to transient SQLite locks. Must stay unauthenticated.
    """
    return jsonify({'status': 'ok'}), 200


# Global SocketIO instance to be used by other modules
socketio = None


def _cooperative_yield():
    """Yield the single gevent worker from long loops; no-op until create_app() sets `socketio`."""
    if socketio is not None:
        socketio.sleep(0)

# Latest recorder health status (populated by main container broadcasts)
_recorder_status = {}

# SocketIO room that only authenticated (owner) sockets join, so recorder health
# — which carries source labels/types and ffmpeg error text that can echo RTSP
# credentials — is broadcast to owners only, matching the @require_auth REST route.
_OWNER_ROOM = 'owners'

def create_app(async_mode='threading'):
    # The 'threading' default is load-bearing, not cosmetic. requirements.txt
    # ships gevent (for the gunicorn wsgi.py path), and Flask-SocketIO's
    # auto-selection prefers gevent over threading. Any caller that omits
    # async_mode — `python -m core.api` (local dev, tests, and the HA add-on's
    # legacy entrypoint) — must stay on threading: that path does NOT run
    # gevent's monkey.patch_all(), so an auto-selected gevent backend would
    # block on unpatched socket/sleep calls. wsgi.py passes async_mode='gevent'
    # explicitly (and patches first). Do not drop this default.
    global socketio, db_executor
    db_executor.shutdown(wait=False)
    db_executor = create_db_executor(async_mode)
    invalidate_dashboard_cache()
    invalidate_gallery_cache()

    app = Flask(__name__)

    # CORS is intentionally NOT enabled - all requests go through nginx proxy
    # which makes them same-origin. This prevents cross-origin attacks while
    # cookies and sessions work normally for same-origin requests.

    # Configure session for authentication
    configure_session(app)

    try:
        cleanup_migration_temp_dir()
    except Exception as e:
        logger.warning("Startup migration temp cleanup failed", extra={'error': str(e)})

    app.register_blueprint(api)
    _assert_route_access_declared(app)

    # Initialize SocketIO.
    # `cors_allowed_origins=None` lets Engine.IO compute allowed origins from the
    # request host headers (same-origin only). Do not set this to [] (blocks all origins).
    socketio = SocketIO(app, async_mode=async_mode, cors_allowed_origins=None,
                         logger=False, engineio_logger=False)

    # WebSocket event handlers
    @socketio.on('connect')
    def handle_connect():
        is_owner = is_authenticated()
        if not is_feature_public('live_feed') and not is_owner:
            return False  # Reject connection
        logger.info('WebSocket client connected')
        emit('status', {'message': 'Connected to live detection feed'})
        # recorder_status is owner-only (source labels/types + ffmpeg error text
        # that can contain RTSP credentials), matching the @require_auth
        # /api/recorder/status route. Anonymous live_feed listeners must not get
        # it. Owners join a room so the main container's status broadcasts reach
        # only them (see broadcast_recorder_status_endpoint).
        if is_owner:
            join_room(_OWNER_ROOM)
            if _recorder_status:
                emit('recorder_status', _recorder_status)

    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info('WebSocket client disconnected')

    return app, socketio

def broadcast_detection(detection_data):
    """Function to broadcast detection to all connected clients"""
    global socketio
    # Freshness, not correctness: expire only what the new detection changes
    # (see expire_dashboard_cache); week/month/allTime stay warm.
    expire_dashboard_cache()
    if socketio:
        detection_payload = _localize_detection(detection_data)
        socketio.emit('bird_detected', detection_payload)
        logger.debug("Detection broadcasted to WebSocket clients", extra={
            'species': detection_payload.get('common_name', 'Unknown'),
            'confidence': detection_payload.get('confidence')
        })

if __name__ == '__main__':
    logger.info("🌐 API server starting", extra={
        'port': API_PORT,
        'websocket': 'enabled',
        'timezone': get_timezone_str()
    })
    app, socketio = create_app()
    socketio.run(app, host='0.0.0.0', port=API_PORT, debug=False, allow_unsafe_werkzeug=True)
