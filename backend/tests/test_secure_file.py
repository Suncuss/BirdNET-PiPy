"""Tests for private atomic configuration-file writes."""

import json
import os
import stat
import tempfile
from unittest.mock import patch

from core.secure_file import atomic_write_private_json


def test_json_temp_file_is_private_before_content_is_written():
    """The process umask must never expose secrets during the write window."""
    with tempfile.TemporaryDirectory() as tmpdir:
        destination = os.path.join(tmpdir, 'config.json')
        observed = {}
        original_dump = json.dump

        def inspect_mode_while_writing(payload, file_obj, **kwargs):
            observed['path'] = file_obj.name
            observed['mode'] = stat.S_IMODE(os.stat(file_obj.name).st_mode)
            return original_dump(payload, file_obj, **kwargs)

        old_umask = os.umask(0o022)
        try:
            with patch('core.secure_file.json.dump', side_effect=inspect_mode_while_writing):
                atomic_write_private_json(destination, {'password': 'secret'})
        finally:
            os.umask(old_umask)

        assert observed['path'] != destination
        assert observed['mode'] == 0o600
        assert stat.S_IMODE(os.stat(destination).st_mode) == 0o600
        with open(destination, encoding='utf-8') as file_obj:
            assert json.load(file_obj) == {'password': 'secret'}
        assert not os.path.exists(observed['path'])
