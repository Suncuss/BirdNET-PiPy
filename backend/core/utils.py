import logging
import re
import subprocess
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)

MAX_SITE_URL_LENGTH = 200


def normalize_site_url(raw):
    """Normalize and validate a user-entered site URL into a stored base URL.

    Accepts bare hosts (``birdnet.example.com`` → ``https://...``), strips
    trailing slashes, lowercases scheme/host, and preserves an optional path
    prefix. Returns '' for empty input (feature off). Raises ValueError with a
    user-facing message otherwise.

    The result is embedded in notification-email hrefs, so only http(s) is
    allowed and userinfo/query/fragment are rejected rather than silently
    dropped — surprising input should be seen, not reinterpreted.
    """
    value = (raw or '').strip()
    if not value:
        return ''
    if len(value) > MAX_SITE_URL_LENGTH:
        raise ValueError(f'Site URL must be at most {MAX_SITE_URL_LENGTH} characters')
    if '://' not in value:
        value = f'https://{value}'

    try:
        parts = urlsplit(value)
        port = parts.port  # raises ValueError on a malformed/out-of-range port
    except ValueError:
        raise ValueError('Site URL is not a valid URL') from None
    if parts.scheme not in ('http', 'https'):
        raise ValueError('Site URL must start with http:// or https://')
    if not parts.hostname:
        raise ValueError('Site URL must include a hostname')
    if '@' in parts.netloc:  # userinfo of any form
        raise ValueError('Site URL must not contain credentials')
    if parts.query or parts.fragment:
        raise ValueError('Site URL must not contain a query string or fragment')
    # Reject characters that could break out of an HTML attribute or a URL
    # path; normal hosts and path prefixes never contain them.
    if re.search(r'[\s<>"\'\\]', value):
        raise ValueError('Site URL contains invalid characters')

    host = parts.hostname  # urlsplit already lowercases scheme and hostname
    if ':' in host:  # IPv6 literal — urlsplit strips the brackets
        host = f'[{host}]'
    if port is not None:
        host = f'{host}:{port}'
    path = parts.path.rstrip('/')
    return f'{parts.scheme}://{host}{path}'


def build_detection_permalink(base_url, common_name, detection_id, share_token=None):
    """Build the canonical SPA permalink for one detection.

    Single owner of the ``/bird/<common name>/recording/<id>`` shape so email
    links and OG share cards can never drift. The species segment is
    decorative (the API resolves by id) but kept for readable URLs; it uses
    the DB common_name, which the SPA route resolves against.
    """
    name_segment = quote(common_name or 'Unknown', safe='')
    url = f"{base_url.rstrip('/')}/bird/{name_segment}/recording/{int(detection_id)}"
    if share_token:
        url += f'?s={quote(share_token, safe="")}'
    return url


def sanitize_source_label(label):
    """Sanitize a source label for use as a filename suffix.

    Strips whitespace, replaces spaces with underscores, removes characters
    not in [A-Za-z0-9_-], and truncates to 30 characters.

    Returns empty string if label is empty/None or contains only whitespace.
    """
    if not label:
        return ""
    result = label.strip()
    if not result:
        return ""
    result = result.replace(' ', '_')
    result = re.sub(r'[^A-Za-z0-9_-]', '', result)
    return result[:30]


