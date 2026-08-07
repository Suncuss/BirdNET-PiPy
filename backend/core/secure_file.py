"""Private, atomic persistence helpers for configuration files."""

import json
import os
import tempfile


def atomic_write_private_json(path, payload, *, fsync=False):
    """Write JSON through a unique owner-only file, then atomically publish it.

    ``mkstemp`` creates the file as ``0600`` before the first byte is written,
    independent of the process umask. Keeping it beside the destination makes
    ``os.replace`` atomic, and a unique name prevents concurrent writers from
    colliding on one predictable ``.tmp`` path.
    """
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix=f'.{os.path.basename(path)}.',
        suffix='.tmp',
        dir=directory,
        text=True,
    )

    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file_obj:
            fd = None
            json.dump(payload, file_obj, indent=2)
            if fsync:
                file_obj.flush()
                os.fsync(file_obj.fileno())
        os.replace(temp_path, path)
    except BaseException:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
        raise
