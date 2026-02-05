"""BirdNET-Pi audio migration and spectrogram generation module.

Handles:
- Stage 2: Importing audio files from BirdNET-Pi folder structure
- Stage 3: Generating spectrograms for imported audio files
"""

import os
import re
import shutil
import subprocess
import tempfile
import threading

from config.settings import BASE_DIR, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR
from core.logging_config import get_logger
from core.storage_manager import get_disk_usage
from core.utils import build_detection_filenames, generate_spectrogram

logger = get_logger(__name__)

# Constants
DATA_DIR = os.path.join(BASE_DIR, 'data')
STORAGE_TRIGGER_PERCENT = 85
ESTIMATED_SPECTROGRAM_SIZE_BYTES = 50 * 1024  # ~50KB per spectrogram (conservative estimate)

# Audio file extensions to look for (MP3 only - matches BirdNET-PiPy's default format)
AUDIO_EXTENSIONS = ('.mp3',)

# Folders to exclude from the folder list (system folders)
EXCLUDED_FOLDERS = {'audio', 'spectrograms', 'database', 'logs'}

# Progress tracking
_audio_import_progress = {}
_spectrogram_progress = {}
_progress_lock = threading.Lock()


# =============================================================================
# Progress tracking functions
# =============================================================================

def get_audio_import_progress(import_id):
    """Get current progress for an audio import.

    Args:
        import_id: Unique identifier for the import

    Returns:
        dict: Progress info or None if not found
    """
    with _progress_lock:
        progress = _audio_import_progress.get(import_id)
        return progress.copy() if progress else None


def set_audio_import_progress(import_id, progress):
    """Update progress for an audio import.

    Args:
        import_id: Unique identifier for the import
        progress: dict with progress info
    """
    with _progress_lock:
        _audio_import_progress[import_id] = progress


def clear_audio_import_progress(import_id):
    """Clear progress for a completed audio import.

    Args:
        import_id: Unique identifier for the import
    """
    with _progress_lock:
        _audio_import_progress.pop(import_id, None)


def start_audio_import_if_not_running(import_id, total_files):
    """Atomically check if audio import can start and initialize progress.

    Args:
        import_id: Unique identifier for the import
        total_files: Total number of files to import

    Returns:
        tuple: (can_start: bool, running_id: str or None)
               - (True, None) if import can start
               - (False, existing_id) if another import is already running
    """
    with _progress_lock:
        # Check if ANY audio import is currently running (not just this ID)
        for existing_id, existing in _audio_import_progress.items():
            if existing.get('status') in ('starting', 'running'):
                return False, existing_id

        _audio_import_progress[import_id] = {
            'status': 'starting',
            'processed': 0,
            'total': total_files,
            'imported': 0,
            'skipped': 0,
            'errors': 0
        }
        return True, None


def get_spectrogram_progress(generation_id):
    """Get current progress for spectrogram generation.

    Args:
        generation_id: Unique identifier for the generation

    Returns:
        dict: Progress info or None if not found
    """
    with _progress_lock:
        progress = _spectrogram_progress.get(generation_id)
        return progress.copy() if progress else None


def set_spectrogram_progress(generation_id, progress):
    """Update progress for spectrogram generation.

    Args:
        generation_id: Unique identifier for the generation
        progress: dict with progress info
    """
    with _progress_lock:
        _spectrogram_progress[generation_id] = progress


def clear_spectrogram_progress(generation_id):
    """Clear progress for completed spectrogram generation.

    Args:
        generation_id: Unique identifier for the generation
    """
    with _progress_lock:
        _spectrogram_progress.pop(generation_id, None)


