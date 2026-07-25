"""Bird image endpoints: Wikimedia lookups/choices and custom image uploads.

HTTP shims over core.bird_image_service (fetching, caching, sidecars, file
management). Registered on the shared ``api`` blueprint at import time.
"""
import os

from flask import jsonify, request, send_from_directory

from config.settings import CUSTOM_BIRD_IMAGES_DIR
from core.api_infra import api
from core.api_utils import handle_api_errors
from core.auth import require_auth, require_scope
from core.bird_image_service import (
    ALLOWED_IMAGE_EXTENSIONS,
    MAX_IMAGE_SIZE,
    _delete_choice_sidecar,
    _delete_custom_image,
    _get_custom_image_path,
    _is_wikimedia_url,
    _load_choice_sidecar,
    _sanitize_species_filename,
    _save_choice_sidecar,
    _validate_image_magic_bytes,
    fetch_wikimedia_candidates,
    fetch_wikimedia_image,
)
from core.logging_config import get_logger, log_api_request
from core.timezone_service import local_now

logger = get_logger(__name__)

def _wikimedia_error_response(payload, error):
    """Build (response, status) for a Wikimedia failure, echoing the upstream
    Retry-After on a 429 so the client can back off instead of retrying blind."""
    resp = jsonify(payload)
    if error.get('status') == 429 and error.get('retry_after'):
        resp.headers['Retry-After'] = str(int(error['retry_after']))
    return resp, error.get('status', 502)


@api.route('/api/wikimedia_image', methods=['GET'])
@require_scope('public:read')
def get_wikimedia_image():
    species_name = request.args.get('species', '')
    if not species_name:
        return jsonify({'error': 'Species name is required'}), 400

    custom_path, _ = _get_custom_image_path(species_name)
    has_custom = custom_path is not None

    # Honor saved Wikimedia choice when sidecar is present (skip upstream fetch).
    sidecar = _load_choice_sidecar(species_name)
    if sidecar:
        return jsonify({
            'imageUrl': sidecar['imageUrl'],
            # Legacy sidecars (schemaVersion 1) have no thumbUrl — fall back to
            # the full imageUrl so the gallery still renders, just heavier. New
            # saves carry a thumbUrl; re-saving a legacy choice upgrades it.
            'thumbUrl': sidecar.get('thumbUrl') or sidecar['imageUrl'],
            'pageUrl': sidecar['pageUrl'],
            'authorName': sidecar.get('authorName', 'Unknown Author'),
            'authorUrl': sidecar.get('authorUrl'),
            'licenseType': sidecar.get('licenseType', 'Unknown License'),
            'fileTitle': sidecar.get('fileTitle'),
            'hasCustomImage': has_custom,
            'source': 'sidecar',
        })

    # The gallery passes for_display_only=1: it renders the local custom image
    # when one exists and ignores the Wikimedia metadata, so skip the upstream
    # lookup for custom-upload species (a sidecar would have returned above).
    # BirdDetails omits the flag because it still wants the revert-fallback data.
    display_only = request.args.get('for_display_only', '').lower() in ('1', 'true', 'yes')
    if display_only and has_custom:
        return jsonify({'hasCustomImage': True}), 200

    image_data, error = fetch_wikimedia_image(species_name)

    if error:
        if has_custom:
            return jsonify({'hasCustomImage': True}), 200
        return _wikimedia_error_response({'error': error['message']}, error)

    image_data['hasCustomImage'] = has_custom
    image_data['source'] = 'wikimedia-search'

    logger.debug("Wikimedia image fetched", extra={
        'species': species_name,
        'has_image': bool(image_data),
        'has_custom_image': has_custom
    })
    return jsonify(image_data)


