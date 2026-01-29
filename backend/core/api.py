from core.db import DatabaseManager
from core.storage_manager import delete_detection_files
from core.migration import (
    BirdNETPiMigrator,
    get_migration_progress,
    set_migration_progress,
    clear_migration_progress,
    start_migration_if_not_running
)
from core.migration_audio import (
    list_available_folders,
    scan_audio_files,
    check_disk_space,
    import_audio_files,
    get_audio_import_progress,
    clear_audio_import_progress,
    start_audio_import_if_not_running,
    scan_files_needing_spectrograms,
    generate_spectrograms_batch,
    get_spectrogram_progress,
    clear_spectrogram_progress,
    start_spectrogram_generation_if_not_running
)
import threading
from config.settings import SPECTROGRAM_DIR, EXTRACTED_AUDIO_DIR, DEFAULT_AUDIO_PATH, DEFAULT_IMAGE_PATH, API_PORT, BASE_DIR, STREAM_URL, RTSP_URL, RECORDING_MODE, LABELS_PATH, load_user_settings, get_default_settings
from config.constants import (
    RecordingMode,
    VALID_RECORDING_MODES,
    RECORDING_LENGTH_OPTIONS,
    OVERLAP_OPTIONS,
    UPDATE_CHANNELS,
)
from core.logging_config import setup_logging, get_logger, log_api_request
from core.api_utils import (
    handle_api_errors,
    validate_date_param,
    serve_file_with_fallback,
    validate_limit_param,
    log_data_metrics
)
from core.auth import (
    configure_session,
    require_auth,
    is_auth_enabled,
    is_setup_complete,
    is_authenticated,
    set_auth_enabled,
    setup_password,
    change_password,
    authenticate,
    logout,
    MIN_PASSWORD_LENGTH
)
from version import __version__, DISPLAY_NAME

from flask import Flask, Blueprint, jsonify, request, Response, session
from flask_socketio import SocketIO, emit
from datetime import datetime, timedelta
import os
import json
import requests
import time
import re
import csv
import io
import tempfile
import uuid

# Setup logging
setup_logging('api')
logger = get_logger(__name__)

api = Blueprint('api', __name__)
db_manager = DatabaseManager()


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
CACHE_EXPIRATION = 172800  # Cache expiration time in seconds (48 hours)
MAX_CACHE_SIZE = 1000  # Maximum number of cached entries


