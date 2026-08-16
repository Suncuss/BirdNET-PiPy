"""Media endpoints: audio/spectrogram serving, recordings, share links, OG cards.

Every payload with a playable clip flows through the entitlement gates here:
session (owner), signed media query (anonymous, in-window), or share token
(per-detection). The public recency window itself is defined in
core.detection_presenter. Registered on the shared ``api`` blueprint at import.
"""
import re

from flask import Response, jsonify, request

from config.settings import (
    DEFAULT_AUDIO_PATH,
    DEFAULT_IMAGE_PATH,
    EXTRACTED_AUDIO_DIR,
    SPECTROGRAM_DIR,
)
from core import api_infra as infra
from core.api_infra import _run_db, api
from core.api_utils import (
    _resolve_species_filter,
    handle_api_errors,
    recording_has_media,
    serve_file_with_fallback,
)
from core.auth import (
    forwarded_scheme,
    get_request_tier,
    is_authenticated,
    is_public_access_enabled,
    require_auth,
    require_scope,
)
from core.detection_presenter import (
    _localize_detection,
    _localize_detection_list,
    _public_window_cutoff,
    _within_public_window,
)
from core.logging_config import get_logger, log_api_request
from core.media_access import verify_media_signature
from core.og_card import (
    OG_CARD_IMAGE_PATH,
    format_og_description,
    indefinite_article,
    render_og_card,
)
from core.settings_store import load_user_settings
from core.share_tokens import mint_share_token, share_token_subject, verify_share_token
from core.utils import build_detection_permalink

logger = get_logger(__name__)

def _share_token_authorizes_file(token, filename):
    """True if a share token's own detection owns this audio/spectrogram file."""
    detection_id = share_token_subject(token)
    if detection_id is None:
        return False
    detection = _run_db(infra.db_manager.get_detection_by_id, detection_id)
    if detection is None:
        return False
    return filename in (
        detection.get('audio_filename'),
        detection.get('spectrogram_filename'),
    )


def _media_request_authorized(filename):
    """Whether the current request may fetch this media file.

    Owners (and auth-off installs) always may. A share token authorizes its own
    detection's two files even when public access is off (a private station can
    still share one detection's clip). Otherwise an anonymous caller needs a
    valid signed URL, and only while public access is on — so the deterministic
    filenames listed in public payloads can't be turned into a bulk download.

    Checked BEFORE serve_file_with_fallback, which returns a 200 placeholder on
    any miss: letting that run for an unauthorized request would leak access (and
    mask a broken gate) instead of returning 401.
    """
    if is_authenticated():
        return True
    share = request.args.get('s')
    if share and _share_token_authorizes_file(share, filename):
        return True
    if not is_public_access_enabled():
        return False
    return verify_media_signature(
        filename, request.args.get('exp'), request.args.get('sig'),
    )


def _follow_rename_in_ownership(old_name, new_name):
    """Keep detection_media in step with the lazy colon->dash rename (a
    no-op for unresolved legacy rows, which have no ownership record yet)."""
    _run_db(infra.db_manager.rename_detection_media, old_name, new_name)


@api.route('/api/audio/<filename>')
def serve_audio(filename):
    if not _media_request_authorized(filename):
        return jsonify({'error': 'Authentication required'}), 401
    return serve_file_with_fallback(EXTRACTED_AUDIO_DIR, filename, DEFAULT_AUDIO_PATH, "audio",
                                    on_rename=_follow_rename_in_ownership)

@api.route('/api/spectrogram/<filename>')
def serve_spectrogram(filename):
    if not _media_request_authorized(filename):
        return jsonify({'error': 'Authentication required'}), 401
    return serve_file_with_fallback(SPECTROGRAM_DIR, filename, DEFAULT_IMAGE_PATH, "spectrogram",
                                    on_rename=_follow_rename_in_ownership)

# Extra recordings fetched beyond the requested page so that filtering out rows
# whose audio/spectrogram files are missing from disk still fills the page.
RECORDINGS_MEDIA_OVERFETCH = 16

# Hard ceiling on how many recordings a single request may return. An omitted or
# oversized ``limit`` previously fell through to the DB as ``LIMIT -1`` (unbounded),
# letting a caller pull a species' entire detection history — and every audio
# filename — in one request: the cleanest full-DB scrape path. The frontend only
# ever asks for small pages (<=16), so this ceiling never affects the UI.
RECORDINGS_MAX_LIMIT = 500

# Tighter per-request cap for anonymous (auth-on, not-signed-in) callers, so the
# public bird-detail view still works (it asks for <=16) but a scripted crawl
# gets only a recent slice per species, not the archive. Owners are uncapped
# beyond RECORDINGS_MAX_LIMIT.
RECORDINGS_PUBLIC_MAX = 30


