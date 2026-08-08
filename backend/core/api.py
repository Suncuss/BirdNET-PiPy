"""API composition root: app factory, SocketIO wiring, and the runtime bridge.

The REST endpoints live in core/routes/* (registered on the shared blueprint
from core.api_infra); what remains here is what genuinely belongs with the app
factory — the socketio-coupled broadcast/status routes, the health probe, and
the two entrypoints (``python -m core.api`` for dev/HA legacy; wsgi.py for
gunicorn/gevent).
"""
import requests
from flask import (
    Flask,
    jsonify,
    request,
)
from flask_socketio import SocketIO, emit, join_room

from config.settings import (
    API_PORT,
    BIRDNET_STATUS_ENDPOINT,
    MODEL_STARTUP_STATUS_PATH,
)
from core.api_infra import (
    _assert_route_access_declared,
    api,
    require_internal,
    reset_db_executor,
)
from core.api_utils import (
    handle_api_errors,
)
from core.auth import (
    configure_session,
    get_request_tier,
    is_authenticated,
    is_feature_public,
    require_auth,
    require_feature,
)
from core.detection_presenter import (
    _localize_detection,
)
from core.logging_config import get_logger, log_api_request
from core.routes.observations import (
    expire_dashboard_cache,
    invalidate_dashboard_cache,
    invalidate_gallery_cache,
)
from core.settings_store import (
    load_user_settings,
)
from core.timezone_service import get_timezone_str
from model_service.service_status import read_startup_failure

# Logging is configured in core.api_infra (imported above), before the DB
# manager is constructed there.
logger = get_logger(__name__)

@api.route('/api/stream/config', methods=['GET'])
@log_api_request
@require_feature('live_feed')
@handle_api_errors
def get_stream_config():
    """Provide stream configuration for frontend based on enabled sources."""
    settings = load_user_settings()
    audio = settings.get('audio') or {}
    sources = audio.get('sources', [])
    enabled = [s for s in sources if s.get('enabled', True)]

    # Owner-chosen labels stay owner-only: they can hint at the station's
    # location or layout, which is why _strip_public_metadata drops
    # source_label and /api/recorder/status is owner-room-only. Anonymous
    # live-feed listeners get a positional name instead — enough to tell two
    # streams apart in the picker.
    is_public = get_request_tier() == 'public'

    streams = []
    for index, source in enumerate(enabled, start=1):
        sid = source.get('id', '')
        label = f'Source {index}' if is_public else (source.get('label') or sid)
        streams.append({
            'source_id': sid,
            'label': label,
            'url': f'stream/{sid}.mp3',
        })

    return jsonify({'streams': streams})

@api.route('/api/broadcast/detection', methods=['POST'])
@require_internal
def broadcast_detection_endpoint():
    """Endpoint to broadcast detection via WebSocket.

    Internal-only endpoint - only accessible from docker network or localhost.
    Called by the main processing container to broadcast detections to WebSocket clients.
    """
    try:
        detection_data = request.json
        broadcast_detection(detection_data)
        # Log is handled in broadcast_detection() function to avoid duplication
        return jsonify({'status': 'broadcasted'}), 200
    except Exception as e:
        logger.error("Failed to broadcast detection", extra={
            'error': str(e)
        }, exc_info=True)
        return jsonify({'error': str(e)}), 500

@api.route('/api/broadcast/recorder-status', methods=['POST'])
@require_internal
def broadcast_recorder_status_endpoint():
    """Receive recorder health status from main container and broadcast to owners.

    Internal-only endpoint - only accessible from docker network or localhost.
    Called by the main processing container on recorder state changes. The status
    is emitted only to the owner room (authenticated sockets), since it carries
    source labels and error text that must not reach anonymous live_feed clients.
    """
    global _recorder_status
    try:
        _recorder_status = request.json
        if socketio:
            socketio.emit('recorder_status', _recorder_status, room=_OWNER_ROOM)
        logger.debug("Recorder status broadcasted", extra={
            'state': _recorder_status.get('state')
        })
        return jsonify({'status': 'broadcasted'}), 200
    except Exception as e:
        logger.error("Failed to broadcast recorder status", extra={
            'error': str(e)
        })
        return jsonify({'error': str(e)}), 500

