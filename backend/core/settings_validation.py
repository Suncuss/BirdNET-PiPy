"""Validation and repair shared by the settings loader and every write route.

Every value rule carries its repair, so a file an older version wrote always
loads into a document that passes every current rule. A wrong type on a
top-level scalar has no repair and makes the file unreadable: resetting one
would guess (a string "false" for public access must never become the
default True). Inside a rule's own domain a bad value repairs like any other.
"""
import copy
import math
import re
from zoneinfo import ZoneInfo

from config.constants import (
    OVERLAP_OPTIONS,
    RECORDING_LENGTH_OPTIONS,
    UPDATE_CHANNELS,
    VALID_MODEL_TYPES,
)

_SOURCE_FIELDS = frozenset({'id', 'type', 'url', 'device', 'label', 'enabled'})
_SOURCE_ID = re.compile(r'source_[0-9]+')
MAX_SOURCES = 10


def validate_settings_shape(settings):
    """Types and structure only: the errors that make a document unreadable."""
    from config.settings import DEFAULT_SETTINGS

    def shape(value, default, path=''):
        if isinstance(default, dict):
            if not isinstance(value, dict):
                return f'{path or "Settings"} must be a JSON object'
            for key, item in value.items():
                name = f'{path}.{key}' if path else key
                if key not in default:
                    return f'Unknown setting: {name}'
                error = shape(item, default[key], name)
                if error:
                    return error
        elif isinstance(default, bool):
            if type(value) is not bool:
                return f'{path} must be a boolean'
        elif isinstance(default, (int, float)):
            if type(value) not in (int, float) or not math.isfinite(value):
                return f'{path} must be a finite number'
        elif isinstance(default, list):
            if not isinstance(value, list):
                return f'{path} must be an array'
            if path != 'audio.sources' and not all(isinstance(v, str) for v in value):
                return f'{path} must be a list of strings'
        elif default is None:
            if value is not None and not isinstance(value, str):
                return f'{path} must be a string or null'
        elif not isinstance(value, str):
            return f'{path} must be a string'
        return None

    return shape(settings, DEFAULT_SETTINGS)


def _read(settings, path):
    section, key = path.split('.')
    return settings.get(section, {}).get(key)


def _write(settings, path, value):
    section, key = path.split('.')
    settings.setdefault(section, {})[key] = value


def _default(path):
    from config.settings import DEFAULT_SETTINGS
    section, key = path.split('.')
    return copy.deepcopy(DEFAULT_SETTINGS[section][key])


def _reset(path):
    return lambda settings: _write(settings, path, _default(path))


# Each rule is (check, repair). check(settings) returns a user-facing error or
# None and must tolerate absent keys; repair(settings) runs on a full document
# and makes check pass. Order matters: single-value rules run before the rules
# that compare two values, and the source list is cleaned before the id
# allocator is checked against it.

_RANGES = {
    'location.latitude': (-90, 90), 'location.longitude': (-180, 180),
    'detection.sensitivity': (0.1, 1), 'detection.cutoff': (0, 1),
    'detection.species_filter_threshold': (0, 1),
    'storage.trigger_percent': (0, 100), 'storage.target_percent': (0, 100),
    'spectrogram.min_freq_khz': (0, 24), 'spectrogram.max_freq_khz': (0, 24),
    'spectrogram.min_dbfs': (-200, 0), 'spectrogram.max_dbfs': (-200, 0),
}

def _range_rule(path, low, high):
    def check(settings):
        value = _read(settings, path)
        if value is not None and not low <= value <= high:
            return f'{path} must be between {low} and {high}'

    def repair(settings):
        _write(settings, path, min(max(_read(settings, path), low), high))
    return check, repair


def _options_rule(path, options):
    def check(settings):
        value = _read(settings, path)
        if value is not None and value not in options:
            return f'Invalid {path}. Expected one of: {", ".join(map(str, options))}'
    return check, _reset(path)


def _minimum_rule(path, minimum):
    def check(settings):
        value = _read(settings, path)
        if value is not None and (type(value) is not int or value < minimum):
            return f'{path} must be an integer of at least {minimum}'

    def repair(settings):
        value = _read(settings, path)
        _write(settings, path, max(value, minimum) if type(value) is int else _default(path))
    return check, repair


def _non_negative_rule(path, *, positive=False):
    def check(settings):
        value = _read(settings, path)
        if value is not None and (value < 0 or (positive and value == 0)):
            return f'{path} must be {"positive" if positive else "non-negative"}'
    return check, _reset(path)


def _ordering_rule(section, low, high):
    low_path, high_path = f'{section}.{low}', f'{section}.{high}'

    def check(settings):
        values = settings.get(section, {})
        if low in values and high in values and values[low] >= values[high]:
            return f'{section}.{low} must be less than {high}'

    def repair(settings):
        # Keep the threshold the user set: the shipped low default if it fits
        # below it, else the default spacing below it; reset the pair only
        # when nothing fits.
        high_value = _read(settings, high_path)
        floor, _ = _RANGES[low_path]
        spacing = _default(high_path) - _default(low_path)
        for candidate in (_default(low_path), max(floor, high_value - spacing)):
            if candidate < high_value:
                _write(settings, low_path, candidate)
                return
        _write(settings, low_path, _default(low_path))
        _write(settings, high_path, _default(high_path))
    return check, repair


def _timezone_check(settings):
    timezone = settings.get('location', {}).get('timezone')
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ValueError, KeyError):
            return 'Invalid location.timezone'


