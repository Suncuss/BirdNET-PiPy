"""Settings endpoints: read/update user settings, per-section instant saves.

The main PUT /api/settings applies changes without a container restart:
core.runtime_config classifies which sections changed and the affected
services pick the new values up live. Persistence itself lives in
core.settings_store. Registered on the shared ``api`` blueprint at import.
"""

from flask import jsonify, request

from config.constants import (
    UPDATE_CHANNELS,
)
from config.settings import SettingsUnreadable, get_default_settings
from core.api_infra import api
from core.auth import require_auth
from core.bird_name_utils import (
    clear_bird_name_caches,
)
from core.ha_mode import is_home_assistant_mode
from core.logging_config import get_logger, log_api_request
from core.runtime_config import (
    classify_setting_changes,
    deep_merge_settings,
    get_setting_differences,
    invalidate_runtime_settings_cache,
    read_saved_settings,
)
from core.settings_store import (
    _persist_no_restart_setting,
    _validate_notification_settings,
    load_user_settings,
    save_user_settings,
    serialize_settings_write,
    settings_etag,
    update_quiet_hours,
)
from core.settings_validation import validate_settings, validate_settings_shape
from core.timezone_lookup import get_timezone_for_location
from core.utils import normalize_site_url

logger = get_logger(__name__)


@api.route('/api/settings', methods=['GET'])
@log_api_request
@require_auth
def get_settings():
    """Get all user settings"""
    try:
        settings = read_saved_settings(force_reload=True)
        response = jsonify(settings)
        response.headers['ETag'] = settings_etag(settings)
        return response, 200
    except SettingsUnreadable as e:
        logger.error("Saved settings unreadable", extra={'error': str(e)})
        return jsonify({'error': str(e), 'code': 'settings_unreadable'}), 503
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
@serialize_settings_write
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
@serialize_settings_write
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
@serialize_settings_write
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
@serialize_settings_write
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


@api.route('/api/settings/schedule', methods=['PUT'])
@log_api_request
@require_auth
@serialize_settings_write
def update_schedule_setting():
    """Update the recording schedule (quiet hours) without triggering a restart.

    The main container re-evaluates schedule.* from the settings file on every
    recorder tick, so the change takes effect within seconds. Accepts a
    partial quiet_hours object; omitted fields keep their current value.
    """
    try:
        data = request.json
        if not data or 'quiet_hours' not in data:
            return jsonify({'error': 'quiet_hours field required'}), 400
        incoming = data['quiet_hours']
        if not isinstance(incoming, dict):
            return jsonify({'error': 'quiet_hours must be a JSON object'}), 400

        merged, error = update_quiet_hours(incoming)
        if error:
            return jsonify({'error': error}), 400

        logger.info("Quiet hours changed", extra={'quiet_hours': merged})

        return jsonify({
            'success': True,
            'quiet_hours': merged
        }), 200

    except Exception as e:
        logger.error("Failed to update schedule setting", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500


@api.route('/api/settings/notifications', methods=['PUT'])
@log_api_request
@require_auth
@serialize_settings_write
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
@serialize_settings_write
def update_settings():
    """Update user settings and apply changes without container restart."""
    try:
        incoming_settings = request.json
        if not incoming_settings or not isinstance(incoming_settings, dict):
            return jsonify({'error': 'No settings data provided'}), 400

        current_settings = load_user_settings()
        new_settings = deep_merge_settings(current_settings, incoming_settings)

        # Types first, before any normalizer below touches a value; the value
        # rules run on the finished document.
        error = validate_settings_shape(new_settings)
        if error:
            return jsonify({'error': error}), 400
        if any(key in incoming_settings.get('location', {}) for key in ('latitude', 'longitude')):
            new_settings['location']['configured'] = True
        # The server owns model-aware defaults, including API-only clients.
        if new_settings.get('model', {}).get('type') != current_settings.get('model', {}).get('type'):
            from config.constants import (
                DEFAULT_GEOMODEL_FILTER_THRESHOLD,
                DEFAULT_SPECIES_FILTER_THRESHOLD,
            )
            if 'species_filter_threshold' not in incoming_settings.get('detection', {}):
                new_settings.setdefault('detection', {})['species_filter_threshold'] = (
                    DEFAULT_GEOMODEL_FILTER_THRESHOLD if new_settings['model']['type'] == 'birdnet_v3'
                    else DEFAULT_SPECIES_FILTER_THRESHOLD)
        if 'site_url' in incoming_settings.get('display', {}):
            try:
                new_settings['display']['site_url'] = normalize_site_url(new_settings['display']['site_url'])
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400

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

        error = validate_settings(new_settings)
        if error:
            return jsonify({'error': error}), 400

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
        if any(path.startswith("access.") for path in changed_paths):
            from core.api import revoke_public_sockets
            revoke_public_sockets()

        logger.info("Settings updated", extra={
            'changed_sections': list(incoming_settings.keys()),
            'changed_paths': changed_paths,
            'full_restart_required': change_plan['full_restart_required']
        })

        if not changed_paths:
            message = 'No changes detected.'
        elif change_plan['full_restart_required']:
            message = 'Settings saved. Restart services to apply the model change.'
        else:
            message = 'Settings saved. Live settings take effect at the next processing boundary.'

        return jsonify({
            'status': 'updated',
            'message': message,
            'settings': new_settings,
            'changes': {
                'changed_paths': changed_paths,
                'hot_reload_paths': change_plan['hot_reload_paths'],
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