def start_spectrogram_generation_if_not_running(generation_id, total_files):
    """Atomically check if spectrogram generation can start and initialize progress.

    Args:
        generation_id: Unique identifier for the generation
        total_files: Total number of spectrograms to generate

    Returns:
        tuple: (can_start: bool, running_id: str or None)
               - (True, None) if generation can start
               - (False, existing_id) if another generation is already running
    """
    with _progress_lock:
        # Check if ANY spectrogram generation is currently running (not just this ID)
        for existing_id, existing in _spectrogram_progress.items():
            if existing.get('status') in ('starting', 'running'):
                return False, existing_id

        _spectrogram_progress[generation_id] = {
            'status': 'starting',
            'processed': 0,
            'total': total_files,
            'generated': 0,
            'errors': 0
        }
        return True, None


# =============================================================================
# Folder Discovery Functions
# =============================================================================

def list_available_folders():
    """List folders in the data directory that could contain audio files.

    Returns folders that:
    - Are not in the excluded list (system folders)
    - Contain at least one audio file (recursively)

    Returns:
        list: List of dicts with 'name', 'path', and 'audio_count'
    """
    folders = []

    if not os.path.exists(DATA_DIR):
        return folders

    for item in os.listdir(DATA_DIR):
        item_path = os.path.join(DATA_DIR, item)

        # Skip files and excluded folders
        if not os.path.isdir(item_path):
            continue
        if item.lower() in EXCLUDED_FOLDERS:
            continue

        # Count audio files in this folder (recursively)
        audio_count = 0
        for _root, _dirs, files in os.walk(item_path):
            for filename in files:
                if filename.lower().endswith(AUDIO_EXTENSIONS):
                    audio_count += 1

        # Only include folders that have audio files
        if audio_count > 0:
            folders.append({
                'name': item,
                'path': item,  # Relative to data folder
                'audio_count': audio_count
            })

    # Sort by name
    folders.sort(key=lambda x: x['name'].lower())

    logger.info("Listed available audio folders", extra={
        'folder_count': len(folders)
    })

    return folders


def get_full_source_path(relative_path):
    """Convert a relative folder path to full path.

    Args:
        relative_path: Path relative to the data directory

    Returns:
        str: Full path to the folder
    """
    if not relative_path:
        return None

    # Sanitize path to prevent directory traversal
    safe_path = os.path.normpath(relative_path)
    if safe_path.startswith('..') or safe_path.startswith('/'):
        return None

    return os.path.join(DATA_DIR, safe_path)


# =============================================================================
# Stage 2: Audio Import Functions
# =============================================================================

def build_source_file_index(source_dir):
    """Recursively find all audio files and build lookup index.

    Args:
        source_dir: Root directory to search

    Returns:
        dict: {basename_lower: full_path} for all audio files
    """
    index = {}
    if not os.path.exists(source_dir):
        return index

    for root, _dirs, files in os.walk(source_dir):
        for filename in files:
            if filename.lower().endswith(AUDIO_EXTENSIONS):
                # Key by basename (case-insensitive) for matching
                index[filename.lower()] = os.path.join(root, filename)

    return index


