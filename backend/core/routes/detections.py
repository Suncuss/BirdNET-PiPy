"""Detection endpoints: table/trends reads, CSV exports, deletes.

Both exports — the streaming CSV and the prepared-zip jobs (core.export_jobs)
— batch DB reads so a million-row export stays a sequence of quick executor
jobs; deletes invalidate the dashboard/gallery caches they falsify.
Registered on the shared ``api`` blueprint at import.
"""
import csv
import io
import time
from datetime import datetime

from flask import Response, jsonify, request, send_file

import core.export_jobs as export_jobs
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
from core.maintenance_lease import MaintenanceInProgressError
from core.routes.observations import (
    invalidate_dashboard_cache,
    invalidate_gallery_cache,
)
from core.settings_store import load_user_settings
from core.timezone_service import local_now

logger = get_logger(__name__)


def _cooperative_yield():
    """Late-bound: the socketio global lives in core.api (set by create_app)."""
    from core.api import _cooperative_yield as cooperative_yield
    cooperative_yield()


# One bounded retry before surfacing a retryable maintenance response —
# the one-time index build usually finishes in seconds.
_MAINTENANCE_RETRY_SECONDS = 2


def _delete_with_maintenance_retry(detection_id):
    """delete_detection with the interactive-write contract: the DB layer
    refuses BEFORE any unlink while the index build holds the writer lock;
    retry once, then let the caller answer with an explicit retryable
    maintenance response (never a generic 500, never after side effects)."""
    try:
        return _run_db(infra.db_manager.delete_detection, detection_id)
    except MaintenanceInProgressError:
        time.sleep(_MAINTENANCE_RETRY_SECONDS)
        return _run_db(infra.db_manager.delete_detection, detection_id)


_MAINTENANCE_RESPONSE = (
    {'error': 'Maintenance in progress, please retry shortly',
     'retryable': True}, 503)



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
        writer.writerow(export_jobs.CSV_HEADER)
        try:
            for batch in export_jobs.iter_export_batches(
                    infra.db_manager, start_date=start_date, end_date=end_date,
                    species=common, scientific_name=sci):
                writer.writerows(batch)
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)
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


# Prepared exports (Settings → Export modal): the backend writes a zipped CSV
# as a background job with real progress; the download is a separate step.
# All owner-only — the CSV carries the station's coordinates.

def _resolve_export_range(args):
    """(start_date, end_date) from range/start_date/end_date args, or raise ValueError."""
    return export_jobs.resolve_range(
        args.get('range'), args.get('start_date'), args.get('end_date'))


@api.route('/api/detections/export/count', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def export_count():
    """Rows an export over the chosen range would contain (the modal's preview).

    Query params: range = all | 7d | 30d | year | custom (+ start_date and
    end_date as YYYY-MM-DD for custom).
    """
    try:
        start_date, end_date = _resolve_export_range(request.args)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    count = _run_db(infra.db_manager.count_detections_for_export, start_date, end_date)
    return jsonify({'count': count, 'start_date': start_date, 'end_date': end_date})


@api.route('/api/detections/export/jobs', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def start_export_job():
    """Start preparing an export. JSON body takes the same fields as
    /export/count. 409 with the running job if one is still preparing."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return jsonify({'error': 'Request body must be a JSON object'}), 400
    try:
        start_date, end_date = _resolve_export_range(body)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        job = export_jobs.start_export(infra.db_manager, start_date, end_date)
    except export_jobs.ExportBusyError as e:
        return jsonify({'error': str(e), 'job': e.job}), 409
    except export_jobs.ExportSpaceError as e:
        return jsonify({'error': str(e)}), 507
    return jsonify({'job': job}), 202


@api.route('/api/detections/export/jobs/current', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def current_export_job():
    """The current export job in any state, or null — lets the modal resume.
    ``today`` is the station's local date, which bounds the custom range
    (presets resolve against it too, not against the browser's date)."""
    return jsonify({'job': export_jobs.current_job(),
                    'today': local_now().date().isoformat()})


@api.route('/api/detections/export/jobs/<job_id>', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def get_export_job(job_id):
    job = export_jobs.get_job(job_id)
    if job is None:
        return jsonify({'error': 'Export not found or expired'}), 404
    return jsonify({'job': job})


@api.route('/api/detections/export/jobs/<job_id>', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def discard_export_job(job_id):
    """Cancel a preparing export, or delete a finished one's file."""
    if not export_jobs.discard_job(job_id):
        return jsonify({'error': 'Export not found or expired'}), 404
    return jsonify({'status': 'discarded'})


@api.route('/api/detections/export/jobs/<job_id>/file', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def download_export_file(job_id):
    """The prepared zip, as an attachment. A plain link, so the browser's
    download manager streams it to disk instead of holding it in memory."""
    ready = export_jobs.ready_file(job_id)
    if ready is None:
        return jsonify({'error': 'Export not found or expired'}), 404
    path, filename = ready
    return send_file(path, mimetype='application/zip',
                     as_attachment=True, download_name=filename)


@api.route('/api/detections/<int:detection_id>', methods=['DELETE'])
@log_api_request
@require_auth
@handle_api_errors
def delete_detection(detection_id):
    """Delete a detection and its associated files.

    Requires authentication.
    """
    # delete_detection unlinks the row's media BEFORE deleting the record
    # (ownership design: a crash can orphan a row, never leak files) and
    # reports the names actually removed — recorded names for resolved
    # rows, resolved pattern candidates for legacy ones.
    try:
        detection = _delete_with_maintenance_retry(detection_id)
    except MaintenanceInProgressError:
        body, status = _MAINTENANCE_RESPONSE
        return jsonify(body), status

    if not detection:
        return jsonify({'error': 'Detection not found'}), 404

    invalidate_dashboard_cache()
    invalidate_gallery_cache()

    files_deleted = detection['files_deleted']

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

        # File cleanup happens inside delete_detection, before the row goes.
        try:
            detection = _delete_with_maintenance_retry(detection_id)
        except MaintenanceInProgressError:
            body, status = _MAINTENANCE_RESPONSE
            return jsonify({**body, 'deleted': len(deleted),
                            'deleted_ids': deleted}), status
        if not detection:
            failed.append({'id': detection_id, 'error': 'Not found'})
            continue

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
