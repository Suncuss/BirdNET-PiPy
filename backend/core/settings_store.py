"""User settings persistence: load/save + field validation helpers.

The settings file is the single source of truth shared by every service;
reads go through the runtime-settings cache (core.runtime_config) and writes
are atomic. The routes in core/routes/settings.py own request parsing and the
restart-required classification; this module owns the file.
"""
from config.settings import USER_SETTINGS_PATH, get_default_settings
from core.logging_config import get_logger
from core.recording_schedule import validate_quiet_hours
from core.runtime_config import (
    get_runtime_settings,
    invalidate_runtime_settings_cache,
)
from core.secure_file import atomic_write_private_json

logger = get_logger(__name__)


def load_user_settings():
    """Compatibility wrapper around runtime settings loader."""
    return get_runtime_settings(force_reload=True)


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
    # The file carries RTSP credentials, notification URLs, the BirdWeather ID
    # and coordinates. Its temporary file is 0600 before content is written.
    atomic_write_private_json(json_path, settings_dict)

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


def update_quiet_hours(incoming):
    """Merge a (possibly partial) quiet_hours object over the stored one and persist.

    Omitted fields keep their stored value (defaults underneath). Returns
    ``(merged, None)`` on success or ``(None, error)`` when the merged result
    fails validation — nothing is written in that case. No restart: the main
    container re-evaluates schedule.* from the settings file every tick.
    """
    current_settings = load_user_settings()
    schedule = current_settings.get('schedule')
    if not isinstance(schedule, dict):
        schedule = {}
    current = schedule.get('quiet_hours')
    merged = {
        **get_default_settings()['schedule']['quiet_hours'],
        **(current if isinstance(current, dict) else {}),
        **incoming,
    }
    error = validate_quiet_hours(merged)
    if error:
        return None, error

    schedule['quiet_hours'] = merged
    current_settings['schedule'] = schedule
    save_user_settings(current_settings)
    invalidate_runtime_settings_cache()
    return merged, None