def scan_audio_files(db_manager, source_folder=None):
    """Scan source folder and match files against detections with original_file_name.

    Recursively walks the source folder to find all audio files.
    Builds filename index, then matches against original_file_name in DB records.

    Args:
        db_manager: DatabaseManager instance
        source_folder: Relative path to folder within data directory (optional)

    Returns:
        dict: {
            'matched_files': [(detection_id, source_path, size_bytes), ...],
            'total_records': int,
            'matched_count': int,
            'unmatched_count': int,
            'total_size_bytes': int,
            'source_exists': bool,
            'source_folder': str
        }
    """
    # Determine source path
    if source_folder:
        source_path = get_full_source_path(source_folder)
        if not source_path:
            logger.warning("Invalid source folder path", extra={'path': source_folder})
            return {
                'matched_files': [],
                'total_records': 0,
                'matched_count': 0,
                'unmatched_count': 0,
                'total_size_bytes': 0,
                'source_exists': False,
                'source_folder': source_folder
            }
    else:
        source_path = DATA_DIR
        source_folder = ''

    result = {
        'matched_files': [],
        'total_records': 0,
        'matched_count': 0,
        'unmatched_count': 0,
        'total_size_bytes': 0,
        'source_exists': os.path.exists(source_path),
        'source_folder': source_folder
    }

    if not result['source_exists']:
        logger.info("Audio source directory does not exist", extra={
            'path': source_path
        })
        return result

    # Build index of all audio files in source directory
    file_index = build_source_file_index(source_path)
    logger.info("Built source file index", extra={
        'file_count': len(file_index),
        'source_path': source_path
    })

    # Get detections with original_file_name
    detections = db_manager.get_detections_with_original_filename()
    result['total_records'] = len(detections)

    for detection in detections:
        original_name = detection['original_file_name']
        if not original_name:
            result['unmatched_count'] += 1
            continue

        # Get just the basename for matching
        basename = os.path.basename(original_name).lower()

        # Try exact match first, then fallback to underscore variant
        # (BirdNET-Pi stores colons in DB but some systems save files with underscores)
        matched_basename = None
        if basename in file_index:
            matched_basename = basename
        elif ':' in basename:
            # Try replacing colons with underscores (common filesystem workaround)
            underscore_variant = basename.replace(':', '_')
            if underscore_variant in file_index:
                matched_basename = underscore_variant

        if matched_basename:
            source_path = file_index[matched_basename]
            try:
                file_size = os.path.getsize(source_path)
                result['matched_files'].append((detection['id'], source_path, file_size))
                result['total_size_bytes'] += file_size
                result['matched_count'] += 1
            except OSError as e:
                logger.warning("Could not get file size", extra={
                    'path': source_path,
                    'error': str(e)
                })
                result['unmatched_count'] += 1
        else:
            result['unmatched_count'] += 1

    logger.info("Audio file scan complete", extra={
        'total_records': result['total_records'],
        'matched': result['matched_count'],
        'unmatched': result['unmatched_count'],
        'total_size_mb': round(result['total_size_bytes'] / (1024 * 1024), 2)
    })

    return result


def check_disk_space(required_bytes):
    """Check if import would exceed 85% disk usage threshold.

    Args:
        required_bytes: Number of bytes that will be written

    Returns:
        dict: {
            'current_percent': float,
            'after_import_percent': float,
            'has_enough_space': bool,
            'available_bytes': int
        }
    """
    usage = get_disk_usage()
    max_allowed = usage['total_bytes'] * (STORAGE_TRIGGER_PERCENT / 100)
    available_before_threshold = max_allowed - usage['used_bytes']
    after_import_bytes = usage['used_bytes'] + required_bytes
    after_import_percent = round((after_import_bytes / usage['total_bytes']) * 100, 1)

    return {
        'current_percent': usage['percent_used'],
        'after_import_percent': after_import_percent,
        'has_enough_space': required_bytes <= available_before_threshold,
        'available_bytes': max(0, int(available_before_threshold))
    }