@api.route('/api/recorder/status', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def get_recorder_status():
    """Return current recorder health status.

    Requires authentication — the payload may contain source labels,
    types, and error details that should not be exposed publicly.
    Decoupled from live feed so it is not gated by live_feed_public.
    """
    return jsonify(_recorder_status or {})


def _unavailable_model_status():
    startup_failure = read_startup_failure(MODEL_STARTUP_STATUS_PATH)
    if startup_failure:
        error_type = startup_failure["error_type"]
        error_message = startup_failure["message"]
        code = "model_service_startup_failed"
        message = (
            f"Model service failed to start ({error_type}: {error_message}). "
            "Acoustic detection is unavailable; check System Logs for details."
        )
    else:
        code = "model_service_unavailable"
        message = (
            "Model service is unavailable. It may still be starting or may have "
            "failed; check System Logs if this persists."
        )
    return {
        'status': 'unavailable',
        'model': None,
        'location_filter': {
            'state': 'unavailable',
            'source': 'disabled',
            'version': None,
            'code': code,
            'message': message,
        },
    }


@api.route('/api/model/status', methods=['GET'])
@log_api_request
@require_auth
@handle_api_errors
def get_model_service_status():
    """Return authenticated model/filter health without exposing port 5001."""
    try:
        response = requests.get(BIRDNET_STATUS_ENDPOINT, timeout=3)
        response.raise_for_status()
        payload = response.json()
        filter_status = payload.get('location_filter') if isinstance(payload, dict) else None
        if not isinstance(filter_status, dict) or filter_status.get('state') not in {
            'active', 'disabled', 'degraded'
        }:
            raise ValueError('Invalid model service status payload')
        return jsonify(payload), 200
    except (requests.exceptions.RequestException, ValueError) as exc:
        logger.warning("Unable to read model service status", extra={
            'error': str(exc),
        })
        return jsonify(_unavailable_model_status()), 200

@api.route('/api/health', methods=['GET'])
def health_check():
    """Unauthenticated liveness probe. Deliberately DB-free: a DB touch would
    couple liveness to transient SQLite locks. Must stay unauthenticated.
    """
    return jsonify({'status': 'ok'}), 200


# Global SocketIO instance to be used by other modules
socketio = None


def _cooperative_yield():
    """Yield the single gevent worker from long loops; no-op until create_app() sets `socketio`."""
    if socketio is not None:
        socketio.sleep(0)

# Latest recorder health status (populated by main container broadcasts)
_recorder_status = {}

# SocketIO room that only authenticated (owner) sockets join, so recorder health
# — which carries source labels/types and ffmpeg error text that can echo RTSP
# credentials — is broadcast to owners only, matching the @require_auth REST route.
_OWNER_ROOM = 'owners'

def create_app(async_mode='threading'):
    # The 'threading' default is load-bearing, not cosmetic. requirements.txt
    # ships gevent (for the gunicorn wsgi.py path), and Flask-SocketIO's
    # auto-selection prefers gevent over threading. Any caller that omits
    # async_mode — `python -m core.api` (local dev, tests, and the HA add-on's
    # legacy entrypoint) — must stay on threading: that path does NOT run
    # gevent's monkey.patch_all(), so an auto-selected gevent backend would
    # block on unpatched socket/sleep calls. wsgi.py passes async_mode='gevent'
    # explicitly (and patches first). Do not drop this default.
    global socketio
    reset_db_executor(async_mode)
    invalidate_dashboard_cache()
    invalidate_gallery_cache()

    app = Flask(__name__)

    # CORS is intentionally NOT enabled - all requests go through nginx proxy
    # which makes them same-origin. This prevents cross-origin attacks while
    # cookies and sessions work normally for same-origin requests.

    # Configure session for authentication
    configure_session(app)

    # Route modules register themselves on the shared api blueprint at import
    # time (see core/routes/__init__.py); import before registering it.
    from core.routes.migration import cleanup_migration_temp_dir

    try:
        cleanup_migration_temp_dir()
    except Exception as e:
        logger.warning("Startup migration temp cleanup failed", extra={'error': str(e)})

    import core.routes  # noqa: F401

    app.register_blueprint(api)
    _assert_route_access_declared(app)

    # Initialize SocketIO.
    # `cors_allowed_origins=None` lets Engine.IO compute allowed origins from the
    # request host headers (same-origin only). Do not set this to [] (blocks all origins).
    socketio = SocketIO(app, async_mode=async_mode, cors_allowed_origins=None,
                         logger=False, engineio_logger=False)

    # WebSocket event handlers
    @socketio.on('connect')
    def handle_connect():
        is_owner = is_authenticated()
        if not is_feature_public('live_feed') and not is_owner:
            return False  # Reject connection
        logger.info('WebSocket client connected')
        emit('status', {'message': 'Connected to live detection feed'})
        # recorder_status is owner-only (source labels/types + ffmpeg error text
        # that can contain RTSP credentials), matching the @require_auth
        # /api/recorder/status route. Anonymous live_feed listeners must not get
        # it. Owners join a room so the main container's status broadcasts reach
        # only them (see broadcast_recorder_status_endpoint).
        if is_owner:
            join_room(_OWNER_ROOM)
            if _recorder_status:
                emit('recorder_status', _recorder_status)

    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info('WebSocket client disconnected')

    return app, socketio

def revoke_owner_sockets():
    """Evict every socket currently in the owner room.

    HTTP gates re-check the session epoch on each request, but a WebSocket is
    authenticated once at connect and would otherwise keep receiving
    recorder_status — source labels and ffmpeg error text that can echo RTSP
    credentials — for the life of the tab. The event explains the reason to
    cooperative clients, while server-side disconnects enforce revocation even
    when a client ignores it.
    """
    global socketio
    if not socketio:
        return

    participants = tuple(
        socketio.server.manager.get_participants('/', _OWNER_ROOM)
    )
    socketio.emit('session_revoked', {'reason': 'password_changed'},
                  room=_OWNER_ROOM)
    for sid, _ in participants:
        socketio.server.disconnect(sid, namespace='/')
    logger.info("Owner sockets revoked", extra={'count': len(participants)})


def broadcast_detection(detection_data):
    """Function to broadcast detection to all connected clients"""
    global socketio
    # Freshness, not correctness: expire only what the new detection changes
    # (see expire_dashboard_cache); week/month/allTime stay warm.
    expire_dashboard_cache()
    if socketio:
        detection_payload = _localize_detection(detection_data)
        socketio.emit('bird_detected', detection_payload)
        logger.debug("Detection broadcasted to WebSocket clients", extra={
            'species': detection_payload.get('common_name', 'Unknown'),
            'confidence': detection_payload.get('confidence')
        })

if __name__ == '__main__':
    logger.info("🌐 API server starting", extra={
        'port': API_PORT,
        'websocket': 'enabled',
        'timezone': get_timezone_str()
    })
    app, socketio = create_app()
    socketio.run(app, host='0.0.0.0', port=API_PORT, debug=False, allow_unsafe_werkzeug=True)
