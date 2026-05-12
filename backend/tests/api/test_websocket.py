"""WebSocket (Flask-SocketIO) regression tests.

These tests exercise the real Flask-SocketIO handshake — unlike the rest of the
API suite, they do NOT mock ``core.api.socketio``. The point is to catch
dependency-compat breakage between Flask and Flask-SocketIO (e.g. the
Flask 3.1.3 / Flask-SocketIO 5.5.1 ``RequestContext.session`` read-only crash
fixed in b6b0f26) before it ships.
"""
import os
import tempfile
from unittest.mock import patch

import pytest


@pytest.fixture
def ws_app():
    """Create a real Flask app with a real SocketIO instance (no mocks).

    Auth defaults to disabled (no auth.json in the temp dir), so the connect
    handler's feature gate passes without needing a logged-in session.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch('core.auth.AUTH_CONFIG_DIR', tmpdir), \
             patch('core.auth.AUTH_CONFIG_FILE', os.path.join(tmpdir, 'auth.json')), \
             patch('core.auth.RESET_PASSWORD_FILE', os.path.join(tmpdir, 'RESET_PASSWORD')), \
             patch('core.api.db_manager'):
            from core.api import create_app
            app, socketio = create_app()
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