def _timezone_repair(settings):
    # Keep the station running on the zone its coordinates imply; None means
    # "not configured" and stops the recorder until the location is re-saved.
    from core.timezone_lookup import get_timezone_for_location
    location = settings['location']
    zone = get_timezone_for_location(location['latitude'], location['longitude'])
    location['timezone'] = zone if zone and not _timezone_check({'location': {'timezone': zone}}) else None


def _language_check(settings):
    language = _read(settings, 'display.bird_name_language')
    if language is not None:
        from core.bird_name_utils import SUPPORTED_BIRD_NAME_LANGUAGES
        if language not in SUPPORTED_BIRD_NAME_LANGUAGES:
            return 'Invalid display.bird_name_language'


def _schedule_check(settings):
    if 'schedule' in settings:
        from core.recording_schedule import validate_schedule_settings
        return validate_schedule_settings(settings['schedule'])


def _schedule_repair(settings):
    from config.settings import get_default_settings
    settings['schedule'] = get_default_settings()['schedule']


def _source_error(source):
    """Why one source entry is unusable, or None."""
    if not isinstance(source, dict):
        return 'Each audio source must be a JSON object'
    if set(source) - _SOURCE_FIELDS:
        return 'Unknown audio source field'
    sid = source.get('id')
    if not isinstance(sid, str) or not _SOURCE_ID.fullmatch(sid):
        return 'Invalid source id. Must match source_<int>'
    if source.get('type') not in ('pulseaudio', 'rtsp'):
        return 'Invalid source type. Must be pulseaudio or rtsp'
    if 'enabled' in source and type(source['enabled']) is not bool:
        return 'Source enabled must be a boolean'
    for key in ('url', 'device', 'label'):
        if key in source and (not isinstance(source[key], str) or '\x00' in source[key]):
            return f'Source {key} must be a string without null bytes'
    if source['type'] == 'rtsp' and not source.get('url', '').startswith(('rtsp://', 'rtsps://')):
        return f'RTSP source {sid} must have a valid rtsp:// or rtsps:// URL'


def _sources_check(settings):
    seen, microphones = set(), 0
    for source in settings.get('audio', {}).get('sources', []):
        error = _source_error(source)
        if error:
            return error
        if source['id'] in seen:
            return f'Duplicate source id: {source["id"]}'
        seen.add(source['id'])
        microphones += source['type'] == 'pulseaudio'
    if microphones > 1:
        return 'Only one microphone source is allowed'
    if len(seen) > MAX_SOURCES:
        return f'At most {MAX_SOURCES} audio sources are supported'


def _highest_source_id(settings):
    ids = [int(s['id'][7:]) for s in settings.get('audio', {}).get('sources', [])]
    return max(ids, default=-1)


def _next_source_id_check(settings):
    audio = settings.get('audio', {})
    if audio.get('sources') and 'next_source_id' in audio and audio['next_source_id'] <= _highest_source_id(settings):
        return 'next_source_id must be greater than all existing source ids'


def _next_source_id_repair(settings):
    settings['audio']['next_source_id'] = _highest_source_id(settings) + 1


def _sources_repair(settings):
    """Keep every usable source, in order; drop what the recorder could not use."""
    kept, seen, microphones = [], set(), 0
    for source in settings.get('audio', {}).get('sources', []):
        if _source_error(source) or source['id'] in seen:
            continue
        if source['type'] == 'pulseaudio':
            microphones += 1
            if microphones > 1:
                continue
        seen.add(source['id'])
        kept.append(source)
    settings.setdefault('audio', {})['sources'] = kept[:MAX_SOURCES]


_RULES = [
    *(_range_rule(path, low, high) for path, (low, high) in _RANGES.items()),
    *(_options_rule(path, options) for path, options in (
        ('audio.recording_length', RECORDING_LENGTH_OPTIONS),
        ('audio.overlap', OVERLAP_OPTIONS), ('audio.recording_chunk_length', (3,)),
        ('model.type', VALID_MODEL_TYPES), ('updates.channel', UPDATE_CHANNELS),
        ('display.time_format', ('12h', '24h')),
    )),
    *(_minimum_rule(path, minimum) for path, minimum in (
        ('audio.next_source_id', 0), ('storage.keep_per_species', 0),
        ('storage.keep_recent_per_species', 0), ('storage.retention_days', 0),
        ('notifications.rare_threshold', 0), ('notifications.rare_window_days', 1),
    )),
    _non_negative_rule('notifications.rate_limit_seconds'),
    _non_negative_rule('storage.media_budget_gb'),
    _non_negative_rule('storage.check_interval_minutes', positive=True),
    *(_ordering_rule(section, low, high) for section, low, high in (
        ('storage', 'target_percent', 'trigger_percent'),
        ('spectrogram', 'min_freq_khz', 'max_freq_khz'),
        ('spectrogram', 'min_dbfs', 'max_dbfs'),
    )),
    (_timezone_check, _timezone_repair),
    (_language_check, _reset('display.bird_name_language')),
    (_schedule_check, _schedule_repair),
    (_sources_check, _sources_repair),
    (_next_source_id_check, _next_source_id_repair),
]


def validate_settings(settings):
    """Return a user-facing error, or None. Absent keys are not errors."""
    error = validate_settings_shape(settings)
    if error:
        return error
    for check, _ in _RULES:
        error = check(settings)
        if error:
            return error
    return None


def repair_settings(settings):
    """Bring a full, well-shaped document up to every current rule in place.

    Returns the rule messages that were acted on, for the log. The result
    passes validate_settings; the tripwire test holds every rule to that.
    """
    repairs = []
    for check, repair in _RULES:
        error = check(settings)
        if error:
            repair(settings)
            repairs.append(error)
    return repairs
