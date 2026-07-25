"""Detection payload shaping: localization + the anonymous-safe public variant.

Every detection-shaped payload the API returns passes through here on its way
out. Two concerns live together because they run per-row in the same pass:

- Localization: attach display names in the configured bird-name language.
- Privacy: strip private/owner-only fields and mint short-lived signed media
  URLs, but only for detections inside the anonymous public recency window.

The window helpers (_public_window_cutoff*) are the single source of truth for
"how far back can an anonymous caller see" — the recordings routes, the
Detections table, and the media-signature gate must all agree on one boundary.
"""
from datetime import timedelta

from core.auth import get_request_tier
from core.bird_name_utils import (
    add_display_common_name,
    add_display_species,
    get_bird_name_language,
    get_localized_common_name,
)
from core.db import PRIVATE_DETECTION_FIELDS
from core.media_access import sign_media_query
from core.timezone_service import local_now

# Recency window for anonymous callers: the public view shows only the recent
# slice, so an anonymous caller can't pull a species' old all-time clips (incl.
# high-confidence ones via 'best' sort), nor id-walk historical detections via
# the by-id permalink. Owners and share-token holders are not windowed.
RECORDINGS_PUBLIC_WINDOW_DAYS = 30


def _public_window_cutoff():
    """ISO timestamp lower bound for the anonymous recent window.

    Floored to midnight (whole days) so every consumer agrees on one boundary:
    the recordings/by-id ``since`` filters, the media-signature gate
    (``_within_public_window``), and the Detections table — which floors an
    anonymous ``start_date`` to ``YYYY-MM-DD``. Without the floor the table
    floored by date but the signature gate compared the full timestamp, so rows
    earlier in the cutoff day than the current time were shown to anonymous
    callers with unplayable (unsigned) media. Whole-day granularity keeps the
    window ~30 calendar days and makes the two agree exactly.
    """
    cutoff_day = (local_now() - timedelta(days=RECORDINGS_PUBLIC_WINDOW_DAYS)).date()
    return f'{cutoff_day.isoformat()}T00:00:00'


def _public_window_cutoff_date():
    """The window boundary as a bare ``YYYY-MM-DD``, for date-granular params.

    Lives next to _public_window_cutoff so the "first 10 chars of the ISO
    timestamp = the date" layout knowledge stays in one place — consumers
    comparing bare dates (table start_date, sightings/unique date-walk) must
    use the SAME day the timestamp consumers use.
    """
    return _public_window_cutoff()[:10]


def _within_public_window(detection, cutoff=None):
    """Whether a detection is recent enough to be in the anonymous public view.

    ``cutoff`` may be passed in (computed once per request) to avoid recomputing
    the window boundary for every row of a list payload.
    """
    timestamp = detection.get('timestamp')
    return bool(timestamp) and str(timestamp) >= (cutoff or _public_window_cutoff())


def _strip_private_fields(detection):
    # Endpoint-level guard (defense in depth). The data layer already drops
    # PRIVATE_DETECTION_FIELDS in DatabaseManager._normalize_detection; this also
    # covers any path that builds a payload from coordinates obtained another
    # way. Both layers share the same tuple (imported from core.db) so the
    # private-field list has a single source of truth.
    if isinstance(detection, dict):
        for field in PRIVATE_DETECTION_FIELDS:
            detection.pop(field, None)
    return detection


def _add_media_signatures(detection, cutoff=None):
    """Attach short-lived signed query strings (``audio_sig``/``spectrogram_sig``)
    so an anonymous client can fetch exactly this detection's audio/spectrogram.

    Only minted for detections within the public recency window. So an
    anonymous caller never receives a working media URL for an OLD clip via ANY
    payload path (sightings, sightings/unique date-walk, dashboard samples, etc.),
    not just the recordings list. Owners still play old clips via their session
    (the bare-filename request is authorized by the cookie); share links use the
    token, not the signature. Handles both field-name conventions (recordings use
    ``audio_filename``; the dashboard/recent path renames to ``bird_song_file_name``).
    See core.media_access.
    """
    if not isinstance(detection, dict) or not _within_public_window(detection, cutoff):
        return detection
    audio_fn = detection.get('audio_filename') or detection.get('bird_song_file_name')
    if audio_fn:
        detection['audio_sig'] = sign_media_query(audio_fn)
    spectrogram_fn = (
        detection.get('spectrogram_filename') or detection.get('spectrogram_file_name')
    )
    if spectrogram_fn:
        detection['spectrogram_sig'] = sign_media_query(spectrogram_fn)
    return detection


# Extra-blob keys safe to expose to anonymous callers. Anything else (notably
# source_label, a user-chosen name that can hint at the station's location or
# layout) is dropped from public payloads, along with the raw audio_source id.
_PUBLIC_EXTRA_KEYS = {'weather'}