def _cleanup_expired_cache():
    """Remove expired entries from image cache."""
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
            "srsearch": f"{species_name} filetype:bitmap",
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
    
    image_data, error = fetch_wikimedia_image(species_name)
    
    if error:
        return jsonify({'error': error}), 404 if 'No results found' in error else 500
    
    logger.debug("Wikimedia image fetched", extra={
        'species': species_name,
        'has_image': bool(image_data)
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
    observations = db_manager.get_latest_detections(7)
    log_data_metrics('get_recent_observations', observations)
    return jsonify(observations)

@api.route('/api/observations/summary', methods=['GET'])
@log_api_request
@handle_api_errors
def get_observation_summary():
    summary = {
        'today': db_manager.get_summary_stats(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)),
        'week': db_manager.get_summary_stats(datetime.now() - timedelta(weeks=1)),
        'month': db_manager.get_summary_stats(datetime.now() - timedelta(days=30)),
        'allTime': db_manager.get_summary_stats()
    }
    log_data_metrics('get_observation_summary', summary, {
        'today_count': summary.get('today', {}).get('totalObservations', 0),
        'all_time_species': summary.get('allTime', {}).get('uniqueSpecies', 0)
    })    
    return jsonify(summary)

@api.route('/api/activity/hourly', methods=['GET'])
@log_api_request
@validate_date_param()
@handle_api_errors
def get_hourly_activity():
    date = request.args.get('date', default=datetime.now().strftime('%Y-%m-%d'))
    activity = db_manager.get_hourly_activity(date)
    log_data_metrics('get_hourly_activity', activity, {
        'date': date,
        'hours_with_activity': sum(1 for h in activity if h['count'] > 0)
    })
    return jsonify(activity)

@api.route('/api/activity/overview', methods=['GET'])
@log_api_request
@validate_date_param()
@handle_api_errors
def get_activity_overview():
    date = request.args.get('date', default=datetime.now().strftime('%Y-%m-%d'))
    overview = db_manager.get_activity_overview(date)
    log_data_metrics('get_activity_overview', overview, {
        'date': date,
        'species_count': len(overview) if overview else 0
    })
    return jsonify(overview)

@api.route('/api/sightings/unique', methods=['GET'])
@log_api_request
@validate_date_param(required=True)
@handle_api_errors
def get_unique_detections():
    date_str = request.args.get('date')
    # Get the unique detections from the database
    unique_detections = db_manager.get_detections_by_date_range(date_str, date_str, unique=True)
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

    if sighting_type == 'frequent':
        sightings = db_manager.get_species_sightings(limit=limit, most_frequent=True)
    elif sighting_type == 'rare':
        sightings = db_manager.get_species_sightings(limit=limit, most_frequent=False)
    else:
        return jsonify({"error": "Invalid sighting type. Use 'frequent' or 'rare'"}), 400
    
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
    details = db_manager.get_bird_details(species_name)
    if details:
        logger.debug("Bird details retrieved", extra={
            'species': species_name,
            'total_detections': details.get('detectionCount', 0)
        })
        return jsonify(details)
    return jsonify({"error": "Bird species not found"}), 404

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

    recordings = db_manager.get_bird_recordings(species_name, sort, limit)
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
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    distribution = db_manager.get_detection_distribution(species_name, view, date)
    return jsonify(distribution)

@api.route('/api/species/all', methods=['GET'])
@log_api_request
@handle_api_errors
def get_all_species():
    """Get all unique bird species ever detected"""
    species_list = db_manager.get_all_unique_species()
    log_data_metrics('get_all_species', species_list)
    return jsonify(species_list)


@api.route('/api/detections/trends', methods=['GET'])
@log_api_request
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

    detections, total_count = db_manager.get_paginated_detections(
        page=page,
        per_page=per_page,
        start_date=start_date,
        end_date=end_date,
        species=species,
        sort=sort,
        order=order
    )

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
        'confidence', 'latitude', 'longitude', 'cutoff', 'sensitivity', 'overlap', 'week', 'extra'
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
            extra_value
        ])

    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
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
_available_species_cache = None


