"""Observation/dashboard endpoints and their response caches.

Owns the three single-flight response caches (dashboard, per-period summary,
bird gallery) and their invalidation/expiry semantics — the trickiest state in
the API. The cached payload builders run off the request thread on the DB
executor, so they always build the anonymous-safe variant (see
core.detection_presenter). Registered on the shared ``api`` blueprint at import.
"""
import threading
import time
from datetime import datetime, timedelta

from flask import jsonify, request

from core import api_infra as infra
from core.api_infra import _DB_JOB_TIMEOUT_SECONDS, _run_db, _submit_db, api
from core.api_utils import (
    handle_api_errors,
    log_data_metrics,
    validate_date_param,
    validate_limit_param,
)
from core.auth import get_request_tier, require_feature, require_scope
from core.detection_presenter import (
    _localize_activity_items,
    _localize_activity_overview,
    _localize_detection,
    _localize_detection_list,
    _localize_species_list,
    _localize_summary,
    _public_window_cutoff_date,
)
from core.logging_config import get_logger, log_api_request
from core.settings_store import load_user_settings
from core.timezone_service import local_now

logger = get_logger(__name__)

@api.route('/api/observations/latest', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_latest_observation():
    observation = _run_db(infra.db_manager.get_latest_detections, 1)
    if observation:
        settings = load_user_settings()
        localized = _localize_detection(observation[0], settings=settings)
        log_data_metrics('get_latest_observation', localized, {
            'species': localized.get('common_name'),
            'timestamp': localized.get('timestamp')
        })
        return jsonify(localized)
    # Return 200 with null for empty database - frontend shows "No observations available yet."
    return jsonify(None)

@api.route('/api/observations/recent', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_recent_observations():
    unique = request.args.get('unique', 'false').lower() == 'true'
    settings = load_user_settings()
    observations = _localize_detection_list(
        _run_db(infra.db_manager.get_latest_detections, 7, unique=unique),
        settings=settings,
    )
    log_data_metrics('get_recent_observations', observations)
    return jsonify(observations)

@api.route('/api/observations/summary', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_observation_summary():
    now = local_now()
    settings = load_user_settings()
    stats = _run_db(
        infra.db_manager.get_summary_stats_all_periods,
        now.replace(hour=0, minute=0, second=0, microsecond=0),
        now - timedelta(weeks=1),
        now - timedelta(days=30),
    )
    summary = {
        period: _localize_summary(stats[period], settings=settings)
        for period in ('today', 'week', 'month', 'allTime')
    }
    log_data_metrics('get_observation_summary', summary, {
        'today_count': summary.get('today', {}).get('totalObservations', 0),
        'all_time_species': summary.get('allTime', {}).get('uniqueSpecies', 0)
    })
    return jsonify(summary)

@api.route('/api/activity/hourly', methods=['GET'])
@log_api_request
@require_feature('charts')
@validate_date_param()
@handle_api_errors
def get_hourly_activity():
    date = request.args.get('date', default=local_now().strftime('%Y-%m-%d'))
    activity = _run_db(infra.db_manager.get_hourly_activity, date)
    log_data_metrics('get_hourly_activity', activity, {
        'date': date,
        'hours_with_activity': sum(1 for h in activity if h['count'] > 0)
    })
    return jsonify(activity)

@api.route('/api/activity/overview', methods=['GET'])
@log_api_request
@require_feature('charts')
@validate_date_param()
@handle_api_errors
def get_activity_overview():
    date = request.args.get('date', default=local_now().strftime('%Y-%m-%d'))
    order = request.args.get('order', default='most')
    if order not in ('most', 'least'):
        order = 'most'
    settings = load_user_settings()
    overview = _run_db(infra.db_manager.get_activity_overview, date, order=order)
    overview = _localize_activity_items(overview, settings=settings)
    log_data_metrics('get_activity_overview', overview, {
        'date': date,
        'species_count': len(overview) if overview else 0
    })
    return jsonify(overview)

# Dashboard response cache. Dashboard only includes the initially visible
# summary period (today); hidden summary tabs lazy-load through
# /api/dashboard/summary. TTL slightly above the poll interval so consecutive
# polls hit the cache.
_DASHBOARD_CACHE_TTL_SECONDS = 10

# Ceiling for the Activity Overview species lists. The client renders 10 or
# 15 rows depending on viewport height and slices down, so this stays a fixed
# server cap (rather than a per-client count parameter) to keep the payload
# shared across the single-flight cache.
_DASHBOARD_ACTIVITY_MAX_SPECIES = 15

# Ceiling for the Recent Observations lists, same pattern: the client shows
# 7 or 8 rows depending on viewport height and slices down.
_DASHBOARD_RECENT_MAX = 8
_dashboard_cache_lock = threading.Lock()  # hub-only: taken by route greenlets around job.result(), never inside builders
_dashboard_cache: dict = {
    'payload': None,
    'expires_at': 0.0,
    'inflight': None,  # in-flight job, or None
    'dirty': False,    # soft-expired while a job was in flight; see _expire_cache_entry
}

# Per-period TTLs. 'today' is pinned to the dashboard TTL (the dashboard
# payload embeds the today summary, so the two must stay in lockstep);
# week/month/allTime are the most expensive queries the API runs (full-table
# scans on a Pi Zero) and stay warm for minutes/hours — see
# expire_dashboard_cache() for why detections don't touch them.
_SUMMARY_CACHE_TTL_SECONDS = {
    'today': _DASHBOARD_CACHE_TTL_SECONDS,
    'week': 300,
    'month': 3600,
    'allTime': 3600,
}
# The TTL table defines the period set: adding a period means giving it a TTL.
_SUMMARY_PERIODS = tuple(_SUMMARY_CACHE_TTL_SECONDS)
_summary_cache_lock = threading.Lock()  # hub-only: see _dashboard_cache_lock
_summary_cache: dict = {
    period: {
        'payload': None,
        'expires_at': 0.0,
        'inflight': None,
        'dirty': False,
    }
    for period in _SUMMARY_PERIODS
}

# Bird Gallery response cache. The Most/Least Frequent and Species Catalog
# tabs run multi-second GROUP BY scans over the whole detections table. The
# gallery is opened on demand, not polled — so broadcast_detection() leaves it
# entirely alone (it doesn't even soft-expire it the way it does the dashboard
# entry): touching it per detection would keep it permanently cold. New
# detections age out via the TTL; bulk changes clear it explicitly (see
# invalidate_gallery_cache).
_GALLERY_SIGHTINGS_LIMIT = 12
_GALLERY_CACHE_TTL_SECONDS = 90
_GALLERY_KEY_FREQUENT = 'sightings:frequent'
_GALLERY_KEY_RARE = 'sightings:rare'
_GALLERY_KEY_SPECIES = 'species:all'
_gallery_cache_lock = threading.Lock()  # hub-only: see _dashboard_cache_lock
_gallery_cache: dict = {
    key: {'payload': None, 'expires_at': 0.0, 'inflight': None, 'dirty': False}
    for key in (_GALLERY_KEY_FREQUENT, _GALLERY_KEY_RARE, _GALLERY_KEY_SPECIES)
}


def _summary_period_start(period, now):
    if period == 'today':
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'week':
        return now - timedelta(weeks=1)
    if period == 'month':
        return now - timedelta(days=30)
    if period == 'allTime':
        return datetime.min
    raise ValueError(f"invalid summary period: {period}")


def _reset_cache_entry(entry):
    """Clear a single-flight cache entry's payload, TTL, and in-flight job."""
    entry['payload'] = None
    entry['expires_at'] = 0.0
    entry['inflight'] = None
    entry['dirty'] = False


def _expire_cache_entry(entry):
    """Expire a single-flight cache entry without discarding anything.

    Zeroes 'expires_at' but keeps 'payload' and — crucially — 'inflight': a
    rebuild already in progress keeps its slot, so it still completes and is
    served to its waiting callers (contrast _reset_cache_entry, which revokes
    the in-flight job's write). 'dirty' records that the expiry may predate
    an in-flight job's DB snapshot: _serve_single_flight's write then leaves
    the entry expired, so the next poll rebuilds instead of serving a
    pre-expiry snapshot for a full TTL. Freshness, not correctness.
    """
    entry['expires_at'] = 0.0
    entry['dirty'] = True


def invalidate_summary_cache():
    """Drop cached lazy summary-tab payloads."""
    with _summary_cache_lock:
        for entry in _summary_cache.values():
            _reset_cache_entry(entry)


def invalidate_dashboard_cache():
    """Drop the cached dashboard payload so the next request recomputes.

    Clearing 'inflight' here is what makes an invalidation race-safe: any
    job in flight when invalidate fires loses its slot, so the single-flight
    write (guarded on `inflight is job`) skips, leaving the cache empty for
    the next caller to refresh.

    This is the correctness path — for data that changed out from under the
    cache (deletes, migration imports, localization changes). New detections
    are a freshness event and use expire_dashboard_cache() instead.
    """
    with _dashboard_cache_lock:
        _reset_cache_entry(_dashboard_cache)
    invalidate_summary_cache()


def expire_dashboard_cache():
    """Expire the dashboard payload and 'today' summary; leave the rest warm.

    The freshness path for new detections (see _expire_cache_entry for the
    keep-payload/keep-inflight semantics). week/month/allTime are left alone
    entirely: one detection moves those counters by +1, and hard-expiring
    them per detection is what used to keep every summary permanently cold
    on active stations (detections arrive faster than the poll interval).
    """
    with _dashboard_cache_lock:
        _expire_cache_entry(_dashboard_cache)
    with _summary_cache_lock:
        _expire_cache_entry(_summary_cache['today'])


def invalidate_gallery_cache():
    """Drop cached Bird Gallery payloads (Most/Least Frequent + Species Catalog).

    Called when detections change in bulk (delete, migration import) or when a
    settings change alters localization — but never from broadcast_detection();
    see the _gallery_cache comment for that rationale.
    """
    with _gallery_cache_lock:
        for entry in _gallery_cache.values():
            _reset_cache_entry(entry)


def _serve_single_flight(entry, lock, ttl, builder, *args):
    """Serve a cached payload from `entry`, recomputing via `builder` under a
    single-flight guard so concurrent misses share one DB job.

    `entry` is a dict with 'payload'/'expires_at'/'inflight'/'dirty'. Only the
    caller whose job is still the 'inflight' slot writes the cache: if an
    invalidation cleared 'inflight' mid-compute, the `is job` guard fails and
    the write is skipped, so a job racing an invalidation cannot poison the
    cache. A soft expiry (_expire_cache_entry) instead keeps the job but marks
    the entry 'dirty', so the completed payload is served without earning a
    fresh TTL — its DB snapshot may predate whatever fired the expiry.
    """
    with lock:
        cached = entry['payload']
        if cached is not None and entry['expires_at'] > time.time():
            return cached

        job = entry['inflight']
        if job is None:
            job = _submit_db(builder, *args)
            entry['inflight'] = job
            # This job's DB snapshot postdates any expiry recorded so far.
            entry['dirty'] = False

    try:
        payload = job.result(timeout=_DB_JOB_TIMEOUT_SECONDS)
    except Exception:
        with lock:
            if entry['inflight'] is job:
                entry['inflight'] = None
        raise

    with lock:
        if entry['inflight'] is job:
            entry['payload'] = payload
            entry['expires_at'] = 0.0 if entry['dirty'] else time.time() + ttl
            entry['inflight'] = None

    return payload


def _build_summary_period_payload(period, *, settings=None, now=None):
    now = now or local_now()
    settings = settings or load_user_settings()
    summary = infra.db_manager.get_summary_stats_for_period(
        _summary_period_start(period, now),
        now=now,
    )
    return _localize_summary(summary, settings=settings)


def _get_summary_period_payload(period):
    return _serve_single_flight(
        _summary_cache[period], _summary_cache_lock,
        _SUMMARY_CACHE_TTL_SECONDS[period], _build_summary_period_payload, period,
    )


def _build_sightings_payload(most_frequent):
    """Build a localized Most/Least Frequent payload for the gallery cache."""
    settings = load_user_settings()
    sightings = infra.db_manager.get_species_sightings(
        limit=_GALLERY_SIGHTINGS_LIMIT, most_frequent=most_frequent,
    )
    # Cached + shared across tiers -> always emit the anonymous-safe variant.
    return _localize_detection_list(sightings, settings=settings, public_only=True)


def _build_species_all_payload():
    """Build the localized Species Catalog payload for the gallery cache."""
    settings = load_user_settings()
    species = infra.db_manager.get_all_unique_species()
    return _localize_species_list(species, settings=settings)


def _build_dashboard_payload():
    """Compute the dashboard payload with only the visible summary period."""
    now = local_now()
    today = now.strftime('%Y-%m-%d')
    settings = load_user_settings()

    recent_all = infra.db_manager.get_latest_detections(_DASHBOARD_RECENT_MAX)
    recent_unique = infra.db_manager.get_latest_detections(
        _DASHBOARD_RECENT_MAX, unique=True)
    # Cached + shared across tiers -> always emit the anonymous-safe variant
    # (the dashboard never displays source_label, so owners lose nothing here).
    recent_all = _localize_detection_list(recent_all, settings=settings, public_only=True)
    recent_unique = _localize_detection_list(recent_unique, settings=settings, public_only=True)
    latest = recent_all[0] if recent_all else None

    summary = {
        'today': _build_summary_period_payload('today', settings=settings, now=now)
    }

    hourly_activity = infra.db_manager.get_hourly_activity(today)
    activity_overview = _localize_activity_overview(
        infra.db_manager.get_activity_overview_both(
            today, num_species=_DASHBOARD_ACTIVITY_MAX_SPECIES),
        settings=settings,
    )

    return {
        'latestObservation': latest,
        'recentObservations': {'all': recent_all, 'unique': recent_unique},
        'summary': summary,
        'hourlyActivity': hourly_activity,
        'activityOverview': activity_overview
    }


@api.route('/api/dashboard', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_dashboard():
    """Consolidated dashboard endpoint — all DB data in one request.

    Cached for _DASHBOARD_CACHE_TTL_SECONDS via _serve_single_flight, so a
    thundering herd of polls from multiple tabs costs one DB pass, not N.
    """
    payload = _serve_single_flight(
        _dashboard_cache, _dashboard_cache_lock,
        _DASHBOARD_CACHE_TTL_SECONDS, _build_dashboard_payload,
    )
    return jsonify(payload)


@api.route('/api/dashboard/summary', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_dashboard_summary():
    """Return one dashboard summary period for lazy-loaded Summary tabs."""
    period = request.args.get('period', default='today')
    if period not in _SUMMARY_PERIODS:
        return jsonify({
            'error': f'Invalid period. Must be one of: {", ".join(_SUMMARY_PERIODS)}'
        }), 400

    summary = _get_summary_period_payload(period)
    log_data_metrics('get_dashboard_summary', summary, {
        'period': period,
        'total_observations': summary.get('totalObservations', 0),
        'unique_species': summary.get('uniqueSpecies', 0),
    })
    return jsonify(summary)


@api.route('/api/sightings/unique', methods=['GET'])
@require_scope('public:read')
@log_api_request
@validate_date_param(required=True)
@handle_api_errors
def get_unique_detections():
    date_str = request.args.get('date')
    # Anonymous callers are limited to the recent window: a past-date query would
    # otherwise let them date-walk historical species-by-day metadata. The gallery
    # only ever requests today's date, so this doesn't affect the public UI.
    if (
        get_request_tier() == 'public'
        and date_str
        and date_str < _public_window_cutoff_date()
    ):
        return jsonify([])
    settings = load_user_settings()
    # Get the unique detections from the database
    unique_detections = _run_db(
        infra.db_manager.get_detections_by_date_range,
        date_str,
        date_str,
        unique=True,
    )
    unique_detections = _localize_detection_list(unique_detections, settings=settings)
    log_data_metrics('get_unique_detections', unique_detections, {
        'date': date_str,
        'unique_species': len(unique_detections)
    })
    return jsonify(unique_detections)

@api.route('/api/sightings', methods=['GET'])
@require_scope('public:read')
@validate_limit_param(default=_GALLERY_SIGHTINGS_LIMIT)
@handle_api_errors
def get_sightings():
    """Consolidated endpoint for different types of sightings

    Query params:
    - type: 'frequent' or 'rare' (default: 'frequent')
    - limit: number of results (default: 12)
    """
    sighting_type = request.args.get('type', 'frequent')
    limit = request.args.get('limit', default=_GALLERY_SIGHTINGS_LIMIT, type=int)

    if sighting_type not in ('frequent', 'rare'):
        return jsonify({"error": "Invalid sighting type. Use 'frequent' or 'rare'"}), 400
    most_frequent = sighting_type == 'frequent'

    if limit == _GALLERY_SIGHTINGS_LIMIT:
        key = _GALLERY_KEY_FREQUENT if most_frequent else _GALLERY_KEY_RARE
        return jsonify(_serve_single_flight(
            _gallery_cache[key], _gallery_cache_lock,
            _GALLERY_CACHE_TTL_SECONDS, _build_sightings_payload, most_frequent,
        ))

    settings = load_user_settings()
    sightings = _run_db(
        infra.db_manager.get_species_sightings, limit=limit, most_frequent=most_frequent,
    )
    return jsonify(_localize_detection_list(sightings, settings=settings))


@api.route('/api/species/all', methods=['GET'])
@require_scope('public:read')
@log_api_request
@handle_api_errors
def get_all_species():
    """Get all unique bird species ever detected (Species Catalog).

    Served from the single-flight gallery cache; each species carries
    ``last_detected`` so the frontend needs no per-species detail fetch.
    """
    species_list = _serve_single_flight(
        _gallery_cache[_GALLERY_KEY_SPECIES], _gallery_cache_lock,
        _GALLERY_CACHE_TTL_SECONDS, _build_species_all_payload,
    )
    log_data_metrics('get_all_species', species_list)
    return jsonify(species_list)
