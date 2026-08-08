"""WebSocket (Flask-SocketIO) regression tests.

These tests exercise the real Flask-SocketIO handshake — unlike the rest of the
API suite, they do NOT mock ``core.api.socketio``. The point is to catch
dependency-compat breakage between Flask and Flask-SocketIO (e.g. the
Flask 3.1.3 / Flask-SocketIO 5.5.1 ``RequestContext.session`` read-only crash
fixed in b6b0f26) before it ships.
"""
import json
from contextlib import contextmanager

import pytest

from tests.api.conftest import AUTH_TEST_PASSWORD, sandboxed_auth_env

# Sensitive recorder health: a source label plus ffmpeg error text that can echo
# an RTSP URL with embedded credentials. Must never reach an anonymous socket.
_RECORDER_STATUS = {
    'state': 'error',
    'sources': [{
        'label': 'Backyard Cam',
        'type': 'rtsp',
        'last_error_message': "Failed to open rtsp://admin:hunter2@192.168.1.9/stream",
    }],
}


@pytest.fixture
def ws_app():
    """Create a real Flask app with a real SocketIO instance (no mocks).

    Auth defaults to disabled (no auth.json in the sandbox), so the connect
    handler's feature gate passes without needing a logged-in session.
    """
    with sandboxed_auth_env(mock_socketio=False) as (api_module, _):
        app, socketio = api_module.create_app()
        app.config['TESTING'] = True
        yield app, socketio


class TestWebSocketHandshake:
    """Verify the real Flask + Flask-SocketIO handshake works end-to-end."""

    def test_connect_succeeds(self, ws_app):
        """Connecting must not raise — guards against Flask/Flask-SocketIO
        version-compat regressions where the connect handler crashes on the
        request context (see commit b6b0f26)."""
        app, socketio = ws_app
        client = socketio.test_client(app)
        assert client.is_connected()
        client.disconnect()

    def test_connect_emits_status(self, ws_app):
        """The connect handler emits a 'status' event with a welcome message."""
        app, socketio = ws_app
        client = socketio.test_client(app)
        received = client.get_received()
        names = [event['name'] for event in received]
        assert 'status' in names
        status_event = next(e for e in received if e['name'] == 'status')
        assert status_event['args'][0]['message'] == 'Connected to live detection feed'
        client.disconnect()

    def test_disconnect_does_not_raise(self, ws_app):
        """The disconnect handler must run cleanly — same compat surface as
        connect, since both push a Flask request context."""
        app, socketio = ws_app
        client = socketio.test_client(app)
        client.disconnect()
        assert not client.is_connected()


class TestBroadcastDetectionEndToEnd:
    """Verify broadcast_detection reaches a real connected WebSocket client.

    The existing test_broadcast_detection_with_socketio test asserts on a mock
    — this one asserts the event actually round-trips through Flask-SocketIO."""

    def test_broadcast_reaches_connected_client(self, ws_app):
        from core.api import broadcast_detection

        app, socketio = ws_app
        client = socketio.test_client(app)
        client.get_received()  # drain the connect 'status' event

        broadcast_detection({
            'common_name': 'American Robin',
            'scientific_name': 'Turdus migratorius',
            'confidence': 0.95,
        })

        received = client.get_received()
        bird_events = [e for e in received if e['name'] == 'bird_detected']
        assert len(bird_events) == 1
        payload = bird_events[0]['args'][0]
        assert payload['common_name'] == 'American Robin'
        assert payload['confidence'] == 0.95
        client.disconnect()