def _strip_public_metadata(detection):
    """Drop owner-only metadata (source label/id; any non-weather extra key)
    from a payload bound for an anonymous caller."""
    if not isinstance(detection, dict):
        return detection
    detection.pop('audio_source', None)
    extra = detection.get('extra')
    if isinstance(extra, dict):
        detection['extra'] = {
            key: value for key, value in extra.items()
            if key.lower() in _PUBLIC_EXTRA_KEYS
        }
    return detection


def _localize_detection(detection, settings=None, is_public=None, cutoff=None):
    # add_display_common_name returns a copy, so popping here never mutates the
    # underlying DB row.
    # is_public=None derives the tier from the current request; callers
    # serializing a list pass it (and cutoff) in once, computed per-request,
    # rather than re-deriving them for every row. Off-request-thread callers
    # (the cached payload builders) MUST pass is_public explicitly — there is
    # no request context to derive from.
    if is_public is None:
        is_public = get_request_tier() == 'public'
    localized = _strip_private_fields(add_display_common_name(
        detection,
        language=get_bird_name_language(settings),
        settings=settings,
    ))
    # Anonymous callers get the safe variant: owner-only metadata stripped, and
    # signed media URLs minted (owners fetch media by bare filename via their
    # session, so signatures would be dead payload weight for them). Cached
    # payloads (dashboard/sightings) are built once and shared across tiers, so
    # their builders force is_public=True to keep the cached copy the safe one.
    if is_public:
        _add_media_signatures(localized, cutoff)
        _strip_public_metadata(localized)
    return localized


def _localize_detection_list(detections, settings=None, public_only=False):
    # public_only forces the anonymous-safe variant without consulting the
    # request tier: cached payloads (dashboard/sightings) are built off the
    # request thread, so there is no request context to classify.
    is_public = public_only or get_request_tier() == 'public'
    cutoff = _public_window_cutoff()
    return [
        _localize_detection(detection, settings=settings, is_public=is_public,
                            cutoff=cutoff)
        for detection in detections
    ]


def _localized_species_order(species_pairs, settings=None, *, descending=False):
    """Order scientific names by their localized display name.

    Takes get_distinct_species_pairs output and produces the species order
    that get_paginated_detections_localized pages by, so the species-column
    sort never materializes detection rows. Species sharing a display name
    get a deterministic scientific_name tiebreak.
    """
    language = get_bird_name_language(settings)
    return [sci for _, sci in sorted(
        (
            (get_localized_common_name(sci, common, language=language,
                                       settings=settings).casefold(), sci)
            for sci, common in species_pairs
        ),
        reverse=descending,
    )]


def _localize_species_list(species_list, settings=None):
    # The species catalog is built off the request thread (single-flight gallery
    # cache) and shared across tiers, so it must NOT resolve a request tier per
    # row: get_request_tier() -> is_authenticated() -> session access has no
    # request context on the db-executor thread and raises "Working outside of
    # request context", which hard-500s /api/species/all whenever auth is enabled
    # (the failed build never warms the cache, so every subsequent request 500s
    # too, for owners as well as anonymous callers). public_only=True forces the
    # anonymous-safe variant like the dashboard/sightings builders; catalog rows
    # carry no owner-only metadata (common/scientific name + last_detected
    # only), so the stripping is a no-op on the data.
    localized = _localize_detection_list(species_list, settings=settings, public_only=True)
    localized.sort(key=lambda species: species.get('display_common_name', species.get('common_name', '')))
    return localized


def _localize_summary(summary, settings=None):
    """Add ``mostCommonBirdDisplay`` and ``rarestBirdDisplay`` fields.

    Looks up the translation by ``{key}ScientificName`` (the stable key from
    the DB CTE), so V2's "Eurasian Blackbird" and V3's "Common Blackbird" for
    the same Turdus merula both translate to "Amsel" under German. Falls back
    to the English ``{key}`` value when no scientific name is available
    (legacy rows) or when the summary is empty.
    """
    localized_summary = dict(summary)

    for key in ('mostCommonBird', 'rarestBird'):
        bird_name = localized_summary.get(key)
        sci_name = localized_summary.get(f'{key}ScientificName')
        if bird_name and bird_name != 'N/A':
            localized_summary[f'{key}Display'] = get_localized_common_name(
                sci_name,
                bird_name,
                language=get_bird_name_language(settings),
                settings=settings,
            )
        else:
            localized_summary[f'{key}Display'] = bird_name

    return localized_summary


def _localize_activity_overview(activity_overview, settings=None):
    if not activity_overview:
        return activity_overview

    return {
        key: [add_display_species(item, settings=settings) for item in items]
        for key, items in activity_overview.items()
    }


def _localize_activity_items(items, settings=None):
    return [add_display_species(item, settings=settings) for item in items]