@api.route('/api/wikimedia_image/candidates', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_wikimedia_image_candidates():
    """Return up to `limit` Wikimedia candidates plus the user's currently-saved choice."""
    species_name = request.args.get('species', '').strip()
    if not species_name:
        return jsonify({'error': 'Species name is required'}), 400

    try:
        limit = int(request.args.get('limit', 8))
    except (TypeError, ValueError):
        return jsonify({'error': 'limit must be an integer'}), 400
    limit = max(1, min(limit, 20))

    candidates, error = fetch_wikimedia_candidates(species_name, limit=limit)

    custom_path, _ = _get_custom_image_path(species_name)
    has_custom = custom_path is not None
    sidecar = _load_choice_sidecar(species_name)
    selected_file_title = sidecar.get('fileTitle') if sidecar else None

    payload = {
        'species': species_name,
        'candidates': candidates,
        'selectedFileTitle': selected_file_title,
        'hasCustomImage': has_custom,
    }
    if error and not candidates:
        payload['error'] = error['message']
        return _wikimedia_error_response(payload, error)
    return jsonify(payload)


@api.route('/api/bird/<species_name>/wikimedia_choice', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_wikimedia_choice(species_name):
    sidecar = _load_choice_sidecar(species_name)
    if sidecar is None:
        return jsonify({'error': 'No saved choice', 'hasChoice': False}), 404
    return jsonify(sidecar)


@api.route('/api/bird/<species_name>/wikimedia_choice', methods=['PUT'])
@log_api_request
@require_auth
@handle_api_errors
def put_wikimedia_choice(species_name):
    payload = request.get_json(silent=True) or {}
    required = ('fileTitle', 'imageUrl', 'pageUrl', 'authorName', 'licenseType')
    missing = [k for k in required if not payload.get(k)]
    if missing:
        return jsonify({'error': f'Missing keys: {", ".join(missing)}'}), 400

    if not _is_wikimedia_url(payload['imageUrl']) or not _is_wikimedia_url(payload['pageUrl']):
        return jsonify({'error': 'imageUrl and pageUrl must be wikimedia.org https URLs'}), 400

    author_url = payload.get('authorUrl')
    if author_url is not None and not isinstance(author_url, str):
        return jsonify({'error': 'authorUrl must be a string or null'}), 400

    # thumbUrl is optional (older clients omit it). Validate it when present;
    # otherwise store the full imageUrl so the sidecar always has a usable
    # thumbnail field for the gallery to display.
    thumb_url = payload.get('thumbUrl')
    if thumb_url is not None and (not isinstance(thumb_url, str) or not _is_wikimedia_url(thumb_url)):
        return jsonify({'error': 'thumbUrl must be a wikimedia.org https URL'}), 400

    sidecar = {
        'schemaVersion': 2,
        'source': 'wikimedia',
        'fileTitle': payload['fileTitle'],
        'imageUrl': payload['imageUrl'],
        'thumbUrl': thumb_url or payload['imageUrl'],
        'pageUrl': payload['pageUrl'],
        'authorName': payload['authorName'],
        'authorUrl': author_url,
        'licenseType': payload['licenseType'],
        'savedAt': local_now().isoformat(),
    }
    _save_choice_sidecar(species_name, sidecar)
    logger.info("Wikimedia choice saved", extra={
        'species': species_name, 'fileTitle': payload['fileTitle']
    })
    return jsonify(sidecar)


@api.route('/api/bird/<species_name>/wikimedia_choice', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def delete_wikimedia_choice(species_name):
    """Idempotently remove a saved Wikimedia choice."""
    _delete_choice_sidecar(species_name)
    logger.info("Wikimedia choice deleted", extra={'species': species_name})
    return jsonify({'hasChoice': False})


@api.route('/api/bird/<species_name>/image', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def upload_bird_image(species_name):
    """Upload a custom image for a bird species."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400

    # Validate extension
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return jsonify({'error': f'Invalid file type. Allowed: {", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))}'}), 400

    # Validate file size
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_IMAGE_SIZE:
        return jsonify({'error': f'File too large. Maximum size is {MAX_IMAGE_SIZE // (1024 * 1024)}MB'}), 400

    if size == 0:
        return jsonify({'error': 'File is empty'}), 400

    # Validate magic bytes
    if not _validate_image_magic_bytes(file):
        return jsonify({'error': 'File does not appear to be a valid image'}), 400

    os.makedirs(CUSTOM_BIRD_IMAGES_DIR, exist_ok=True)
    _delete_custom_image(species_name)
    final_path = os.path.join(CUSTOM_BIRD_IMAGES_DIR, _sanitize_species_filename(species_name) + ext)
    file.save(final_path)

    logger.info("Custom bird image uploaded", extra={'species': species_name})
    return jsonify({'hasCustomImage': True})


@api.route('/api/bird/<species_name>/image', methods=['GET'])
@require_scope('public:read')
def serve_bird_image(species_name):
    """Serve a custom bird image."""
    _, filename = _get_custom_image_path(species_name)
    if filename:
        return send_from_directory(CUSTOM_BIRD_IMAGES_DIR, filename)
    return jsonify({'error': 'No custom image found'}), 404


@api.route('/api/bird/<species_name>/image', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def delete_bird_image(species_name):
    """Delete a custom bird image. Idempotent - always returns 200."""
    _delete_custom_image(species_name)
    logger.info("Custom bird image deleted", extra={'species': species_name})
    return jsonify({'hasCustomImage': False})
