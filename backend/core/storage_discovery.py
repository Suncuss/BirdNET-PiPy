"""Read the host service's device inventory, without accessing block devices."""
import json
import os
import time

from config.settings import BASE_DIR
from core.storage_devices import _protected_filesystems, describe_devices

SNAPSHOT_PATH = os.path.join(BASE_DIR, 'data/flags/storage-devices.json')
MAX_AGE_SECONDS = 60


def get_storage_devices():
    try:
        with open(SNAPSHOT_PATH) as stream:
            updated_at = os.fstat(stream.fileno()).st_mtime
            payload = json.load(stream)
        if time.time() - updated_at > MAX_AGE_SECONDS:
            return {'state': 'unavailable', 'devices': [],
                    'message': 'Drive discovery is not updating.'}
        return {'state': 'available', 'updated_at': updated_at,
                'devices': describe_devices(
                    payload.get('inventory', payload)['blockdevices'], _protected_filesystems(payload))}
    except FileNotFoundError:
        return {'state': 'unavailable', 'devices': [],
                'message': 'Drive discovery is not available on this installation.'}
    except (OSError, ValueError, KeyError, TypeError):
        return {'state': 'unavailable', 'devices': [],
                'message': 'Drive information could not be read.'}
