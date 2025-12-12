from core.db import DatabaseManager
from config.settings import SPECTROGRAM_DIR, EXTRACTED_AUDIO_DIR, DEFAULT_AUDIO_PATH, DEFAULT_IMAGE_PATH, API_PORT, BASE_DIR, STREAM_URL, RECORDING_MODE, load_user_settings
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

from flask import Flask, Blueprint, jsonify, request
from flask_socketio import SocketIO, emit
from datetime import datetime, timedelta
import os
import json
import requests
import time
import re
from flask_cors import CORS

# Setup logging
setup_logging('api')
logger = get_logger(__name__)

api = Blueprint('api', __name__)
db_manager = DatabaseManager()

# Simple in-memory cache
image_cache = {}
CACHE_EXPIRATION = 36000  # Cache expiration time in seconds (10 hours)

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

        search_response = requests.get(search_url, params=search_params, headers=headers)
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

        image_response = requests.get(image_url, params=image_params, headers=headers)
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
    observations = db_manager.get_latest_detections(8)
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
    - type: 'frequent', 'rare', or 'random' (default: 'frequent')
    - limit: number of results (default: 12)
    """
    sighting_type = request.args.get('type', 'frequent')
    limit = request.args.get('limit', default=12, type=int)
    
    if sighting_type == 'frequent':
        sightings = db_manager.get_species_sightings(limit=limit, most_frequent=True)
    elif sighting_type == 'rare':
        sightings = db_manager.get_species_sightings(limit=limit, most_frequent=False)
    elif sighting_type == 'random':
        sightings = db_manager.get_random_detections(limit=limit)
    else:
        return jsonify({"error": "Invalid sighting type. Use 'frequent', 'rare', or 'random'"}), 400
    
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

@api.route('/api/stream/config', methods=['GET'])
@require_auth
def get_stream_config():
    """Provide stream configuration for frontend based on recording mode"""

    if RECORDING_MODE == 'pulseaudio':
        # PulseAudio mode - provide Icecast stream URL
        return jsonify({
            'stream_url': '/stream/stream.mp3',
            'stream_type': 'icecast',
            'description': 'Local Icecast audio stream'
        })
    elif RECORDING_MODE == 'rtsp':
        # RTSP mode - use Icecast to transcode RTSP to MP3 for browser
        return jsonify({
            'stream_url': '/stream/stream.mp3',
            'stream_type': 'icecast',
            'description': 'RTSP stream via Icecast'
        })
    elif RECORDING_MODE == 'http_stream':
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
def broadcast_detection_endpoint():
    """Endpoint to broadcast detection via WebSocket"""
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

def write_flag(flag_name):
    """Write flag file to trigger host action"""
    flag_dir = os.path.join(BASE_DIR, 'data', 'flags')
    os.makedirs(flag_dir, exist_ok=True)
    flag_file = os.path.join(flag_dir, flag_name)
    with open(flag_file, 'w') as f:
        f.write(f"{datetime.now().isoformat()}\n")
    logger.debug("Flag file written", extra={
        'flag': flag_name,
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
            if recording_mode and recording_mode not in ['pulseaudio', 'http_stream', 'rtsp']:
                return jsonify({'error': 'Invalid recording_mode. Must be "pulseaudio", "http_stream", or "rtsp"'}), 400

            # Validate RTSP URL if provided
            rtsp_url = new_settings['audio'].get('rtsp_url')
            if rtsp_url and not rtsp_url.startswith(('rtsp://', 'rtsps://')):
                return jsonify({'error': 'Invalid RTSP URL. Must start with rtsp:// or rtsps://'}), 400

            # Validate recording_length
            recording_length = new_settings['audio'].get('recording_length')
            if recording_length is not None and recording_length not in [9, 12, 15]:
                return jsonify({'error': 'Invalid recording_length. Must be 9, 12, or 15 seconds'}), 400

            # Validate overlap
            overlap = new_settings['audio'].get('overlap')
            if overlap is not None and overlap not in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]:
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

@api.route('/api/system/update-check', methods=['GET'])
@log_api_request
@handle_api_errors
def check_for_updates():
    """Check if updates are available using GitHub API"""
    try:
        # Load current version info
        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available. Run build.sh to generate version.json'
            }), 500

        current_commit = version_info.get('commit', '')
        current_branch = version_info.get('branch', 'main')
        target_branch = 'main'  # Always check against main for updates

        logger.info("Update check initiated", extra={
            'current_commit': current_commit,
            'current_branch': current_branch,
            'target_branch': target_branch
        })

        if not current_commit or current_commit == 'unknown':
            return jsonify({
                'error': 'Current commit hash not available in version.json'
            }), 500

        # Get comparison from GitHub API
        comparison, error = get_commits_comparison(current_commit, target_branch)

        if error:
            logger.error("GitHub API comparison failed", extra={'error': error})
            return jsonify({'error': f'Failed to check for updates: {error}'}), 500

        # Use ahead_by: how many commits the remote is ahead of our local commit
        commits_behind = comparison.get('ahead_by', 0)
        update_available = commits_behind > 0

        logger.info("GitHub API comparison result", extra={
            'comparison_status': comparison.get('status'),
            'ahead_by': comparison.get('ahead_by'),
            'behind_by': comparison.get('behind_by'),  # Log for comparison
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

        return jsonify({
            'update_available': update_available,
            'current_commit': current_commit,
            'remote_commit': remote_commit,
            'commits_behind': commits_behind,
            'current_branch': current_branch,
            'target_branch': target_branch,
            'preview_commits': comparison['commits']
        }), 200

    except Exception as e:
        return jsonify({'error': f'Failed to check for updates: {str(e)}'}), 500

@api.route('/api/system/update', methods=['POST'])
@log_api_request
@handle_api_errors
def trigger_system_update():
    """Trigger system update by writing flag file.

    Note: Update availability is already verified by frontend via /api/system/update-check
    before this endpoint is called. No need to re-check here.
    """
    try:
        # Load current version info for validation and logging
        version_info = load_version_info()

        if version_info is None:
            return jsonify({
                'error': 'Version information not available'
            }), 500

        current_branch = version_info.get('branch', 'main')

        # Verify not on detached HEAD (branch would be "HEAD" in that case)
        if current_branch == 'HEAD':
            return jsonify({
                'error': 'Cannot update: repository in detached HEAD state'
            }), 400

        # Write update flag - service script will handle git pull and rebuild
        write_flag('update-requested')

        logger.info("System update triggered", extra={
            'current_commit': version_info.get('commit', 'unknown'),
            'current_branch': current_branch
        })

        return jsonify({
            'status': 'update_triggered',
            'message': 'System update initiated. Services will restart shortly.',
            'estimated_downtime': '2-5 minutes'
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


# Global SocketIO instance to be used by other modules
socketio = None

def create_app():
    global socketio
    app = Flask(__name__)

    # Configure CORS for API requests
    # supports_credentials=True is needed for session cookies to work
    # Without explicit origins, Flask-CORS mirrors the Origin header (required when credentials=True)
    # This is safe for a self-hosted app behind nginx reverse proxy
    CORS(app, supports_credentials=True)

    # Configure session for authentication
    configure_session(app)

    app.register_blueprint(api)

    # Initialize SocketIO with CORS support
    # For WebSocket connections, we need to allow cross-origin for development
    socketio = SocketIO(app, cors_allowed_origins="*", logger=False, engineio_logger=False)
    
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