def import_audio_files(db_manager, matched_files, import_id):
    """Import audio files, renaming to BirdNET-PiPy format.

    Moves files from migration source to EXTRACTED_AUDIO_DIR with proper naming.

    Args:
        db_manager: DatabaseManager instance
        matched_files: List of (detection_id, source_path, size_bytes) tuples
        import_id: Unique identifier for progress tracking
    """
    # Ensure destination directory exists
    os.makedirs(EXTRACTED_AUDIO_DIR, exist_ok=True)

    result = {
        'imported': 0,
        'skipped': 0,
        'errors': 0
    }

    def update_progress(status='running'):
        processed = result['imported'] + result['skipped'] + result['errors']
        set_audio_import_progress(import_id, {
            'status': status,
            'processed': processed,
            'total': len(matched_files),
            'imported': result['imported'],
            'skipped': result['skipped'],
            'errors': result['errors']
        })

    try:
        update_progress('running')

        for detection_id, source_path, _size_bytes in matched_files:
            try:
                # Get detection record
                detection = db_manager.get_detection_by_id(detection_id)
                if not detection:
                    logger.warning("Detection not found", extra={'id': detection_id})
                    result['errors'] += 1
                    update_progress()
                    continue

                # Generate new filename (mp3 only - scan only includes mp3 files)
                filenames = build_detection_filenames(
                    detection['common_name'],
                    detection['confidence'],
                    detection['timestamp'],
                    audio_extension='mp3'
                )

                dest_path = os.path.join(EXTRACTED_AUDIO_DIR, filenames['audio_filename'])

                # Skip if file already exists at destination
                if os.path.exists(dest_path):
                    result['skipped'] += 1
                    update_progress()
                    continue

                # Copy file
                shutil.copy2(source_path, dest_path)
                result['imported'] += 1

                logger.debug("Imported audio file", extra={
                    'source': os.path.basename(source_path),
                    'dest': filenames['audio_filename']
                })

            except Exception as e:
                logger.error("Failed to import audio file", extra={
                    'source': source_path,
                    'error': str(e)
                })
                result['errors'] += 1

            update_progress()

        update_progress('completed')

        logger.info("Audio import completed", extra={
            'imported': result['imported'],
            'skipped': result['skipped'],
            'errors': result['errors']
        })

    except Exception as e:
        logger.error("Audio import failed", extra={'error': str(e)}, exc_info=True)
        set_audio_import_progress(import_id, {
            'status': 'failed',
            'error': str(e),
            'imported': result['imported'],
            'skipped': result['skipped'],
            'errors': result['errors']
        })

    return result


# =============================================================================
# Stage 3: Spectrogram Generation Functions
# =============================================================================

def scan_files_needing_spectrograms():
    """List audio files in EXTRACTED_AUDIO_DIR without matching spectrogram.

    Returns:
        dict: {
            'files_needing': list of audio filenames,
            'count': int,
            'estimated_size_bytes': int,
            'disk_usage': dict from check_disk_space
        }
    """
    files_needing = []

    if not os.path.exists(EXTRACTED_AUDIO_DIR):
        return {
            'files_needing': [],
            'count': 0,
            'estimated_size_bytes': 0,
            'disk_usage': check_disk_space(0)
        }

    # Get all audio files
    for filename in os.listdir(EXTRACTED_AUDIO_DIR):
        if not filename.lower().endswith(AUDIO_EXTENSIONS):
            continue

        # Check if spectrogram exists
        # Convert audio filename to spectrogram filename
        base_name = os.path.splitext(filename)[0]
        spectrogram_name = f"{base_name}.webp"
        spectrogram_path = os.path.join(SPECTROGRAM_DIR, spectrogram_name)

        if not os.path.exists(spectrogram_path):
            files_needing.append(filename)

    estimated_size = len(files_needing) * ESTIMATED_SPECTROGRAM_SIZE_BYTES
    disk_usage = check_disk_space(estimated_size)

    logger.info("Scanned for files needing spectrograms", extra={
        'count': len(files_needing),
        'estimated_size_mb': round(estimated_size / (1024 * 1024), 2)
    })

    return {
        'files_needing': files_needing,
        'count': len(files_needing),
        'estimated_size_bytes': estimated_size,
        'disk_usage': disk_usage
    }


def _convert_to_wav_if_needed(audio_path):
    """Convert non-WAV audio to temporary WAV file for spectrogram generation.

    Args:
        audio_path: Path to the audio file

    Returns:
        tuple: (wav_path, is_temp) - wav_path is either original or temp file,
               is_temp indicates if it should be deleted after use
    """
    if audio_path.lower().endswith('.wav'):
        return audio_path, False

    # Create temp WAV file
    temp_wav = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    temp_wav.close()

    try:
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error',
            '-i', audio_path,
            '-ar', '48000',  # Match BirdNET sample rate
            '-ac', '1',  # Mono
            temp_wav.name
        ], check=True, timeout=60)
        return temp_wav.name, True
    except Exception as e:
        # Clean up temp file on error
        if os.path.exists(temp_wav.name):
            os.unlink(temp_wav.name)
        raise e


