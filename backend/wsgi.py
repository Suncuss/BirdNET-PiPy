"""Gunicorn WSGI entrypoint.

gevent's monkey.patch_all() rewrites the stdlib (socket, ssl, select, time,
threading) in place. It MUST run before requests/flask/sqlite3/core.api are
imported, or the gevent worker blocks on network/sleep calls. Do not add any
import above the patch.
"""
from gevent import monkey

monkey.patch_all()

from core.api import create_app

application, socketio = create_app(async_mode='gevent')