@api.route('/api/bird/<species_name>/recordings', methods=['GET'])
@require_scope('public:read')
@log_api_request
def get_bird_recordings(species_name):
    """Get recordings for a species with sorting options.

    Query params:
    - sort: 'recent' (default, timestamp DESC) or 'best' (confidence DESC)
    - limit: optional max number of records (omit for all)
    """
    sort = request.args.get('sort', 'recent')
    requested_limit = request.args.get('limit', type=int)  # None if not provided

    # Validate sort parameter
    if sort not in ['recent', 'best']:
        return jsonify({"error": "Sort must be 'recent' or 'best'"}), 400

    # Always bound the query. An omitted or oversized limit must never become an
    # unbounded scan (SQLite LIMIT -1) — that let an unauthenticated caller dump
    # a species' entire history (and every audio filename) in one request.
    if requested_limit is None:
        limit = RECORDINGS_MAX_LIMIT
    else:
        limit = max(1, min(requested_limit, RECORDINGS_MAX_LIMIT))

    # Anonymous (auth-on, not signed in) callers get a tighter, recency-windowed
    # slice per species — the bird-detail UI only asks for <=16, so this keeps the
    # public view working while denying a scripted per-species history dump and
    # old all-time 'best' clips.
    since = None
    if get_request_tier() == 'public':
        limit = min(limit, RECORDINGS_PUBLIC_MAX)
        since = _public_window_cutoff()

    settings = load_user_settings()
    sci, common = _resolve_species_filter(species_name)

    # Skip recordings whose audio/spectrogram files are gone from disk (storage
    # cleanup removes the files but keeps the row; spectrogram generation can
    # also fail independently). Over-fetch a small constant beyond the requested
    # page so dropping those doesn't leave the grid short — the displayed records
    # normally sit inside cleanup's protected window, so few (if any) are dropped.
    fetch_limit = limit + RECORDINGS_MEDIA_OVERFETCH
    fetched = _run_db(
        infra.db_manager.get_bird_recordings,
        common,
        sort,
        fetch_limit,
        scientific_name=sci,
        since=since,
    )
    present = [
        r for r in fetched
        if recording_has_media(r, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR)
    ]
    # Trim to the requested page (present[:None] is a no-op for the unlimited
    # case), then localize only the records we actually return.
    recordings = _localize_detection_list(present[:limit], settings=settings)

    logger.debug("Bird recordings retrieved", extra={
        'species': species_name,
        'resolved_scientific': sci,
        'sort': sort,
        'limit': limit,
        'fetched_count': len(fetched),
        'records_count': len(recordings)
    })
    return jsonify(recordings)

def _detection_view_entitled(detection, detection_id):
    """May the current request read this one detection (by-id permalink AND its
    OG share card — single owner of the rule so the two can never drift)?

    Owner always; a valid ``?s=`` share token grants exactly this detection
    (any age, even when public access is off); otherwise anonymous may read it
    only within the public recent window — so the historical archive can't be
    id-walked. Callers shape their own denial (404 vs. generic card) so the
    endpoint stays existence-oracle-free.
    """
    if detection is None:
        return False
    if is_authenticated():
        return True
    share = request.args.get('s')
    if share and verify_share_token(share, detection_id):
        return True
    return is_public_access_enabled() and _within_public_window(detection)


@api.route('/api/bird/<species_name>/recording/<int:recording_id>', methods=['GET'])
@log_api_request
def get_bird_recording(species_name, recording_id):
    """Get a single recording by ID for share / deep-link permalinks.

    Unlike the paged ``/recordings`` endpoint, this resolves a recording by its
    stable ID regardless of the recent/best sort window, so a shared link
    works even when the detection isn't among the top results. The recording
    must belong to the requested species (keeps permalinks coherent), else 404.

    ``has_media`` reports whether the audio/spectrogram files still exist:
    storage cleanup can delete them while keeping the row, so the client shows
    a graceful "no longer available" notice instead of a dead player.
    """
    # Mirror the recordings list filter: by scientific_name when the route name
    # resolves to a known species (possibly several keys for one common name
    # after a taxonomy split), otherwise by the legacy common_name.
    sci, common = _resolve_species_filter(species_name)

    detection = _run_db(infra.db_manager.get_detection_by_id, recording_id)
    if detection is None:
        return jsonify({"error": "Recording not found"}), 404

    belongs = (
        detection.get('scientific_name') in sci if sci
        else detection.get('common_name') == common
    )
    if not belongs:
        # Return the SAME 404 as a missing id (not "...for this species"): a
        # distinct message let a caller distinguish "id exists under another
        # species" from "id doesn't exist", an existence oracle for DB size.
        return jsonify({"error": "Recording not found"}), 404

    # Access control (manual, not @require_scope, so a share token grants access
    # even when public access is off — see _detection_view_entitled). 404 (not
    # 401) on denial so the endpoint can't be probed for which ids exist.
    if not _detection_view_entitled(detection, recording_id):
        return jsonify({"error": "Recording not found"}), 404

    settings = load_user_settings()
    recording = _localize_detection(detection, settings=settings)
    recording['has_media'] = recording_has_media(
        recording, EXTRACTED_AUDIO_DIR, SPECTROGRAM_DIR,
    )
    # Same-species sibling detections from the same source recording, so the
    # player's analysis-window bar can label every 3s window that fired — not
    # just this row's. Added after _localize_detection on purpose: it's safe
    # for public/share viewers (timestamps + confidence of the same species
    # within the same few seconds of audio; no ids, no location, no source).
    recording['group_detections'] = _run_db(
        infra.db_manager.get_group_detection_windows, detection)
    return jsonify(recording)