def load_available_species():
    """Load all available species from the BirdNET model labels file.

    Returns list of dicts with scientific_name and common_name.
    Results are cached since the labels file doesn't change at runtime.
    """
    global _available_species_cache

    if _available_species_cache is not None:
        return _available_species_cache

    species_list = []
    try:
        with open(LABELS_PATH, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Format: "Scientific Name_Common Name"
                # e.g., "Turdus migratorius_American Robin"
                parts = line.split('_')
                if len(parts) >= 2:
                    scientific_name = parts[0]
                    common_name = parts[1]
                    species_list.append({
                        'scientific_name': scientific_name,
                        'common_name': common_name
                    })

        # Sort by common name for easier browsing
        species_list.sort(key=lambda x: x['common_name'])
        _available_species_cache = species_list
        logger.info("Loaded available species from labels", extra={
            'count': len(species_list)
        })
    except Exception as e:
        logger.error("Failed to load species labels", extra={
            'error': str(e),
            'path': LABELS_PATH
        })

    return species_list


@api.route('/api/species/available', methods=['GET'])
@log_api_request
@handle_api_errors
def get_available_species():
    """Get all species available in the BirdNET model (6521 species).

    Used for building include/exclude filter lists in the UI.
    Returns list of {scientific_name, common_name} sorted by common_name.
    """
    search = request.args.get('search', '').lower()
    species_list = load_available_species()

    # Filter by search term if provided
    if search:
        species_list = [
            s for s in species_list
            if search in s['scientific_name'].lower() or search in s['common_name'].lower()
        ]

    return jsonify({
        'species': species_list,
        'total': len(load_available_species()),
        'filtered': len(species_list)
    })

@api.route('/api/stream/config', methods=['GET'])
@require_auth
def get_stream_config():
    """Provide stream configuration for frontend based on recording mode"""

    if RECORDING_MODE == RecordingMode.PULSEAUDIO:
        # PulseAudio mode - provide Icecast stream URL
        return jsonify({
            'stream_url': '/stream/stream.mp3',
            'stream_type': 'icecast',
            'description': 'Local Icecast audio stream'
        })
    elif RECORDING_MODE == RecordingMode.RTSP:
        # RTSP mode - use Icecast to transcode RTSP to MP3 for browser
        if RTSP_URL:
            return jsonify({
                'stream_url': '/stream/stream.mp3',
                'stream_type': 'icecast',
                'description': 'RTSP stream via Icecast'
            })
        else:
            # rtsp mode but no URL configured
            return jsonify({
                'stream_url': None,
                'stream_type': 'none',
                'description': 'RTSP mode selected but no URL configured'
            })
    elif RECORDING_MODE == RecordingMode.HTTP_STREAM:
        # HTTP stream mode - use custom stream URL
        if STREAM_URL:
            return jsonify({
                'stream_url': STREAM_URL,
                'stream_type': 'custom',
                'description': 'User-defined audio stream'
            })
        else:
            # http_stream mode but no URL configured
            return jsonify({
                'stream_url': None,
                'stream_type': 'none',
                'description': 'HTTP stream mode selected but no URL configured'
            })
    else:
        # Unknown mode
        return jsonify({
            'stream_url': None,
            'stream_type': 'none',
            'description': 'Unknown recording mode'
        })

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
        f.write(content if content else datetime.now().isoformat())
    logger.debug("Flag file written", extra={
        'flag': flag_name,
        'content': content,
        'path': flag_file
    })

# GitHub API configuration
GITHUB_OWNER = "Suncuss"
GITHUB_REPO = "BirdNET-PiPy"
GITHUB_API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"

def load_version_info():
    """Load version information from version.json"""
    version_file = os.path.join(BASE_DIR, 'data', 'version.json')

    if not os.path.exists(version_file):
        logger.warning("version.json not found", extra={'path': version_file})
        return None

    try:
        with open(version_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to load version.json", extra={'error': str(e)})
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


@api.route('/api/settings', methods=['PUT'])
@log_api_request
@require_auth
def update_settings():
    """Update user settings and trigger service restart"""
    try:
        new_settings = request.json
        if not new_settings:
            return jsonify({'error': 'No settings data provided'}), 400

        # Validate recording mode settings
        if 'audio' in new_settings:
            recording_mode = new_settings['audio'].get('recording_mode')
            if recording_mode and recording_mode not in VALID_RECORDING_MODES:
                return jsonify({'error': f'Invalid recording_mode. Must be one of: {", ".join(VALID_RECORDING_MODES)}'}), 400

            # Validate RTSP URL if provided
            rtsp_url = new_settings['audio'].get('rtsp_url')
            if recording_mode == RecordingMode.RTSP and not rtsp_url:
                return jsonify({'error': 'RTSP URL required when recording_mode is "rtsp"'}), 400
            if rtsp_url and not rtsp_url.startswith(('rtsp://', 'rtsps://')):
                return jsonify({'error': 'Invalid RTSP URL. Must start with rtsp:// or rtsps://'}), 400

            # Validate HTTP stream URL if required
            stream_url = new_settings['audio'].get('stream_url')
            if recording_mode == RecordingMode.HTTP_STREAM and not stream_url:
                return jsonify({'error': 'Stream URL required when recording_mode is "http_stream"'}), 400
            if stream_url and not stream_url.startswith(('http://', 'https://')):
                return jsonify({'error': 'Invalid Stream URL. Must start with http:// or https://'}), 400

            # Validate recording_length
            recording_length = new_settings['audio'].get('recording_length')
            if recording_length is not None and recording_length not in RECORDING_LENGTH_OPTIONS:
                return jsonify({'error': 'Invalid recording_length. Must be 9, 12, or 15 seconds'}), 400

            # Validate overlap
            overlap = new_settings['audio'].get('overlap')
            if overlap is not None and overlap not in OVERLAP_OPTIONS:
                return jsonify({'error': 'Invalid overlap. Must be 0.0, 0.5, 1.0, 1.5, 2.0, or 2.5 seconds'}), 400

        # Save settings to JSON file
        save_user_settings(new_settings)
        
        # Write flag to trigger container restart
        write_flag('restart-backend')
        
        logger.info("Settings updated, triggering service restart", extra={
            'changed_sections': list(new_settings.keys())
        })
        
        return jsonify({
            'status': 'updated', 
            'message': 'Settings saved. Services will restart in 10-30 seconds.',
            'settings': new_settings
        }), 200
        
    except Exception as e:
        logger.error("Failed to update settings", extra={
            'error': str(e)
        }, exc_info=True)
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
    """Get current system version info from version.json"""
    try:
        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available. Run build.sh to generate version.json'
            }), 500

        return jsonify({
            'current_commit': version_info.get('commit', 'unknown'),
            'current_commit_date': version_info.get('commit_date', 'unknown'),
            'current_branch': version_info.get('branch', 'unknown'),
            'remote_url': version_info.get('remote_url', f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}')
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
    """
    try:
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

        logger.info("Update check initiated", extra={
            'current_commit': current_commit,
            'current_branch': current_branch,
            'channel': channel,
            'target_branch': target_branch
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

                return jsonify({
                    'update_available': update_available,
                    'current_commit': current_commit,
                    'remote_commit': remote_commit,
                    'commits_behind': None,  # Unknown for fresh sync
                    'current_branch': current_branch,
                    'target_branch': target_branch,
                    'channel': channel,
                    'preview_commits': [],  # No commit history available
                    'fresh_sync': fresh_sync,
                    'update_note': update_note
                }), 200
            else:
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

        return jsonify({
            'update_available': update_available,
            'current_commit': current_commit,
            'remote_commit': remote_commit,
            'commits_behind': commits_behind,
            'current_branch': current_branch,
            'target_branch': target_branch,
            'channel': channel,
            'preview_commits': comparison['commits'],
            'fresh_sync': fresh_sync,
            'update_note': update_note
        }), 200

    except Exception as e:
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


# =============================================================================
# Authentication Endpoints
# =============================================================================

@api.route('/api/auth/status', methods=['GET'])
def get_auth_status():
    """Get authentication status for frontend."""
    return jsonify({
        'auth_enabled': is_auth_enabled(),
        'setup_complete': is_setup_complete(),
        'authenticated': is_authenticated()
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
            return jsonify({'error': 'Password not set up. Use /api/auth/setup first.'}), 400

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
        set_auth_enabled(enabled)

        return jsonify({
            'success': True,
            'auth_enabled': enabled,
            'message': 'Authentication enabled' if enabled else 'Authentication disabled'
        }), 200

    except Exception as e:
        logger.error("Toggle auth error", extra={'error': str(e)})
        return jsonify({'error': 'Failed to toggle authentication'}), 500


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
    can_start = start_migration_if_not_running(temp_path, total_records)

    if not can_start:
        # Already running - return temp_path as migration_id so client can poll
        return jsonify({
            'status': 'already_running',
            'migration_id': temp_path,
            'message': 'Migration is already in progress'
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
        logger.info('WebSocket client connected')
        emit('status', {'message': 'Connected to live detection feed'})
    
    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info('WebSocket client disconnected')
    
    return app, socketio

def broadcast_detection(detection_data):
    """Function to broadcast detection to all connected clients"""
    global socketio
    if socketio:
        socketio.emit('bird_detected', detection_data)
        logger.debug("Detection broadcasted to WebSocket clients", extra={
            'species': detection_data.get('common_name', 'Unknown'),
            'confidence': detection_data.get('confidence')
        })

if __name__ == '__main__':
    logger.info("🌐 API server starting", extra={
        'port': API_PORT,
        'websocket': 'enabled'
    })
    app, socketio = create_app()
    socketio.run(app, host='0.0.0.0', port=API_PORT, debug=False, allow_unsafe_werkzeug=True)
