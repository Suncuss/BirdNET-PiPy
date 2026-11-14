"""Queue confirmed formatting for the installed host helper. No device access here."""
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

from config.settings import BASE_DIR

FLAGS = Path(BASE_DIR) / 'data/flags'


def format_pending():
    return (FLAGS / 'storage-format-request.json').exists()


def format_status():
    ready = (FLAGS / 'storage-format-available').is_file()
    try:
        payload = json.loads((FLAGS / 'storage-format-status.json').read_text())
        if not isinstance(payload, dict):
            raise ValueError('Invalid formatting status')
    except (OSError, ValueError, TypeError):
        payload = {'state': 'idle' if ready else 'unavailable',
                   'message': '' if ready else 'Drive formatting requires the updated host installer.'}
    payload['ready'] = ready
    try:
        pending = json.loads((FLAGS / 'storage-format-request.json').read_text())
        if payload.get('id') != pending['id']:
            payload.update(id=pending['id'], state='queued', message='Waiting for the host to format the drive…')
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return payload


def queue_format(payload):
    job = {key: payload[key] for key in ('path', 'device_id', 'confirmation')}
    job.update(id=uuid.uuid4().hex, created_at=time.time())
    path = FLAGS / 'storage-format-request.json'
    # Publish a complete file atomically, with exclusive creation across workers.
    fd, temporary = tempfile.mkstemp(prefix='.format-request-', dir=FLAGS)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(job, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)
    return {'id': job['id'], 'state': 'queued', 'message': 'Waiting for the host to format the drive…'}
