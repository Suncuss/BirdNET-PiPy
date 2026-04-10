"""Read, merge, and filter log files from all services."""

import json
import os
import re
from datetime import datetime

from config.constants import LOG_DEFAULT_LINES, LOG_MAX_LINES
from core.logging_config import make_json_safe
from core.timezone_service import get_timezone

# Pattern: [ISO-timestamp] message
_ICECAST_LINE_RE = re.compile(r'^\[([^\]]+)\]\s*(.*)')

# Ordered keyword tuples for inferring level from icecast plain-text lines
_LEVEL_KEYWORDS = (
    ('ERROR', ('ERROR', 'FATAL', 'failed', 'exit code')),
    ('WARNING', ('WARNING', 'Warning', 'retrying', 'reconnect')),
)


def _read_tail_lines(filepath, max_lines):
    """Read last max_lines from a file and its rotated backups (.1, .2)."""
    lines = []

    # Read rotated files first (oldest first), then the main file
    for suffix in ('.2', '.1', ''):
        path = filepath + suffix if suffix else filepath
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                lines.extend(f.readlines())
        except OSError:
            continue

    # Return only the last max_lines
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _parse_json_log_line(line):
    """Parse a JSON log line into a normalized dict, or None if malformed."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None

    if 'timestamp' not in obj or 'message' not in obj:
        return None

    # Collect extra fields
    standard_keys = {'timestamp', 'level', 'service', 'module', 'function', 'line', 'message', 'exception'}
    extra = {k: make_json_safe(v) for k, v in obj.items() if k not in standard_keys}

    return {
        'timestamp': obj['timestamp'],
        'level': obj.get('level', 'INFO'),
        'service': obj.get('service', 'unknown'),
        'message': obj['message'],
        'module': obj.get('module', ''),
        'extra': extra,
    }


def _parse_icecast_line(line):
    """Parse an icecast plain-text line into a normalized dict."""
    line = line.strip()
    if not line:
        return None

    match = _ICECAST_LINE_RE.match(line)
    if match:
        timestamp_str, message = match.group(1), match.group(2)
        try:
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            # Convert UTC to configured local timezone
            local_dt = dt.astimezone(get_timezone()).replace(tzinfo=None)
            timestamp = local_dt.strftime('%Y-%m-%dT%H:%M:%S')
        except ValueError:
            timestamp = timestamp_str
    else:
        message = line
        timestamp = ''

    # Infer level from message content
    level = 'INFO'
    for level_name, keywords in _LEVEL_KEYWORDS:
        if any(kw in message for kw in keywords):
            level = level_name
            break

    return {
        'timestamp': timestamp,
        'level': level,
        'service': 'icecast',
        'message': message,
        'module': '',
        'extra': {},
    }


# Log files to read: (filename, parser function)
_LOG_FILES = {
    'main.log': _parse_json_log_line,
    'api.log': _parse_json_log_line,
    'model.log': _parse_json_log_line,
    'icecast.log': _parse_icecast_line,
}


def _matches_filters(entry, service, search_lower):
    """Check if an entry matches all active filters."""
    if service and entry['service'] != service:
        return False
    if search_lower and search_lower not in entry['message'].lower():
        return False
    return True


def get_logs(service=None, search=None, limit=None, logs_dir=None):
    """Read all log files, merge, filter, and return newest-first entries.

    Returns:
        dict: {entries: list[dict], total: int}
    """
    if limit is None:
        limit = LOG_DEFAULT_LINES
    limit = min(limit, LOG_MAX_LINES)

    if logs_dir is None:
        from config.settings import LOGS_DIR
        logs_dir = LOGS_DIR

    search_lower = search.lower() if search else None

    # Read enough raw lines to have headroom for filtering
    raw_limit = limit * 3

    all_entries = []

    for filename, parse_fn in _LOG_FILES.items():
        filepath = os.path.join(logs_dir, filename)
        lines = _read_tail_lines(filepath, raw_limit)

        for line in lines:
            entry = parse_fn(line)
            if entry and _matches_filters(entry, service, search_lower):
                all_entries.append(entry)

    # Sort by timestamp descending (filtered entries only)
    all_entries.sort(key=lambda e: e['timestamp'], reverse=True)
    total = len(all_entries)

    return {
        'entries': all_entries[:limit],
        'total': total,
    }
