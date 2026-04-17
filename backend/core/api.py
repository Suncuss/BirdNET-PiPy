import csv
import io
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta

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
from flask_socketio import SocketIO, emit
from timezonefinder import TimezoneFinder

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
    get_default_settings,
)
from core.api_utils import (
    handle_api_errors,
    log_data_metrics,
    serve_file_with_fallback,
    validate_date_param,
    validate_limit_param,
)
from core.auth import (
    authenticate,
    change_password,
    configure_session,
    get_public_features,
    is_auth_enabled,
    is_authenticated,
    is_feature_public,
    is_setup_complete,
    logout,
    require_auth,
    require_feature,
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
    get_localized_common_name_from_english,
)
from core.db import DatabaseManager
from core.ha_mode import get_runtime_mode, is_home_assistant_mode
from core.logging_config import get_logger, log_api_request, setup_logging
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
from core.runtime_config import (
    classify_setting_changes,
    deep_merge_settings,
    get_runtime_settings,
    get_setting_differences,
    invalidate_runtime_settings_cache,
)
from core.storage_manager import delete_detection_files
from core.timezone_service import get_timezone_str, local_now
from model_service.label_utils import get_species_list
from version import DISPLAY_NAME, __version__

# Setup logging
setup_logging('api')
logger = get_logger(__name__)

api = Blueprint('api', __name__)
db_manager = DatabaseManager()

# Singleton TimezoneFinder (loads ~40MB shape data on first use)
_timezone_finder: TimezoneFinder | None = None
_tz_finder_lock = threading.Lock()


def load_user_settings():
    """Compatibility wrapper around runtime settings loader."""
    return get_runtime_settings(force_reload=True)


def _get_timezone_finder() -> TimezoneFinder:
    """Lazy-load TimezoneFinder (loads ~40MB shape data)."""
    global _timezone_finder
    with _tz_finder_lock:
        if _timezone_finder is None:
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
    """Decorator to restrict endpoint to internal requests only."""
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_internal_request():
            logger.warning("Rejected external request to internal endpoint", extra={
                'remote_addr': request.remote_addr,
                'endpoint': request.endpoint
            })
            return jsonify({'error': 'Internal endpoint only'}), 403
        return f(*args, **kwargs)
    return decorated_function


# Simple in-memory cache
image_cache = {}
_image_cache_lock = threading.Lock()
CACHE_EXPIRATION = 172800  # Cache expiration time in seconds (48 hours)
MAX_CACHE_SIZE = 1000  # Maximum number of cached entries

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


def get_cached_image(species_name):
    with _image_cache_lock:
        if species_name in image_cache:
            cached_data = image_cache[species_name]
            if time.time() - cached_data['timestamp'] < CACHE_EXPIRATION:
                logger.debug("Image cache hit", extra={
                    'species': species_name,
                    'age_seconds': int(time.time() - cached_data['timestamp'])
                })
                return cached_data['data']
    return None