def _build_spectrogram_title_from_audio_filename(audio_filename: str) -> str:
    """Build spectrogram title matching live detection format.

    Expected filename format (without extension):
        Species_Name_85_2024-01-15-birdnet-10:30:45  (old colon pattern)
        Species_Name_85_2024-01-15-birdnet-10-30-45  (new dash pattern)
    Output title format (always uses colons for readability):
        Species Name (0.85) - 2024-01-15T10:30:45
    """
    base_name = os.path.splitext(audio_filename)[0]

    # Accept both colon (HH:MM:SS) and dash (HH-MM-SS) time patterns
    match = re.match(
        r"^(?P<species>.+)_(?P<confidence>\d{1,3})_(?P<date>\d{4}-\d{2}-\d{2})-birdnet-(?P<time>\d{2}[:\-]\d{2}[:\-]\d{2})$",
        base_name
    )
    if match:
        species = match.group('species').replace('_', ' ')
        confidence = int(match.group('confidence')) / 100.0
        # Normalize time to colons for human-readable title
        time_str = match.group('time').replace('-', ':')
        timestamp = f"{match.group('date')}T{time_str}"
        return f"{species} ({confidence:.2f}) - {timestamp}"

    # Fallback: readable title if filename doesn't match expected format
    return base_name.replace('_', ' ')


def generate_spectrograms_batch(audio_files, generation_id):
    """Generate spectrograms for a batch of audio files.

    Args:
        audio_files: List of audio filenames (in EXTRACTED_AUDIO_DIR)
        generation_id: Unique identifier for progress tracking
    """
    # Ensure destination directory exists
    os.makedirs(SPECTROGRAM_DIR, exist_ok=True)

    result = {
        'generated': 0,
        'errors': 0
    }

    def update_progress(status='running'):
        processed = result['generated'] + result['errors']
        set_spectrogram_progress(generation_id, {
            'status': status,
            'processed': processed,
            'total': len(audio_files),
            'generated': result['generated'],
            'errors': result['errors']
        })

    try:
        update_progress('running')

        for audio_filename in audio_files:
            audio_path = os.path.join(EXTRACTED_AUDIO_DIR, audio_filename)
            temp_wav = None

            try:
                if not os.path.exists(audio_path):
                    logger.warning("Audio file not found", extra={'path': audio_path})
                    result['errors'] += 1
                    update_progress()
                    continue

                # Generate spectrogram filename
                base_name = os.path.splitext(audio_filename)[0]
                spectrogram_filename = f"{base_name}.webp"
                spectrogram_path = os.path.join(SPECTROGRAM_DIR, spectrogram_filename)

                # Skip if already exists
                if os.path.exists(spectrogram_path):
                    result['generated'] += 1  # Count as success
                    update_progress()
                    continue

                # Convert to WAV if needed (generate_spectrogram requires WAV)
                wav_path, is_temp = _convert_to_wav_if_needed(audio_path)
                if is_temp:
                    temp_wav = wav_path

                title = _build_spectrogram_title_from_audio_filename(audio_filename)

                # Generate spectrogram
                generate_spectrogram(wav_path, spectrogram_path, title)
                result['generated'] += 1

                logger.debug("Generated spectrogram", extra={
                    'audio': audio_filename,
                    'spectrogram': spectrogram_filename
                })

            except Exception as e:
                logger.error("Failed to generate spectrogram", extra={
                    'audio': audio_filename,
                    'error': str(e)
                })
                result['errors'] += 1

            finally:
                # Clean up temp WAV file
                if temp_wav and os.path.exists(temp_wav):
                    try:
                        os.unlink(temp_wav)
                    except Exception:
                        pass

            update_progress()

        update_progress('completed')

        logger.info("Spectrogram generation completed", extra={
            'generated': result['generated'],
            'errors': result['errors']
        })

    except Exception as e:
        logger.error("Spectrogram generation failed", extra={'error': str(e)}, exc_info=True)
        set_spectrogram_progress(generation_id, {
            'status': 'failed',
            'error': str(e),
            'generated': result['generated'],
            'errors': result['errors']
        })

    return result
