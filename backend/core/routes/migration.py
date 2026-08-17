"""BirdNET-Pi migration endpoints: DB import, audio import, spectrogram backfill.

Three long-running owner-only flows, each with upload/scan -> background thread
-> progress-poll -> skip/cancel endpoints. Registered on the shared ``api``
blueprint at import time (see core/routes/__init__.py).
"""
import os
import threading
import uuid

from flask import jsonify, request, session

from config.settings import BASE_DIR
from core import api_infra as infra
from core.api_infra import api
from core.api_utils import handle_api_errors
from core.auth import require_auth
from core.logging_config import get_logger, log_api_request
from core.migration import (
    BirdNETPiMigrator,
    clear_migration_progress,
    get_migration_progress,
    set_migration_progress,
    start_migration_if_not_running,
)
from core.migration_audio import (
    check_disk_space,
    clear_audio_import_progress,
    clear_spectrogram_progress,
    generate_spectrograms_batch,
    get_audio_import_progress,
    get_spectrogram_progress,
    import_audio_files,
    list_available_folders,
    scan_audio_files,
    scan_files_needing_spectrograms,
    start_audio_import_if_not_running,
    start_spectrogram_generation_if_not_running,
)

logger = get_logger(__name__)


def _cooperative_yield():
    """Late-bound: the socketio global lives in core.api (set by create_app)."""
    from core.api import _cooperative_yield as cooperative_yield
    cooperative_yield()


# =============================================================================
# Migration Endpoints (BirdNET-Pi import)
# =============================================================================

# Directory for storing temporary migration files
MIGRATION_TEMP_DIR = os.path.join(BASE_DIR, 'data', 'temp', 'migration')

def cleanup_migration_temp_dir():
    """Remove orphaned migration temp files from previous sessions."""
    if not os.path.isdir(MIGRATION_TEMP_DIR):
        return 0

    removed = 0
    for filename in os.listdir(MIGRATION_TEMP_DIR):
        if not (filename.startswith('migration_') and filename.endswith('.db')):
            continue
        file_path = os.path.join(MIGRATION_TEMP_DIR, filename)
        if not os.path.isfile(file_path):
            continue
        try:
            os.remove(file_path)
            removed += 1
        except Exception as e:
            logger.warning("Failed to remove migration temp file", extra={
                'path': file_path,
                'error': str(e)
            })

    if removed:
        logger.info("Cleaned orphaned migration temp files", extra={
            'removed': removed
        })
    return removed


def get_migration_temp_path():
    """Get temp file path from session, if it exists and is valid."""
    temp_path = session.get('migration_temp_path')
    if temp_path and os.path.exists(temp_path):
        return temp_path
    return None


def cleanup_migration_temp():
    """Remove temp file and clear session."""
    temp_path = session.pop('migration_temp_path', None)
    if temp_path and os.path.exists(temp_path):
        try:
            os.remove(temp_path)
            logger.debug("Migration temp file cleaned up", extra={'path': temp_path})
        except Exception as e:
            logger.warning("Failed to cleanup migration temp file", extra={
                'path': temp_path,
                'error': str(e)
            })


@api.route('/api/migration/validate', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_validate():
    """Upload and validate a BirdNET-Pi database file.

    Accepts multipart/form-data with a 'file' field containing the birds.db file.

    Returns:
        JSON with validation result, record count, duplicate count, and preview records
    """
    # Check if file was uploaded
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Validate file extension
    if not file.filename.endswith('.db'):
        return jsonify({'error': 'File must be a .db SQLite database file'}), 400

    # Clean up any previous temp file
    cleanup_migration_temp()

    # Create temp directory if needed
    os.makedirs(MIGRATION_TEMP_DIR, exist_ok=True)

    # Save to temp file with unique name
    temp_filename = f"migration_{uuid.uuid4().hex}.db"
    temp_path = os.path.join(MIGRATION_TEMP_DIR, temp_filename)

    try:
        # Chunked copy instead of file.save(): save() is a disk->disk copy of
        # the whole DB (hundreds of MB on a Pi SD card) and disk I/O is not
        # gevent-patched, so yield between chunks to keep the single gevent
        # worker responsive.
        chunk_size = 1024 * 1024
        with open(temp_path, 'wb') as dst:
            while True:
                chunk = file.stream.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk)
                _cooperative_yield()
        logger.info("Migration file uploaded", extra={
            'original_filename': file.filename,
            'temp_path': temp_path
        })

        # Validate the database
        migrator = BirdNETPiMigrator(infra.db_manager)
        validation = migrator.validate_source_database(temp_path)

        if not validation['valid']:
            # Clean up invalid file
            os.remove(temp_path)
            return jsonify({
                'valid': False,
                'error': validation['error']
            }), 400

        # Get preview (skip duplicate counting - too slow for large databases)
        preview = migrator.get_preview(temp_path, limit=10)

        # Store temp path and record count in session for import step
        session['migration_temp_path'] = temp_path
        session['migration_total_records'] = validation['record_count']

        return jsonify({
            'valid': True,
            'record_count': validation['record_count'],
            'preview': preview
        }), 200

    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        logger.error("Migration validation error", extra={'error': str(e)}, exc_info=True)
        return jsonify({'error': f'Failed to validate database: {str(e)}'}), 500


