"""Species endpoints: bird details, availability catalog, detection distribution.

Registered on the shared ``api`` blueprint at import time.
"""
from datetime import UTC, date, datetime, timedelta

from flask import jsonify, request

from config.settings import MODEL_TYPE
from core import api_infra as infra
from core.api_infra import _run_db, api
from core.api_utils import (
    _resolve_species_filter,
    handle_api_errors,
    validate_date_param,
)
from core.auth import require_feature, require_scope
from core.bird_name_utils import add_display_common_name, get_bird_name_language
from core.detection_presenter import _localize_detection, _localize_species_list
from core.logging_config import get_logger, log_api_request
from core.settings_store import load_user_settings
from core.timezone_service import get_timezone, get_timezone_str, local_now
from model_service.label_utils import get_species_list

logger = get_logger(__name__)

_available_species_cache = {}


# Rolling windows start mid-day, so they can't use the daily rollups and always
# scan raw detections; the cap keeps that scan bounded for anonymous callers.
# Longer spans should use calendar dates, which read the rollups.
SUMMARY_MAX_HOURS = 168


def _parse_summary_hours(raw):
    if raw is None:
        return None
    try:
        hours = int(raw)
    except ValueError:
        hours = 0  # falls through to the range check's error
    if not 1 <= hours <= SUMMARY_MAX_HOURS:
        raise ValueError(f'hours must be a whole number from 1 to {SUMMARY_MAX_HOURS}')
    return hours


def _parse_summary_dates(start, end):
    """Strict YYYY-MM-DD pair. date.fromisoformat alone also accepts compact
    forms like 20261107, so require the canonical spelling round-trip."""
    try:
        if start != date.fromisoformat(start).isoformat() or end != date.fromisoformat(end).isoformat():
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Supply both start_date and end_date as YYYY-MM-DD') from None
    if start > end:
        raise ValueError('start_date must not be after end_date')
    return start, end


def _utc_now():
    return datetime.now(UTC)


def _rolling_cutoff(hours):
    """Station-local naive datetime ``hours`` of elapsed time ago.

    Subtract in UTC, then convert: subtracting from a local wall-clock time
    (naive, or aware with the same tzinfo) would make a window that crosses a
    DST change an hour too long or too short.
    """
    cutoff = _utc_now() - timedelta(hours=hours)
    return cutoff.astimezone(get_timezone()).replace(tzinfo=None)


@api.route('/api/species/summary', methods=['GET'])
@log_api_request
@require_feature('charts')
@handle_api_errors
def get_species_summary():
    """Return per-species counts and detection boundaries for inclusive local
    dates, a rolling window of the last ``hours``, or all history.

    Gated like the other per-species aggregates (activity overview, trends):
    anonymous callers get it only when the owner has made charts public.
    """
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    hours = _parse_summary_hours(request.args.get('hours'))
    dated = start is not None or end is not None
    since = None
    if hours is not None:
        if dated:
            raise ValueError('Use either hours or start_date/end_date, not both')
        since = _rolling_cutoff(hours)
    elif dated:
        start, end = _parse_summary_dates(start, end)
    species = _run_db(infra.db_manager.get_species_summary, start, end, since)
    language = get_bird_name_language(load_user_settings())
    species = [add_display_common_name(row, language=language) for row in species]
    return jsonify({
        'start_date': start,
        'end_date': end,
        'hours': hours,
        'timezone': get_timezone_str(),
        'species': species,
    })


@api.route('/api/bird/<species_name>', methods=['GET'])
@require_scope('public:read')
@log_api_request
def get_bird_details(species_name):
    settings = load_user_settings()
    sci, common = _resolve_species_filter(species_name)
    details = _run_db(infra.db_manager.get_bird_details, common, scientific_name=sci)
    if details:
        details = _localize_detection(details, settings=settings)
        logger.debug("Bird details retrieved", extra={
            'species': species_name,
            'resolved_scientific': sci,
            'total_detections': details.get('detectionCount', 0)
        })
        return jsonify(details)
    return jsonify({"error": "Bird species not found"}), 404


@api.route('/api/bird/<species_name>/detection_distribution', methods=['GET'])
@require_scope('public:read')
@validate_date_param()
@handle_api_errors
def get_detection_distribution(species_name):
    view = request.args.get('view', 'month')
    date = request.args.get('date', local_now().strftime('%Y-%m-%d'))
    sci, common = _resolve_species_filter(species_name)
    distribution = _run_db(
        infra.db_manager.get_detection_distribution,
        common, view, date, scientific_name=sci,
    )
    return jsonify(distribution)


def load_available_species():
    """Load all available species from the species table.

    Returns list of dicts with scientific_name and common_name.
    Results are cached per model type since the species table doesn't change at runtime.
    """
    model_type = load_user_settings().get('model', {}).get('type', MODEL_TYPE)

    if model_type in _available_species_cache:
        return _available_species_cache[model_type]

    species_list = get_species_list(model_type)
    _available_species_cache[model_type] = species_list
    logger.info("Loaded available species", extra={
        'count': len(species_list),
        'model_type': model_type,
    })
    return species_list


@api.route('/api/species/available', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_available_species():
    """Get all species available in the BirdNET model.

    Used for building include/exclude filter lists in the UI.
    Returns list of {scientific_name, common_name} sorted by common_name.
    Species count depends on model type: ~6K for V2.4, ~11K for V3.1.
    """
    settings = load_user_settings()
    search = request.args.get('search', '').lower()
    species_list = _localize_species_list(load_available_species(), settings=settings)

    # Filter by search term if provided
    if search:
        species_list = [
            s for s in species_list
            if (
                search in s['scientific_name'].lower()
                or search in s['common_name'].lower()
                or search in s.get('display_common_name', '').lower()
            )
        ]

    return jsonify({
        'species': species_list,
        'total': len(load_available_species()),
        'filtered': len(species_list)
    })
