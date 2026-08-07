"""Bird image sourcing: Wikimedia lookups, custom uploads, and choice sidecars.

Everything about where a species' picture comes from lives here — the cached
two-step Wikimedia Commons lookup (with single-flight dedup of concurrent
misses), the on-disk custom image files, and the per-species "which Wikimedia
image did the owner pick" sidecar JSONs. The routes in core/routes/images.py
stay thin: they translate these results to HTTP responses.
"""
import json
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests

from config.settings import CUSTOM_BIRD_IMAGES_DIR
from core.logging_config import get_logger
from version import DISPLAY_NAME, __version__

logger = get_logger(__name__)

# Simple in-memory cache
image_cache = {}
_image_cache_lock = threading.Lock()  # hub-only: Wikimedia fetches run in request greenlets, never the DB lane
CACHE_EXPIRATION = 172800  # Cache expiration time in seconds (48 hours)
MAX_CACHE_SIZE = 1000  # Maximum number of cached entries

# Single-flight coordination for Wikimedia lookups. These deliberately do NOT
# go through db_executor: that is a single SQLite lane, and a slow external
# HTTP call there would block unrelated database work. The HTTP runs inline in
# the request greenlet (under gevent, socket waits yield the event loop); this
# map only dedups concurrent cache-misses for the same (species, limit) so they
# share one upstream fetch instead of each hammering Wikimedia.
_wikimedia_inflight = {}
_wikimedia_inflight_lock = threading.Lock()  # hub-only: see above
_WIKIMEDIA_FETCH_TIMEOUT = 30  # waiter cap; the leader does up to 10s+15s of HTTP


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
