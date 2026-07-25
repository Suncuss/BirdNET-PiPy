"""Detection endpoints: table/trends reads, CSV export, deletes.

The streaming CSV export batches DB reads so a million-row export stays a
sequence of quick executor jobs; deletes invalidate the dashboard/gallery
caches they falsify. Registered on the shared ``api`` blueprint at import.
"""
import csv
import io
from datetime import datetime

from flask import Response, jsonify, request

from core import api_infra as infra
from core.api_infra import _run_db, api
from core.api_utils import (
    _resolve_species_filter,
    handle_api_errors,
    log_data_metrics,
)
from core.auth import get_request_tier, require_auth, require_feature
from core.bird_name_utils import DEFAULT_BIRD_NAME_LANGUAGE, get_bird_name_language
from core.detection_presenter import (
    _localize_detection_list,
    _localized_species_order,
    _public_window_cutoff_date,
)
from core.logging_config import get_logger, log_api_request
from core.routes.observations import (
    invalidate_dashboard_cache,
    invalidate_gallery_cache,
)
from core.settings_store import load_user_settings
from core.storage_manager import delete_detection_files
from core.timezone_service import local_now

logger = get_logger(__name__)


def _cooperative_yield():
    """Late-bound: the socketio global lives in core.api (set by create_app)."""
    from core.api import _cooperative_yield as cooperative_yield
    cooperative_yield()


# Rows per DB batch for the streaming CSV export: small enough that a batch
# is a quick lane job holding ~1MB, large enough that a million-row export
# stays a few thousand round trips rather than a million.
_EXPORT_BATCH_ROWS = 1000