def set_cached_image(species_name, data):
    with _image_cache_lock:
        # Periodically clean up expired entries when adding new ones
        if len(image_cache) >= MAX_CACHE_SIZE:
            _cleanup_expired_cache()
            # If still at max after cleanup, remove oldest entry
            if len(image_cache) >= MAX_CACHE_SIZE:
                oldest_key = min(image_cache, key=lambda k: image_cache[k]['timestamp'])
                del image_cache[oldest_key]

        image_cache[species_name] = {
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


def _validate_image_magic_bytes(file_stream):
    """Validate that the file starts with known image magic bytes."""
    header = file_stream.read(4)
    file_stream.seek(0)
    return any(header[:len(m)] == m for m in IMAGE_MAGIC_PREFIXES)


def fetch_wikimedia_image(species_name):
    cached_data = get_cached_image(species_name)
    if cached_data:
        return cached_data, None

    try:
        # User-Agent header required by Wikimedia API (enforced since 2024)
        # Per Wikimedia policy: https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
        # TODO: Update with your actual contact info if you deploy this publicly
        headers = {
            'User-Agent': f'{DISPLAY_NAME}/{__version__} (Bird detection system; educational/personal use)'
        }

        # Search for images on Wikimedia Commons
        search_url = "https://commons.wikimedia.org/w/api.php"
        search_params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": f"{species_name} filetype:bitmap -egg -skeleton",
            "srnamespace": "6",  # File namespace
            "srlimit": "1"  # Limit to one result
        }

        search_response = requests.get(search_url, params=search_params, headers=headers, timeout=10)
        search_response.raise_for_status()
        search_data = search_response.json()

        if not search_data['query']['search']:
            return None, 'No results found'

        file_title = search_data['query']['search'][0]['title']

        # Fetch the image details
        image_url = "https://commons.wikimedia.org/w/api.php"
        image_params = {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "titles": file_title
        }

        image_response = requests.get(image_url, params=image_params, headers=headers, timeout=10)
        image_response.raise_for_status()
        image_data = image_response.json()

        pages = image_data['query']['pages']
        page = next(iter(pages.values()))

        if 'imageinfo' in page:
            image_info = page['imageinfo'][0]
            extmetadata = image_info['extmetadata']

            # Create a data structure with all the required information
            image_data = {
                'imageUrl': image_info['url'],
                'pageUrl': f"https://commons.wikimedia.org/wiki/{file_title.replace(' ', '_')}",
                'licenseType': extmetadata.get('LicenseShortName', {}).get('value', 'Unknown License'),
                'authorName': 'Unknown Author',
                'authorUrl': None
            }

            author_html = extmetadata.get('Artist', {}).get('value', 'Unknown Author')
            author_match = re.search(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', author_html)

            if author_match:
                image_data['authorUrl'] = author_match.group(1)
                if image_data['authorUrl'].startswith('//'):
                    image_data['authorUrl'] = 'https:' + image_data['authorUrl']
                image_data['authorName'] = author_match.group(2)
            else:
                image_data['authorName'] = re.sub('<[^<]+?>', '', author_html)  # Remove any HTML tags

            # Cache the result
            set_cached_image(species_name, image_data)
            return image_data, None
        else:
            return None, 'No image info found'

    except requests.RequestException as e:
        return None, f'Error fetching Wikimedia image: {str(e)}'

@api.route('/api/wikimedia_image', methods=['GET'])
def get_wikimedia_image():
    species_name = request.args.get('species', '')
    if not species_name:
        return jsonify({'error': 'Species name is required'}), 400

    custom_path, _ = _get_custom_image_path(species_name)
    has_custom = custom_path is not None

    image_data, error = fetch_wikimedia_image(species_name)

    if error:
        if has_custom:
            return jsonify({'hasCustomImage': True}), 200
        return jsonify({'error': error}), 404 if 'No results found' in error else 500

    image_data['hasCustomImage'] = has_custom

    logger.debug("Wikimedia image fetched", extra={
        'species': species_name,
        'has_image': bool(image_data),
        'has_custom_image': has_custom
    })
    return jsonify(image_data)

@api.route('/api/observations/latest', methods=['GET'])
@log_api_request
@handle_api_errors
def get_latest_observation():
    observation = db_manager.get_latest_detections(1)
    if observation:
        log_data_metrics('get_latest_observation', observation[0], {
            'species': observation[0].get('common_name'),
            'timestamp': observation[0].get('timestamp')
        })
        return jsonify(observation[0])
    # Return 200 with null for empty database - frontend shows "No observations available yet."
    return jsonify(None)

@api.route('/api/observations/recent', methods=['GET'])
@log_api_request
@handle_api_errors
def get_recent_observations():
    unique = request.args.get('unique', 'false').lower() == 'true'
    observations = db_manager.get_latest_detections(7, unique=unique)
    log_data_metrics('get_recent_observations', observations)
    return jsonify(observations)

@api.route('/api/observations/summary', methods=['GET'])
@log_api_request
@handle_api_errors
def get_observation_summary():
    now = local_now()
    settings = load_user_settings()
    summary = {
        'today': _localize_summary(
            db_manager.get_summary_stats(now.replace(hour=0, minute=0, second=0, microsecond=0)),
            settings=settings,
        ),
        'week': _localize_summary(
            db_manager.get_summary_stats(now - timedelta(weeks=1)),
            settings=settings,
        ),
        'month': _localize_summary(
            db_manager.get_summary_stats(now - timedelta(days=30)),
            settings=settings,
        ),
        'allTime': _localize_summary(db_manager.get_summary_stats(), settings=settings)
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
    activity = db_manager.get_hourly_activity(date)
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
    overview = db_manager.get_activity_overview(date, order=order)
    overview = _localize_activity_items(overview, settings=settings)
    log_data_metrics('get_activity_overview', overview, {
        'date': date,
        'species_count': len(overview) if overview else 0
    })
    return jsonify(overview)

@api.route('/api/dashboard', methods=['GET'])
@log_api_request
@handle_api_errors
def get_dashboard():
    """Consolidated dashboard endpoint — all DB data in one request."""
    now = local_now()
    today = now.strftime('%Y-%m-%d')
    settings = load_user_settings()

    recent_all = db_manager.get_latest_detections(7)
    recent_unique = db_manager.get_latest_detections(7, unique=True)
    recent_all = _localize_detection_list(recent_all, settings=settings)
    recent_unique = _localize_detection_list(recent_unique, settings=settings)
    latest = recent_all[0] if recent_all else None

    summary = {
        'today': _localize_summary(
            db_manager.get_summary_stats(now.replace(hour=0, minute=0, second=0, microsecond=0)),
            settings=settings,
        ),
        'week': _localize_summary(
            db_manager.get_summary_stats(now - timedelta(weeks=1)),
            settings=settings,
        ),
        'month': _localize_summary(
            db_manager.get_summary_stats(now - timedelta(days=30)),
            settings=settings,
        ),
        'allTime': _localize_summary(db_manager.get_summary_stats(), settings=settings)
    }

    hourly_activity = db_manager.get_hourly_activity(today)
    activity_overview = _localize_activity_overview(
        db_manager.get_activity_overview_both(today),
        settings=settings,
    )

    return jsonify({
        'latestObservation': latest,
        'recentObservations': {'all': recent_all, 'unique': recent_unique},
        'summary': summary,
        'hourlyActivity': hourly_activity,
        'activityOverview': activity_overview
    })

@api.route('/api/sightings/unique', methods=['GET'])
@log_api_request
@validate_date_param(required=True)
@handle_api_errors
def get_unique_detections():
    date_str = request.args.get('date')
    settings = load_user_settings()
    # Get the unique detections from the database
    unique_detections = db_manager.get_detections_by_date_range(date_str, date_str, unique=True)
    unique_detections = _localize_detection_list(unique_detections, settings=settings)
    log_data_metrics('get_unique_detections', unique_detections, {
        'date': date_str,
        'unique_species': len(unique_detections)
    })
    return jsonify(unique_detections)

@api.route('/api/sightings', methods=['GET'])
@validate_limit_param(default=12)
@handle_api_errors
def get_sightings():
    """Consolidated endpoint for different types of sightings

    Query params:
    - type: 'frequent' or 'rare' (default: 'frequent')
    - limit: number of results (default: 12)
    """
    sighting_type = request.args.get('type', 'frequent')
    limit = request.args.get('limit', default=12, type=int)

    settings = load_user_settings()
    if sighting_type == 'frequent':
        sightings = db_manager.get_species_sightings(limit=limit, most_frequent=True)
    elif sighting_type == 'rare':
        sightings = db_manager.get_species_sightings(limit=limit, most_frequent=False)
    else:
        return jsonify({"error": "Invalid sighting type. Use 'frequent' or 'rare'"}), 400

    sightings = _localize_detection_list(sightings, settings=settings)
    return jsonify(sightings)


@api.route('/api/audio/<filename>')
def serve_audio(filename):
    return serve_file_with_fallback(EXTRACTED_AUDIO_DIR, filename, DEFAULT_AUDIO_PATH, "audio")

@api.route('/api/spectrogram/<filename>')
def serve_spectrogram(filename):
    return serve_file_with_fallback(SPECTROGRAM_DIR, filename, DEFAULT_IMAGE_PATH, "spectrogram")

@api.route('/api/bird/<species_name>', methods=['GET'])
@log_api_request
def get_bird_details(species_name):
    settings = load_user_settings()
    details = db_manager.get_bird_details(species_name)
    if details:
        details = _localize_detection(details, settings=settings)
        logger.debug("Bird details retrieved", extra={
            'species': species_name,
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


@api.route('/api/bird/<species_name>/recordings', methods=['GET'])
@log_api_request
def get_bird_recordings(species_name):
    """Get recordings for a species with sorting options.

    Query params:
    - sort: 'recent' (default, timestamp DESC) or 'best' (confidence DESC)
    - limit: optional max number of records (omit for all)
    """
    sort = request.args.get('sort', 'recent')
    limit = request.args.get('limit', type=int)  # None if not provided

    # Validate sort parameter
    if sort not in ['recent', 'best']:
        return jsonify({"error": "Sort must be 'recent' or 'best'"}), 400

    settings = load_user_settings()
    recordings = _localize_detection_list(
        db_manager.get_bird_recordings(species_name, sort, limit),
        settings=settings,
    )
    logger.debug("Bird recordings retrieved", extra={
        'species': species_name,
        'sort': sort,
        'limit': limit,
        'records_count': len(recordings)
    })
    return jsonify(recordings)

@api.route('/api/bird/<species_name>/detection_distribution', methods=['GET'])
@validate_date_param()
@handle_api_errors
def get_detection_distribution(species_name):
    view = request.args.get('view', 'month')
    date = request.args.get('date', local_now().strftime('%Y-%m-%d'))
    distribution = db_manager.get_detection_distribution(species_name, view, date)
    return jsonify(distribution)

@api.route('/api/species/all', methods=['GET'])
@log_api_request
@handle_api_errors
def get_all_species():
    """Get all unique bird species ever detected"""
    species_list = _localize_species_list(
        db_manager.get_all_unique_species(),
        settings=load_user_settings(),
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

    trends = db_manager.get_daily_detection_counts(start_date, end_date)

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

    # Cap per_page at 100 (same as db method)
    per_page = min(max(1, per_page), 100)
    settings = load_user_settings()
    bird_name_language = get_bird_name_language(settings)

    if sort == 'common_name' and bird_name_language != DEFAULT_BIRD_NAME_LANGUAGE:
        # Sort the fully localized labels in memory so the rendered order matches
        # what the user sees, even across paginated results.
        detections = _localize_detection_list(
            db_manager.get_all_detections(
                start_date=start_date,
                end_date=end_date,
                species=species,
            ),
            settings=settings,
        )
        detections.sort(
            key=lambda detection: (
                detection.get('display_common_name', detection.get('common_name', '')).casefold()
            ),
            reverse=order.lower() != 'asc',
        )
        total_count = len(detections)
        offset = (page - 1) * per_page
        detections = detections[offset:offset + per_page]
    else:
        detections, total_count = db_manager.get_paginated_detections(
            page=page,
            per_page=per_page,
            start_date=start_date,
            end_date=end_date,
            species=species,
            sort=sort,
            order=order
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
    """Export all detections as CSV file.

    Requires authentication.

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

    # Fetch all detections
    detections = db_manager.get_all_detections_for_export(
        start_date=start_date,
        end_date=end_date,
        species=species
    )

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        'id', 'timestamp', 'group_timestamp', 'scientific_name', 'common_name',
        'confidence', 'latitude', 'longitude', 'cutoff', 'sensitivity', 'overlap',
        'week', 'extra', 'audio_source'
    ])

    # Write data rows
    for detection in detections:
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

    # Generate filename with timestamp
    timestamp = local_now().strftime('%Y%m%d_%H%M%S')
    filename = f'birdnet_detections_{timestamp}.csv'

    return Response(
        output.getvalue(),
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
    # Delete from database (returns detection info for file cleanup)
    detection = db_manager.delete_detection(detection_id)

    if not detection:
        return jsonify({'error': 'Detection not found'}), 404

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

        detection = db_manager.delete_detection(detection_id)
        if not detection:
            failed.append({'id': detection_id, 'error': 'Not found'})
            continue

        # Clean up associated files using shared utility
        delete_detection_files(detection)

        deleted.append(detection_id)

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


def _localize_detection(detection, settings=None):
    return add_display_common_name(
        detection,
        language=get_bird_name_language(settings),
        settings=settings,
    )


def _localize_detection_list(detections, settings=None):
    return [_localize_detection(detection, settings=settings) for detection in detections]


def _localize_species_list(species_list, settings=None):
    localized = [_localize_detection(species, settings=settings) for species in species_list]
    localized.sort(key=lambda species: species.get('display_common_name', species.get('common_name', '')))
    return localized


def _localize_summary(summary, settings=None):
    localized_summary = dict(summary)

    for key in ('mostCommonBird', 'rarestBird'):
        bird_name = localized_summary.get(key)
        localized_summary[f'{key}Display'] = (
            get_localized_common_name_from_english(
                bird_name,
                language=get_bird_name_language(settings),
                settings=settings,
            )
            if bird_name and bird_name != 'N/A'
            else bird_name
        )

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
    """Receive recorder health status from main container and broadcast to clients.

    Internal-only endpoint - only accessible from docker network or localhost.
    Called by the main processing container on recorder state changes.
    """
    global _recorder_status
    try:
        _recorder_status = request.json
        if socketio:
            socketio.emit('recorder_status', _recorder_status)
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
    'first_of_day', 'new_species', 'rare_species', 'rare_threshold', 'rare_window_days'
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
    for bool_field in ('every_detection', 'first_of_day', 'new_species', 'rare_species'):
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
    json_path = os.path.join(BASE_DIR, 'data', 'config', 'user_settings.json')
    temp_file = json_path + '.tmp'

    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    # Atomic write
    with open(temp_file, 'w') as f:
        json.dump(settings_dict, f, indent=2)

    os.rename(temp_file, json_path)
    logger.info("User settings saved", extra={
        'path': json_path
    })

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
def get_default_settings_endpoint():
    """Get default settings (single source of truth for frontend reset)"""
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

        # Load current settings, update units, save
        current_settings = load_user_settings()
        if 'display' not in current_settings:
            current_settings['display'] = {}
        current_settings['display']['use_metric_units'] = use_metric
        save_user_settings(current_settings)
        invalidate_runtime_settings_cache()

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


@api.route('/api/system/version', methods=['GET'])
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
            return jsonify(response), 200

        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available. Run build.sh to generate version.json'
            }), 500

        return jsonify({
            'version': version_info.get('version', 'unknown'),
            'current_commit': version_info.get('commit', 'unknown'),
            'current_commit_date': version_info.get('commit_date', 'unknown'),
            'current_branch': version_info.get('branch', 'unknown'),
            'remote_url': version_info.get('remote_url', f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}'),
            'runtime_mode': runtime_mode,
        }), 200
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
    public_features = sorted(get_public_features()) if auth_enabled else []
    settings = get_runtime_settings()
    return jsonify({
        'auth_enabled': auth_enabled,
        'setup_complete': is_setup_complete(),
        'authenticated': is_authenticated(),
        'public_features': public_features,
        'station_name': settings.get('display', {}).get('station_name', '')
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
    Valid keys: charts_public, table_public, live_feed_public (all booleans).
    """
    data = request.json
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    valid_keys = {'charts_public', 'table_public', 'live_feed_public'}
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
        file.save(temp_path)
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
            total_records=total_records
        )

        logger.info("Migration import completed", extra={
            'migration_id': temp_path,
            'imported': result['imported'],
            'skipped': result['skipped'],
            'errors': result['errors']
        })

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
            import_audio_files(db_manager, scan_result['matched_files'], import_id)
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
            generate_spectrograms_batch(scan_result['files_needing'], generation_id)
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


# Global SocketIO instance to be used by other modules
socketio = None

# Latest recorder health status (populated by main container broadcasts)
_recorder_status = {}

def create_app():
    global socketio
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

    # Initialize SocketIO.
    # `cors_allowed_origins=None` lets Engine.IO compute allowed origins from the
    # request host headers (same-origin only). Do not set this to [] (blocks all origins).
    socketio = SocketIO(app, cors_allowed_origins=None, logger=False, engineio_logger=False)

    # WebSocket event handlers
    @socketio.on('connect')
    def handle_connect():
        if not is_feature_public('live_feed') and not session.get('authenticated', False):
            return False  # Reject connection
        logger.info('WebSocket client connected')
        emit('status', {'message': 'Connected to live detection feed'})
        if _recorder_status:
            emit('recorder_status', _recorder_status)

    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info('WebSocket client disconnected')

    return app, socketio

def broadcast_detection(detection_data):
    """Function to broadcast detection to all connected clients"""
    global socketio
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