def build_detection_filenames(common_name, confidence, timestamp, audio_extension='mp3', audio_source=None):
    """
    Generate standardized filenames for bird detection audio and spectrogram files.

    Args:
        common_name (str): Common name of the bird species (e.g., "American Robin")
        confidence (float): Detection confidence score (0.0 to 1.0)
        timestamp (str or datetime): ISO timestamp string or datetime object
        audio_extension (str): File extension for audio file ('mp3' or 'wav'). Default: 'mp3'
        audio_source (str or None): Filename suffix for the source (e.g., sanitized label "Backyard_Mic").
            If provided, appended before extension.

    Returns:
        dict: Dictionary with 'audio_filename' and 'spectrogram_filename' keys

    Example:
        >>> build_detection_filenames("American Robin", 0.85, "2025-11-24T10:30:45.123456")
        {'audio_filename': 'American_Robin_85_2025-11-24-birdnet-10-30-45.mp3',
         'spectrogram_filename': 'American_Robin_85_2025-11-24-birdnet-10-30-45.webp'}
        >>> build_detection_filenames("American Robin", 0.85, "2025-11-24T10:30:45.123456", audio_source="Backyard_Mic")
        {'audio_filename': 'American_Robin_85_2025-11-24-birdnet-10-30-45_Backyard_Mic.mp3',
         'spectrogram_filename': 'American_Robin_85_2025-11-24-birdnet-10-30-45_Backyard_Mic.webp'}
    """

    # Normalize common name to use underscores
    common_name_underscored = common_name.replace(' ', '_')

    # Round confidence to percentage (0-100)
    confidence_rounded = round(confidence * 100)

    # Parse timestamp if it's a string, otherwise assume it's a datetime object
    if isinstance(timestamp, str):
        # Split ISO format timestamp: "2025-11-24T10:30:45.123456"
        date_part = timestamp.split('T')[0]
        time_part = timestamp.split('T')[1]
        # Strip microseconds if present (handles timestamps like "11:38:39.000000")
        if '.' in time_part:
            time_part = time_part.split('.')[0]
    else:
        # Assume it's a datetime object
        date_part = timestamp.strftime('%Y-%m-%d')
        # Strip microseconds to match database timestamp format
        time_part = timestamp.strftime('%H:%M:%S')

    # Convert time colons to dashes for filesystem compatibility
    # (colons are not allowed in Windows filenames and can cause issues elsewhere)
    time_part_safe = time_part.replace(':', '-')

    # Build filenames using consistent format
    base = f"{common_name_underscored}_{confidence_rounded}_{date_part}-birdnet-{time_part_safe}"
    suffix = f"_{audio_source}" if audio_source else ""
    audio_filename = f"{base}{suffix}.{audio_extension}"
    spectrogram_filename = f"{base}{suffix}.webp"

    return {
        'audio_filename': audio_filename,
        'spectrogram_filename': spectrogram_filename
    }


def extract_audio_segment(source_file_path, output_mp3_path, start, end,
                          bitrate="320k", normalize=False, timeout=60,
                          output_format=None):
    """Extract [start, end] from a WAV and encode it to MP3 in one ffmpeg run.

    Replaces the former sox-trim + ffmpeg-encode pair: one process spawn and
    no intermediate WAV on disk — both matter on slow SD-card devices. The
    trim runs in the filter graph (atrim's end= is an absolute position, like
    sox's =end, and clamps at EOF the same way), which reproduces the old
    pipeline's output byte-for-byte, including under loudnorm.

    Loudness normalization is for human listening so faint/distant birds are
    audible; it runs after BirdNET analysis, so it never changes detections.

    Args:
        source_file_path: Path to source audio file
        output_mp3_path: Path to output MP3 file
        start: Segment start in seconds
        end: Segment end in seconds (absolute position; clamped at EOF)
        bitrate: MP3 bitrate (default: 320k)
        normalize: Apply loudness normalization (falls back to a plain
            conversion if the loudnorm pass fails, rather than lose the clip)
        timeout: Maximum time to wait in seconds (default: 60)
        output_format: Explicit ffmpeg output format (e.g. 'mp3') for
            destinations whose suffix doesn't say (atomic-publication temp
            files end in .part)

    Raises:
        subprocess.TimeoutExpired: If ffmpeg exceeds timeout
        subprocess.CalledProcessError: If ffmpeg fails
    """
    def _run(use_normalize):
        filters = f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS"
        if use_normalize:
            filters += ",loudnorm=I=-18:LRA=11:TP=-1.5"
        command = [
            "ffmpeg",
            "-y",  # Overwrite output file if it exists
            "-loglevel", "error",  # Suppress most of the output
            "-i", source_file_path,
            "-af", filters,
            "-ac", "1",  # Convert to mono
            "-codec:a", "libmp3lame",
            "-b:a", bitrate,
        ]
        if output_format:
            # ffmpeg infers the container from the destination suffix; a
            # temp path like clip.mp3.part needs the format stated.
            command += ["-f", output_format]
        command.append(output_mp3_path)
        subprocess.run(command, check=True, timeout=timeout, capture_output=True)

    if normalize:
        try:
            _run(True)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("Loudness normalization failed (%s); saving un-normalized clip", e)
    _run(False)


