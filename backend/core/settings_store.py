"""User settings persistence: load/save + field validation helpers.

The settings file is the single source of truth shared by every service;
reads go through the runtime-settings cache (core.runtime_config) and writes
are atomic. The routes in core/routes/settings.py own request parsing and the
restart-required classification; this module owns the file.
"""
import hashlib
import json
from functools import wraps
from threading import Lock

from flask import jsonify, make_response, request

from config.settings import USER_SETTINGS_PATH, SettingsUnreadable, get_default_settings
from core.logging_config import get_logger
from core.recording_schedule import validate_quiet_hours
from core.runtime_config import (
    get_runtime_settings,
    invalidate_runtime_settings_cache,
    read_saved_settings,
)
from core.secure_file import atomic_write_private_json
from core.settings_validation import validate_settings

logger = get_logger(__name__)

# hub-only: every settings mutation runs in an API request greenlet; in the
# threading/HA entrypoint the same object is a normal thread lock. Serializing
# the complete handler (not only its final save) prevents two whole-document
# read/modify/write operations from silently overwriting each other.
_settings_write_lock = Lock()  # hub-only: API request handlers only


def serialize_settings_write(func):
    """Serialize a settings handler's complete read/modify/write transaction."""
    @wraps(func)
    def serialized(*args, **kwargs):
        with _settings_write_lock:
            try:
                current = read_saved_settings(force_reload=True)
            except SettingsUnreadable as exc:
                return jsonify({'error': f'{exc}. Repair the settings file before saving.',
                                'code': 'settings_unreadable'}), 503
            # The ETag hashes the saved document. nginx marks it weak (W/) when
            # it compresses the response, which does not change that revision.
            expected = (request.headers.get('If-Match') or '').removeprefix('W/')
            if expected and expected != settings_etag(current):
                return jsonify({'error': 'Settings changed in another session. Refresh and retry.'}), 412
            try:
                result = func(*args, **kwargs)
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400
            response = make_response(result)
            if response.status_code < 300:
                saved = load_user_settings()
                response.headers['ETag'] = settings_etag(saved)
                payload = response.get_json(silent=True)
                if isinstance(payload, dict):
                    payload.setdefault('settings', saved)
                    response.set_data(json.dumps(payload))
            return response
    serialized._serializes_settings_write = True
    return serialized


def load_user_settings():
    """Compatibility wrapper around runtime settings loader."""
    return get_runtime_settings()


def settings_etag(settings):
    """Opaque content revision; the precondition is checked under the write lock."""
    data = json.dumps(settings, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return '"' + hashlib.sha256(data.encode()).hexdigest() + '"'


def _validate_notification_settings(notif):
    return validate_settings({'notifications': notif})


def save_user_settings(settings_dict):
    """Save settings to JSON file atomically"""
    error = validate_settings(settings_dict)
    if error:
        raise ValueError(error)
    json_path = USER_SETTINGS_PATH
    # The file carries RTSP credentials, notification URLs, the BirdWeather ID
    # and coordinates. Its temporary file is 0600 before content is written.
    atomic_write_private_json(json_path, settings_dict)
    invalidate_runtime_settings_cache()

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