def _run_migration_background(temp_path, total_records, skip_duplicates):
    """Run migration in background thread.

    Args:
        temp_path: Path to the validated source database (used as migration ID)
        total_records: Total number of records to import
        skip_duplicates: Whether to skip duplicate records
    """
    try:
        migrator = BirdNETPiMigrator(infra.db_manager)
        result = migrator.migrate(
            temp_path,
            skip_duplicates=skip_duplicates,
            temp_path=temp_path,
            total_records=total_records,
            yield_control=_cooperative_yield
        )

        logger.info("Migration import completed", extra={
            'migration_id': temp_path,
            'imported': result['imported'],
            'skipped': result['skipped'],
            'errors': result['errors']
        })

        if result.get('imported', 0) > 0:
            from core.routes.observations import (
                invalidate_dashboard_cache,
                invalidate_gallery_cache,
            )
            invalidate_dashboard_cache()
            invalidate_gallery_cache()

    except Exception as e:
        logger.error("Migration import error", extra={
            'migration_id': temp_path,
            'error': str(e)
        }, exc_info=True)
        set_migration_progress(temp_path, {
            'status': 'failed',
            'error': str(e)
        })

    finally:
        # Clean up temp file after migration completes
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug("Migration temp file cleaned up", extra={'path': temp_path})
            except Exception as e:
                logger.warning("Failed to cleanup migration temp file", extra={
                    'path': temp_path,
                    'error': str(e)
                })

        # Clear progress tracking after a delay to allow final status poll
        def cleanup_progress():
            import time
            time.sleep(300)  # Keep progress available for 5 minutes
            clear_migration_progress(temp_path)
            logger.debug("Migration progress cleared", extra={'migration_id': temp_path})

        cleanup_thread = threading.Thread(target=cleanup_progress, daemon=True)
        cleanup_thread.start()


