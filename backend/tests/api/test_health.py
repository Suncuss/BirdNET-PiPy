"""Tests for /api/health and create_app(async_mode=...)."""


def test_health_returns_ok_unauthenticated(api_client):
    """/api/health returns 200 {"status": "ok"} without auth."""
    resp = api_client.get('/api/health')
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'ok'}


def test_create_app_accepts_gevent_async_mode():
    """create_app(async_mode='gevent') wires the gevent driver into SocketIO."""
    # Do not `import wsgi`: its module-level monkey.patch_all() would
    # irreversibly patch the whole test process. Save/restore the module
    # global so the real SocketIO doesn't leak into other tests.
    import core.api as api_module

    saved = api_module.socketio
    try:
        app, sio = api_module.create_app(async_mode='gevent')
        assert sio.async_mode == 'gevent'
        assert app is not None
    finally:
        api_module.socketio = saved