@api.route('/api/detections/trends', methods=['GET'])
@log_api_request
@require_feature('charts')
@handle_api_errors
def get_detection_trends():
    """Get daily detection counts for trend visualization.

    Query params:
    - start_date: Start date (YYYY-MM-DD) - required
    - end_date: End date (YYYY-MM-DD) - required

    Returns:
        JSON: {'labels': ['2024-01-01', ...], 'data': [count, ...]}
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Validate required parameters
    if not start_date or not end_date:
        return jsonify({'error': 'Both start_date and end_date are required'}), 400

    # Validate date formats
    for date_param, date_value in [('start_date', start_date), ('end_date', end_date)]:
        try:
            datetime.strptime(date_value, '%Y-%m-%d')
        except ValueError:
            return jsonify({'error': f'Invalid {date_param} format. Use YYYY-MM-DD'}), 400

    # Validate date order
    if start_date > end_date:
        return jsonify({'error': 'start_date must be before or equal to end_date'}), 400

    trends = _run_db(infra.db_manager.get_daily_detection_counts, start_date, end_date)

    log_data_metrics('get_detection_trends', trends, {
        'start_date': start_date,
        'end_date': end_date,
        'days': len(trends.get('labels', []))
    })

    return jsonify(trends)


@api.route('/api/detections', methods=['GET'])
@log_api_request
@require_feature('table')
@handle_api_errors
def get_detections():
    """Get paginated bird detections with optional filtering.

    Query params:
    - page: Page number, 1-indexed (default: 1)
    - per_page: Results per page, max 100 (default: 25)
    - start_date: Start date filter (YYYY-MM-DD)
    - end_date: End date filter (YYYY-MM-DD)
    - species: Filter by common_name
    - hour: Filter by hour of day, integer 0-23
    - sort: Sort field - timestamp, confidence, common_name (default: timestamp)
    - order: Sort order - asc, desc (default: desc)
    """
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get('per_page', default=25, type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    species = request.args.get('species')
    sort = request.args.get('sort', default='timestamp')
    order = request.args.get('order', default='desc')

    # Validate date formats if provided
    for date_param, date_value in [('start_date', start_date), ('end_date', end_date)]:
        if date_value:
            try:
                datetime.strptime(date_value, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': f'Invalid {date_param} format. Use YYYY-MM-DD'}), 400

    # Validate hour filter if provided (parsed manually so a non-integer
    # value is a hard 400 rather than being silently dropped).
    hour = None
    hour_raw = request.args.get('hour')
    if hour_raw not in (None, ''):
        try:
            hour = int(hour_raw)
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid hour. Use an integer 0-23'}), 400
        if not 0 <= hour <= 23:
            return jsonify({'error': 'Invalid hour. Use an integer 0-23'}), 400

    # Cap per_page at 100 (same as db method)
    per_page = min(max(1, per_page), 100)

    # Anonymous callers (when the owner has published the table) see only the
    # recent window — consistent with the rest of the public view, so table_public
    # can't expose the full historical archive and every visible row's media stays
    # playable (its signature is minted). Owners see the full table. Applies to
    # both query paths below.
    if get_request_tier() == 'public':
        cutoff_date = _public_window_cutoff_date()
        if not start_date or start_date < cutoff_date:
            start_date = cutoff_date

    settings = load_user_settings()
    bird_name_language = get_bird_name_language(settings)
    sci, common = _resolve_species_filter(species)

    if sort == 'common_name' and bird_name_language != DEFAULT_BIRD_NAME_LANGUAGE:
        # Localized labels don't follow database ordering, so order the
        # distinct species by display name here (a few hundred keys) and let
        # SQL assemble just the requested page from that order — materializing
        # every matching row for an in-memory sort OOMs small devices once
        # the table reaches hundreds of thousands of rows. The species list
        # is unfiltered on purpose: the page query below applies the filters,
        # and species outside them just yield empty buckets.
        ordered_species = _localized_species_order(
            _run_db(infra.db_manager.get_distinct_species_pairs),
            settings,
            descending=order.lower() != 'asc',
        )
        detections, total_count = _run_db(
            infra.db_manager.get_paginated_detections_localized,
            ordered_species,
            page=page,
            per_page=per_page,
            start_date=start_date,
            end_date=end_date,
            species=common,
            scientific_name=sci,
            hour=hour,
        )
    else:
        detections, total_count = _run_db(
            infra.db_manager.get_paginated_detections,
            page=page,
            per_page=per_page,
            start_date=start_date,
            end_date=end_date,
            species=common,
            sort=sort,
            order=order,
            scientific_name=sci,
            hour=hour,
        )
    detections = _localize_detection_list(detections, settings=settings)

    total_pages = (total_count + per_page - 1) // per_page if per_page > 0 else 0

    return jsonify({
        'detections': detections,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total_items': total_count,
            'total_pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
    })


@api.route('/api/detections/export', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def export_detections_csv():
    """Export all detections as a CSV file, streamed in batches.

    Requires authentication. The response is generated batch by batch so an
    export of a very large table holds only one batch in memory at a time.

    Query params (optional):
    - start_date: Start date filter (YYYY-MM-DD)
    - end_date: End date filter (YYYY-MM-DD)
    - species: Filter by common_name
    """
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    species = request.args.get('species')

    # Validate date formats if provided
    for date_param, date_value in [('start_date', start_date), ('end_date', end_date)]:
        if date_value:
            try:
                datetime.strptime(date_value, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': f'Invalid {date_param} format. Use YYYY-MM-DD'}), 400

    sci, common = _resolve_species_filter(species)

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            'id', 'timestamp', 'group_timestamp', 'scientific_name', 'common_name',
            'confidence', 'latitude', 'longitude', 'cutoff', 'sensitivity', 'overlap',
            'week', 'extra', 'audio_source'
        ])

        before_timestamp = before_id = None
        try:
            while True:
                # Each batch is its own short executor-lane job, so a long
                # export shares the single DB lane with live requests instead
                # of holding it (and every row in memory) for the download.
                batch = _run_db(
                    infra.db_manager.get_detections_for_export_batch,
                    start_date=start_date,
                    end_date=end_date,
                    species=common,
                    scientific_name=sci,
                    before_timestamp=before_timestamp,
                    before_id=before_id,
                    limit=_EXPORT_BATCH_ROWS,
                )
                for detection in batch:
                    # Handle extra field - ensure NULL/None becomes '{}'
                    extra_value = detection.get('extra')
                    if extra_value is None:
                        extra_value = '{}'

                    writer.writerow([
                        detection.get('id', ''),
                        detection.get('timestamp', ''),
                        detection.get('group_timestamp', ''),
                        detection.get('scientific_name', ''),
                        detection.get('common_name', ''),
                        detection.get('confidence', ''),
                        detection.get('latitude', ''),
                        detection.get('longitude', ''),
                        detection.get('cutoff', ''),
                        detection.get('sensitivity', ''),
                        detection.get('overlap', ''),
                        detection.get('week', ''),
                        extra_value,
                        detection.get('audio_source', '')
                    ])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
                if len(batch) < _EXPORT_BATCH_ROWS:
                    return
                before_timestamp = batch[-1]['timestamp']
                before_id = batch[-1]['id']
        except Exception:
            # Response headers are already sent; log why the download broke
            # off and let the stream abort so the client sees a failed
            # transfer rather than a silently complete-looking file.
            logger.exception("CSV export aborted mid-stream")
            raise

    # Generate filename with timestamp
    timestamp = local_now().strftime('%Y%m%d_%H%M%S')
    filename = f'birdnet_detections_{timestamp}.csv'

    return Response(
        generate(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@api.route('/api/detections/<int:detection_id>', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def delete_detection(detection_id):
    """Delete a detection and its associated files.

    Requires authentication.
    """
    # delete_detection returns the detection row so we can clean up the
    # associated audio + spectrogram files below.
    detection = _run_db(infra.db_manager.delete_detection, detection_id)

    if not detection:
        return jsonify({'error': 'Detection not found'}), 404

    invalidate_dashboard_cache()
    invalidate_gallery_cache()

    # Clean up associated files using shared utility
    delete_result = delete_detection_files(detection)

    # Build files_deleted list for response
    files_deleted = []
    if delete_result['deleted_audio']:
        files_deleted.append(detection['audio_filename'])
    if delete_result['deleted_spectrogram']:
        files_deleted.append(detection['spectrogram_filename'])

    logger.info("Detection deleted with files", extra={
        'detection_id': detection_id,
        'species': detection['common_name'],
        'files_deleted': files_deleted
    })

    return jsonify({
        'status': 'deleted',
        'id': detection_id,
        'species': detection['common_name'],
        'files_deleted': files_deleted
    })


@api.route('/api/detections/batch', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def delete_detections_batch():
    """Delete multiple detections and their associated files.

    Requires authentication.
    Request body: { "ids": [1, 2, 3, ...] }
    Max 100 items per request.
    """
    data = request.json
    if not data or 'ids' not in data:
        return jsonify({'error': 'Missing ids array'}), 400

    ids = data['ids']
    if not isinstance(ids, list):
        return jsonify({'error': 'ids must be an array'}), 400

    if len(ids) == 0:
        return jsonify({'error': 'ids array is empty'}), 400

    if len(ids) > 100:
        return jsonify({'error': 'Maximum 100 items per batch'}), 400

    deleted = []
    failed = []

    for detection_id in ids:
        if not isinstance(detection_id, int):
            failed.append({'id': detection_id, 'error': 'Invalid ID type'})
            continue

        detection = _run_db(infra.db_manager.delete_detection, detection_id)
        if not detection:
            failed.append({'id': detection_id, 'error': 'Not found'})
            continue

        # Clean up associated files using shared utility
        delete_detection_files(detection)

        deleted.append(detection_id)

    if deleted:
        invalidate_dashboard_cache()
        invalidate_gallery_cache()

    logger.info("Batch deletion completed", extra={
        'deleted_count': len(deleted),
        'failed_count': len(failed)
    })

    return jsonify({
        'deleted': len(deleted),
        'failed': len(failed),
        'deleted_ids': deleted,
        'errors': failed
    })


# Cache for available species (loaded from model labels file)
# Keyed by model type so switching models invalidates cache
