"""Settings endpoints: read/update user settings, per-section instant saves.

The main PUT /api/settings applies changes without a container restart:
core.runtime_config classifies which sections changed and the affected
services pick the new values up live. Persistence itself lives in
core.settings_store. Registered on the shared ``api`` blueprint at import.
"""
import re
import threading

from flask import jsonify, request

from config.constants import (
    OVERLAP_OPTIONS,
    RECORDING_LENGTH_OPTIONS,
    UPDATE_CHANNELS,
    VALID_MODEL_TYPES,
)
from config.settings import get_default_settings
from core.api_infra import api
from core.auth import require_auth
from core.bird_name_utils import (
    SUPPORTED_BIRD_NAME_LANGUAGES,
    clear_bird_name_caches,
)
from core.ha_mode import is_home_assistant_mode
from core.logging_config import get_logger, log_api_request
from core.runtime_config import (
    classify_setting_changes,
    deep_merge_settings,
    get_setting_differences,
    invalidate_runtime_settings_cache,
)
from core.settings_store import (
    _persist_no_restart_setting,
    _validate_notification_settings,
    load_user_settings,
    save_user_settings,
)
from core.utils import normalize_site_url

logger = get_logger(__name__)


# Singleton TimezoneFinder (loads ~40MB shape data on first use). The import
# itself is deferred into _get_timezone_finder(): it drags numpy/cffi/h3 into
# the worker, and the only caller is the settings handler resolving a newly
# saved location — a station that never edits its location never pays for it.
_timezone_finder = None
_tz_finder_lock = threading.Lock()  # hub-only: timezone lookup runs in settings-route greenlets, never the DB lane


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
                    # Full match, not a prefix check: the id becomes a directory
                    # name under RECORDING_DIR, so anything past the prefix has
                    # to be digits.
                    # [0-9], not \d: \d is Unicode-aware on str, so
                    # 'source_٣' would pass a check that reads as ASCII-only.
                    if not re.fullmatch(r'source_[0-9]+', sid or ''):
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

            if 'site_url' in incoming_settings['display']:
                site_url = incoming_settings['display']['site_url']
                if not isinstance(site_url, str):
                    return jsonify({'error': 'display.site_url must be a string'}), 400
                try:
                    new_settings['display']['site_url'] = normalize_site_url(site_url)
                except ValueError as e:
                    return jsonify({'error': str(e)}), 400

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
            from core.routes.observations import (
                invalidate_dashboard_cache,
                invalidate_gallery_cache,
            )
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