@contextmanager
def _auth_live_feed_ws_app():
    """Real SocketIO app with auth ENABLED and the live feed public.

    live_feed_public admits anonymous sockets, so an anonymous listener reaches
    the recorder_status decision — letting us assert it is admitted to the live
    feed yet never receives recorder_status, while an owner does.
    """
    settings = {
        'audio': {'recording_mode': 'pulseaudio'},
        'access': {'public_access': True, 'live_feed_public': True},
    }
    with sandboxed_auth_env(settings=settings, mock_socketio=False) as (api_module, _):
        app, socketio = api_module.create_app()
        app.config['TESTING'] = True
        # Seed the health the main container would have broadcast.
        api_module._recorder_status = _RECORDER_STATUS
        try:
            yield app, socketio, api_module
        finally:
            api_module._recorder_status = {}


class TestRecorderStatusOwnerOnly:
    """recorder_status is owner-only over the socket, matching the @require_auth
    /api/recorder/status REST route. It carries source labels and ffmpeg error
    text (which can echo RTSP credentials), so an anonymous live_feed listener
    must never receive it — on connect or on a later broadcast."""

    def test_owner_socket_receives_recorder_status_on_connect(self):
        with _auth_live_feed_ws_app() as (app, socketio, _):
            flask_client = app.test_client()
            flask_client.post('/api/auth/setup',
                              data=json.dumps({'password': AUTH_TEST_PASSWORD}),
                              content_type='application/json')  # enables auth + logs in
            owner = socketio.test_client(app, flask_test_client=flask_client)
            events = {e['name'] for e in owner.get_received()}
            assert 'recorder_status' in events
            owner.disconnect()

    def test_anonymous_socket_admitted_but_no_recorder_status(self):
        with _auth_live_feed_ws_app() as (app, socketio, _):
            # Enable auth (via an owner client), then connect a DIFFERENT,
            # unauthenticated client — admitted because live_feed is public.
            app.test_client().post('/api/auth/setup',
                                   data=json.dumps({'password': AUTH_TEST_PASSWORD}),
                                   content_type='application/json')
            anon = socketio.test_client(app, flask_test_client=app.test_client())
            assert anon.is_connected()
            received = anon.get_received()
            assert 'status' in {e['name'] for e in received}  # got the live feed
            assert 'recorder_status' not in {e['name'] for e in received}
            anon.disconnect()

    def test_broadcast_reaches_owner_not_anonymous(self):
        with _auth_live_feed_ws_app() as (app, socketio, api_module):
            flask_client = app.test_client()
            flask_client.post('/api/auth/setup',
                              data=json.dumps({'password': AUTH_TEST_PASSWORD}),
                              content_type='application/json')
            owner = socketio.test_client(app, flask_test_client=flask_client)
            anon = socketio.test_client(app, flask_test_client=app.test_client())
            owner.get_received()  # drain connect events
            anon.get_received()

            # Emit to the owner room exactly as broadcast_recorder_status_endpoint does.
            socketio.emit('recorder_status', _RECORDER_STATUS, room=api_module._OWNER_ROOM)

            owner_events = {e['name'] for e in owner.get_received()}
            anon_events = {e['name'] for e in anon.get_received()}
            assert 'recorder_status' in owner_events
            assert 'recorder_status' not in anon_events
            owner.disconnect()
            anon.disconnect()


class TestOwnerSocketRevocation:
    """Password changes must be enforced by the server, not client JavaScript."""

    def test_revoke_disconnects_owner_but_not_public_listener(self):
        with _auth_live_feed_ws_app() as (app, socketio, _):
            flask_client = app.test_client()
            flask_client.post('/api/auth/setup',
                              data=json.dumps({'password': AUTH_TEST_PASSWORD}),
                              content_type='application/json')
            owner = socketio.test_client(app, flask_test_client=flask_client)
            anon = socketio.test_client(app, flask_test_client=app.test_client())
            assert owner.is_connected()
            assert anon.is_connected()

            response = flask_client.post(
                '/api/auth/change-password',
                data=json.dumps({
                    'current_password': AUTH_TEST_PASSWORD,
                    'new_password': 'newpass456',
                }),
                content_type='application/json',
            )

            assert response.status_code == 200
            assert not owner.is_connected()
            assert anon.is_connected()
            anon.disconnect()
