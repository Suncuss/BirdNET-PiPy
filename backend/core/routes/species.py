"""Species endpoints: bird details, availability catalog, detection distribution.

Registered on the shared ``api`` blueprint at import time.
"""
from flask import jsonify, request

from config.settings import MODEL_TYPE
from core import api_infra as infra
from core.api_infra import _run_db, api
from core.api_utils import (
    _resolve_species_filter,
    handle_api_errors,
    validate_date_param,
)
from core.auth import require_scope
from core.detection_presenter import _localize_detection, _localize_species_list
from core.logging_config import get_logger, log_api_request
from core.settings_store import load_user_settings
from core.timezone_service import local_now
from model_service.label_utils import get_species_list

logger = get_logger(__name__)

_available_species_cache = {}

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