@api.route('/api/detections/<int:detection_id>/share', methods=['POST'])
@log_api_request
@require_auth
@handle_api_errors
def create_share_link(detection_id):
    """Mint a share token for one detection (owner only).

    The token authorizes read of exactly this detection (its id is a signed
    claim) plus its two media files — see core.share_tokens. The frontend builds
    the shareable URL from the returned token, so base-href/ingress prefixes are
    handled client-side.
    """
    detection = _run_db(infra.db_manager.get_detection_by_id, detection_id)
    if detection is None:
        return jsonify({'error': 'Recording not found'}), 404

    token = mint_share_token(detection_id)
    return jsonify({'token': token})


# hostname/IPv4 (dots, hyphens), IPv6 ([...]), optional :port — nothing else,
# so a forged forwarding header can't smuggle a path, userinfo, or markup into
# the absolute URLs reflected on the OG card.
_FORWARDED_HOST_RE = re.compile(r'^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:]+\](:\d{1,5})?$')


def _external_base_url():
    """Best-effort external origin (``scheme://host``) for absolute share/OG URLs.

    nginx forwards the externally requested scheme/host via X-Forwarded-Proto /
    X-Forwarded-Host (see ``frontend/nginx.conf``); fall back to the request's
    own scheme/host for direct access. Proxy chains can comma-join these, so we
    take the first (outermost) hop.

    Both headers are ultimately client-controlled (nginx copies the client's
    own ``Host`` into X-Forwarded-Host), so constrain them to a plain
    http(s)://host[:port] shape — a forged header degrades to the request's own
    scheme/host instead of planting an arbitrary URL on the card.
    """
    proto = forwarded_scheme()
    host = request.headers.get('X-Forwarded-Host', '').split(',')[0].strip()
    if not _FORWARDED_HOST_RE.match(host):
        host = request.host
    return f"{proto}://{host}"


@api.route('/api/og/recording/<int:recording_id>', methods=['GET'])
@log_api_request
def get_recording_og_card(recording_id):
    """Server-rendered Open Graph card for a detection permalink.

    A shared link (``/bird/<name>/recording/<id>``) is a client-rendered SPA
    route, so link-unfurl crawlers — which read ``<head>`` meta tags but never
    run JS — get only the static ``index.html`` and preview the link as a bare
    URL. nginx routes *only* known crawler user-agents here (humans still get
    the SPA); this returns a tiny HTML doc whose ``<head>`` carries
    per-detection OG/Twitter tags.

    Resolution is by ID alone (the species segment is decorative) to avoid
    URL-encoding pitfalls with species names containing spaces. A stale/deleted
    detection falls back to a generic branded card so the link still previews.
    Every card carries the app's branded bird illustration as ``og:image`` so it
    unfurls as a large-thumbnail card (which also reveals the description on
    iMessage). A per-detection image isn't used: the only per-detection raster is
    a WebP spectrogram, which unfurlers don't reliably render.

    Access mirrors the by-id permalink gate (owner / share token / public
    recent window): the card is derived from the same data the permalink would
    serve, so it must not reveal more. Crawlers are anonymous, so on an
    auth-enabled station a detection outside the anonymous view unfurls as the
    SAME generic branded card as a nonexistent id — the link still previews
    (title + illustration), it names no species, and the route can't be
    id-walked as an existence oracle for private detections.
    """
    base = _external_base_url()
    image_url = f"{base}{OG_CARD_IMAGE_PATH}"

    detection = _run_db(infra.db_manager.get_detection_by_id, recording_id)
    if not _detection_view_entitled(detection, recording_id):
        return Response(render_og_card(
            title="Bird detections",
            description="Live bird detections from a BirdNET listening station.",
            url=f"{base}/",
            image_url=image_url,
        ), mimetype='text/html')

    settings = load_user_settings()
    recording = _localize_detection(detection, settings=settings)

    common = recording.get('common_name') or 'Unknown species'
    display = recording.get('display_common_name') or common
    # Canonical SPA permalink. Use common_name (which the SPA route resolves
    # against) for the path segment, properly URL-encoded.
    share_url = build_detection_permalink(base, common, recording_id)

    # iMessage's no-image summary card mostly shows the title, so it leads with
    # the app and the species ("BirdNET-PiPy overheard a Northern Cardinal").
    # "overheard" (not "spotted") keeps it accurate — detection is acoustic, the
    # bird is heard, never seen. The scientific name / confidence / time ride
    # along in the description for platforms (Slack, Discord, …) that show it.
    title = f"BirdNET-PiPy overheard {indefinite_article(display)} {display}"

    return Response(render_og_card(
        title=title,
        description=format_og_description(recording),
        url=share_url,
        image_url=image_url,
    ), mimetype='text/html')