def select_audio_chunks(detected_chunk_index, total_chunks):
    """
    Select the range of audio chunks to extract based on the detected chunk index.

    For edge detections (first/last chunk): extracts 2 chunks (6 seconds)
    For middle detections: extracts 3 chunks centered on detection (9 seconds)

    Args:
        detected_chunk_index (int): The index of the chunk where detection occurred (0-based).
        total_chunks (int): The total number of chunks in the audio.

    Returns:
        tuple: (start_chunk_index, end_chunk_index) - both inclusive.
               Used by extract_detection_audio() to calculate time range.

    NOTE: the detection player's analysis-window bar re-derives this layout
    client-side (frontend/src/utils/analysisSegments.js) from
    timestamp/group_timestamp/overlap — it assumes at most ONE context chunk
    before the detected window. If the selection layout changes, update that
    derivation too (or start stamping the clip-relative window into the
    detection's extra field).
    """
    if detected_chunk_index < 0 or detected_chunk_index >= total_chunks:
        raise ValueError("detected_chunk_index must be within the range of total_chunks")

    if total_chunks < 3:
        # Return all chunks if fewer than 3
        return (0, total_chunks - 1)

    if detected_chunk_index == 0:
        # First chunk detected: extract chunks 0 and 1 (6 seconds)
        return (0, 1)
    elif detected_chunk_index == total_chunks - 1:
        # Last chunk detected: extract last 2 chunks (6 seconds)
        return (total_chunks - 2, total_chunks - 1)
    else:
        # Middle chunk: extract 3 chunks centered on detection (9 seconds)
        start = detected_chunk_index - 1
        end = detected_chunk_index + 1
        return (start, end)


def get_legacy_filename(filename):
    """Convert new dash-pattern filename to old colon-pattern.

    Used for fallback lookup of old files that still use colons in the time portion.

    Pattern: {species}_{conf}_{date}-birdnet-{HH-MM-SS}.ext
    Returns: {species}_{conf}_{date}-birdnet-{HH:MM:SS}.ext

    Args:
        filename: Filename with dash-pattern time (e.g., "Bird_85_2025-01-28-birdnet-10-30-45.mp3")

    Returns:
        Legacy filename with colon-pattern time, or None if pattern doesn't match

    Example:
        >>> get_legacy_filename("American_Robin_85_2025-01-28-birdnet-10-30-45.mp3")
        'American_Robin_85_2025-01-28-birdnet-10:30:45.mp3'
    """
    marker = '-birdnet-'
    if marker not in filename:
        return None

    idx = filename.index(marker) + len(marker)
    prefix = filename[:idx]
    suffix = filename[idx:]

    # Convert first two dashes in time portion to colons
    # HH-MM-SS.ext -> HH:MM:SS.ext
    parts = suffix.split('-', 2)
    if len(parts) >= 3:
        legacy_suffix = f"{parts[0]}:{parts[1]}:{parts[2]}"
        return prefix + legacy_suffix

    return None


def sanitize_url(url: str) -> str:
    """
    Mask credentials in URL for safe logging.

    Replaces password in URLs with '***' to prevent credential exposure in logs.

    Args:
        url: URL string that may contain embedded credentials

    Returns:
        URL with password masked, or original URL if no password present

    Example:
        >>> sanitize_url("rtsp://admin:secret123@192.168.1.100:554/stream")
        'rtsp://admin:***@192.168.1.100:554/stream'
        >>> sanitize_url("http://example.com/stream")
        'http://example.com/stream'
    """
    if not url:
        return url

    from urllib.parse import urlparse, urlunparse

    try:
        parsed = urlparse(url)

        # If no password, return original URL unchanged
        if not parsed.password:
            return url

        # Build new netloc with masked password
        if parsed.username:
            netloc = f"{parsed.username}:***@{parsed.hostname}"
        else:
            netloc = f":***@{parsed.hostname}"

        if parsed.port:
            netloc += f":{parsed.port}"

        # Reconstruct URL with masked password
        return urlunparse(parsed._replace(netloc=netloc))

    except Exception:
        # If parsing fails, return original to avoid breaking logging
        return url