@api.route('/api/migration/import', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_import():
    """Start importing records from a previously validated BirdNET-Pi database.

    The import runs in the background. Use /api/migration/status to check progress.

    Request body (optional):
        {
            "skip_duplicates": true  // default: true
        }

    Returns:
        JSON with status: started and migration_id for tracking
    """
    # Get temp file from session
    temp_path = get_migration_temp_path()
    if not temp_path:
        return jsonify({'error': 'No validated file found. Please upload and validate first.'}), 400

    total_records = session.get('migration_total_records', 0)

    # Get options from request (handle missing or non-JSON body)
    data = {}
    if request.is_json:
        data = request.json or {}
    skip_duplicates = data.get('skip_duplicates', True)

    # Clear session early - we either start the migration or it's already running
    # This prevents cancel from interfering with a running migration
    session.pop('migration_temp_path', None)
    session.pop('migration_total_records', None)

    # Atomically check if we can start and initialize progress
    # This prevents race conditions with duplicate requests
    # temp_path is used as the migration_id (unique per upload via uuid)
    can_start, running_id = start_migration_if_not_running(temp_path, total_records)

    if not can_start:
        # Already running - return the ID of the running job so client can poll
        return jsonify({
            'status': 'already_running',
            'migration_id': running_id,
            'message': 'Database migration is already in progress'
        }), 200

    # Start background thread
    thread = threading.Thread(
        target=_run_migration_background,
        args=(temp_path, total_records, skip_duplicates),
        daemon=True
    )
    thread.start()

    logger.info("Migration import started in background", extra={
        'migration_id': temp_path,
        'total_records': total_records
    })

    return jsonify({
        'status': 'started',
        'migration_id': temp_path,
        'total_records': total_records
    }), 200


@api.route('/api/migration/status', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def migration_status():
    """Get the current status of a running migration.

    Query params:
        migration_id: The migration ID returned from /api/migration/import

    Returns:
        JSON with current progress (status, processed, total, imported, skipped, errors)
    """
    migration_id = request.args.get('migration_id')
    if not migration_id:
        return jsonify({'error': 'migration_id parameter required'}), 400

    progress = get_migration_progress(migration_id)
    if not progress:
        return jsonify({
            'status': 'not_found',
            'message': 'No migration found with this ID'
        }), 404

    return jsonify(progress), 200


@api.route('/api/migration/cancel', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_cancel():
    """Cancel migration and clean up.

    Call this if user cancels after validation but before import.
    Note: Cannot stop a running import (it will complete in background),
    but this will clean up the temp file if called.
    """
    temp_path = get_migration_temp_path()

    if temp_path:
        # Clear any progress tracking (keyed by temp_path)
        clear_migration_progress(temp_path)
        cleanup_migration_temp()
        logger.info("Migration cancelled and temp file cleaned up")
        return jsonify({'status': 'cancelled', 'message': 'Migration cancelled'}), 200
    else:
        return jsonify({'status': 'ok', 'message': 'No migration in progress'}), 200


# =============================================================================
# Migration Stage 2: Audio Import Endpoints
# =============================================================================

@api.route('/api/migration/audio/folders', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_folders():
    """List available folders that contain audio files.

    Returns folders in the data directory that contain audio files
    and are not system folders.

    Returns:
        JSON with list of available folders
    """
    folders = list_available_folders()
    return jsonify({'folders': folders}), 200


@api.route('/api/migration/audio/scan', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_scan():
    """Scan source folder for matching audio files.

    Request body:
        source_folder: Relative path to folder within data directory (required)

    Returns:
        JSON with matched files count, unmatched count, total size, and disk space info
    """
    data = request.get_json() or {}
    source_folder = data.get('source_folder')

    if not source_folder:
        return jsonify({
            'error': 'Missing source_folder parameter',
            'hint': 'Please select a folder containing your BirdNET-Pi audio files.'
        }), 400

    scan_result = scan_audio_files(infra.db_manager, source_folder)

    # Check disk space if we have matched files
    disk_check = check_disk_space(scan_result['total_size_bytes'])

    return jsonify({
        'source_folder': scan_result.get('source_folder', ''),
        'source_exists': scan_result['source_exists'],
        'total_records': scan_result['total_records'],
        'matched_count': scan_result['matched_count'],
        'unmatched_count': scan_result['unmatched_count'],
        'total_size_bytes': scan_result['total_size_bytes'],
        'disk_usage': disk_check
    }), 200


@api.route('/api/migration/audio/import', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_import():
    """Start importing matched audio files.

    Request body:
        source_folder: Relative path to folder within data directory (required)

    The import runs in the background. Use /api/migration/audio/status to check progress.

    Returns:
        JSON with status: started and import_id for tracking
    """
    data = request.get_json() or {}
    source_folder = data.get('source_folder')

    if not source_folder:
        return jsonify({
            'error': 'Missing source_folder parameter',
            'hint': 'Please select a folder containing your BirdNET-Pi audio files.'
        }), 400

    # Re-scan to get matched files (ensures fresh data)
    scan_result = scan_audio_files(infra.db_manager, source_folder)

    if not scan_result['matched_files']:
        return jsonify({
            'error': 'No matching audio files found in the selected folder.',
            'hint': 'Make sure the folder contains audio files that match your imported database records.'
        }), 400

    # Check disk space
    disk_check = check_disk_space(scan_result['total_size_bytes'])
    if not disk_check['has_enough_space']:
        return jsonify({
            'error': 'Not enough disk space to import these files.',
            'hint': 'Free up some space or import fewer files.',
            'required_bytes': scan_result['total_size_bytes'],
            'available_bytes': disk_check['available_bytes']
        }), 400

    # Generate unique import ID
    import_id = f"audio_import_{uuid.uuid4().hex}"
    total_files = len(scan_result['matched_files'])

    # Atomically check if we can start
    can_start, running_id = start_audio_import_if_not_running(import_id, total_files)
    if not can_start:
        return jsonify({
            'status': 'already_running',
            'import_id': running_id,  # Return the ID of the running job
            'message': 'Audio import is already in progress'
        }), 200

    # Start background thread
    def run_import():
        try:
            import_audio_files(infra.db_manager, scan_result['matched_files'], import_id,
                                yield_control=_cooperative_yield)
        finally:
            # Clear progress tracking after a delay
            def cleanup_progress():
                import time
                time.sleep(300)  # Keep progress available for 5 minutes
                clear_audio_import_progress(import_id)
                logger.debug("Audio import progress cleared", extra={'import_id': import_id})

            cleanup_thread = threading.Thread(target=cleanup_progress, daemon=True)
            cleanup_thread.start()

    thread = threading.Thread(target=run_import, daemon=True)
    thread.start()

    logger.info("Audio import started in background", extra={
        'import_id': import_id,
        'total_files': total_files
    })

    return jsonify({
        'status': 'started',
        'import_id': import_id,
        'total_files': total_files
    }), 200


@api.route('/api/migration/audio/status', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_status():
    """Get the current status of an audio import.

    Query params:
        import_id: The import ID returned from /api/migration/audio/import

    Returns:
        JSON with current progress (status, processed, total, imported, skipped, errors)
    """
    import_id = request.args.get('import_id')
    if not import_id:
        return jsonify({'error': 'import_id parameter required'}), 400

    progress = get_audio_import_progress(import_id)
    if not progress:
        return jsonify({
            'status': 'not_found',
            'message': 'No audio import found with this ID'
        }), 404

    return jsonify(progress), 200


@api.route('/api/migration/audio/skip', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_audio_skip():
    """Skip the audio import stage.

    Returns:
        JSON with status: skipped
    """
    logger.info("Audio import stage skipped")
    return jsonify({'status': 'skipped', 'message': 'Audio import skipped'}), 200


# =============================================================================
# Migration Stage 3: Spectrogram Generation Endpoints
# =============================================================================

@api.route('/api/migration/spectrogram/scan', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_spectrogram_scan():
    """Scan for audio files needing spectrograms.

    Checks EXTRACTED_AUDIO_DIR for audio files without matching spectrograms.

    Returns:
        JSON with count of files needing spectrograms and estimated size
    """
    scan_result = scan_files_needing_spectrograms()

    return jsonify({
        'count': scan_result['count'],
        'estimated_size_bytes': scan_result['estimated_size_bytes'],
        'disk_usage': scan_result['disk_usage']
    }), 200


@api.route('/api/migration/spectrogram/generate', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_spectrogram_generate():
    """Start generating spectrograms for audio files.

    Must call /api/migration/spectrogram/scan first.
    The generation runs in the background. Use /api/migration/spectrogram/status to check progress.

    Returns:
        JSON with status: started and generation_id for tracking
    """
    # Scan for files needing spectrograms
    scan_result = scan_files_needing_spectrograms()

    if not scan_result['files_needing']:
        return jsonify({
            'status': 'no_files',
            'message': 'No files need spectrograms'
        }), 200

    # Check disk space
    if not scan_result['disk_usage']['has_enough_space']:
        return jsonify({
            'error': 'Insufficient disk space',
            'required_bytes': scan_result['estimated_size_bytes'],
            'available_bytes': scan_result['disk_usage']['available_bytes']
        }), 400

    # Generate unique generation ID
    generation_id = f"spectrogram_gen_{uuid.uuid4().hex}"
    total_files = scan_result['count']

    # Atomically check if we can start
    can_start, running_id = start_spectrogram_generation_if_not_running(generation_id, total_files)
    if not can_start:
        return jsonify({
            'status': 'already_running',
            'generation_id': running_id,  # Return the ID of the running job
            'message': 'Spectrogram generation is already in progress'
        }), 200

    # Start background thread
    def run_generation():
        try:
            generate_spectrograms_batch(scan_result['files_needing'], generation_id,
                                        yield_control=_cooperative_yield,
                                        db_manager=infra.db_manager)
        finally:
            # Clear progress tracking after a delay
            def cleanup_progress():
                import time
                time.sleep(300)  # Keep progress available for 5 minutes
                clear_spectrogram_progress(generation_id)
                logger.debug("Spectrogram progress cleared", extra={'generation_id': generation_id})

            cleanup_thread = threading.Thread(target=cleanup_progress, daemon=True)
            cleanup_thread.start()

    thread = threading.Thread(target=run_generation, daemon=True)
    thread.start()

    logger.info("Spectrogram generation started in background", extra={
        'generation_id': generation_id,
        'total_files': total_files
    })

    return jsonify({
        'status': 'started',
        'generation_id': generation_id,
        'total_files': total_files
    }), 200


@api.route('/api/migration/spectrogram/status', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def migration_spectrogram_status():
    """Get the current status of spectrogram generation.

    Query params:
        generation_id: The generation ID returned from /api/migration/spectrogram/generate

    Returns:
        JSON with current progress (status, processed, total, generated, errors)
    """
    generation_id = request.args.get('generation_id')
    if not generation_id:
        return jsonify({'error': 'generation_id parameter required'}), 400

    progress = get_spectrogram_progress(generation_id)
    if not progress:
        return jsonify({
            'status': 'not_found',
            'message': 'No spectrogram generation found with this ID'
        }), 404

    return jsonify(progress), 200


@api.route('/api/migration/spectrogram/skip', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def migration_spectrogram_skip():
    """Skip the spectrogram generation stage.

    Returns:
        JSON with status: skipped
    """
    logger.info("Spectrogram generation stage skipped")
    return jsonify({'status': 'skipped', 'message': 'Spectrogram generation skipped'}), 200
