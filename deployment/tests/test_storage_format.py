"""Synthetic formatter checks. No subprocesses, host inventories or block devices."""
import copy
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend/core'))
spec = importlib.util.spec_from_file_location('formatter', ROOT / 'deployment/storage-format.py')
formatter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(formatter)


class FormattingTests(unittest.TestCase):
    def setUp(self):
        self.disk = {'name': 'sda', 'path': '/dev/sda', 'type': 'disk', 'tran': 'usb',
                     'model': 'BIRDSTORE', 'serial': 'synthetic-A', 'size': 500000000000,
                     'maj:min': '8:0', 'children': [
                         {'name': 'sda1', 'path': '/dev/sda1', 'type': 'part',
                          'maj:min': '8:1', 'fstype': 'exfat', 'mountpoints': ['/media/usb']}]}
        self.protected = {r: {'179:2'} for r in ('application', 'database', 'settings')}
        drive = formatter.describe_devices([self.disk], self.protected)[0]
        self.request = {k: drive[k] for k in ('path', 'device_id')}
        self.request.update(confirmation=drive['name'])
        self.commands = []
        self.messages = []
        self.mounted = []

    def command(self, args, **kwargs):
        self.commands.append((args, kwargs))
        if args[0] == 'umount':
            self.disk['children'][0]['mountpoints'] = []
        if args[0] == 'sfdisk':
            self.disk['children'][0]['fstype'] = None
        if args[0] == 'mkfs.ext4':
            self.disk['children'][0]['fstype'] = 'ext4'
        if args[0] == 'blkid':
            return self.disk['children'][0].get('fstype') or ''
        return ''

    def discover(self, *_):
        return copy.deepcopy([self.disk]), copy.deepcopy(self.protected)

    def execute(self, **kwargs):
        formatter.format_drive(self.request, '/synthetic',
            lambda state, message: self.messages.append((state, message)),
            command=self.command, discover=kwargs.get('discover', self.discover), check_device=lambda _: None,
            mount_drive=self.mounted.append)

    def test_confirmed_drive_is_unmounted_partitioned_formatted_and_verified(self):
        self.execute()
        self.assertEqual([c[0][0] for c in self.commands], ['umount', 'sfdisk', 'udevadm', 'mkfs.ext4', 'blkid'])
        self.assertEqual(self.commands[1][1]['input'], 'label: gpt\n, , L\n')
        self.assertEqual(self.messages[-1][0], 'complete')
        self.assertIn('formatted and mounted', self.messages[-1][1])
        self.assertEqual(self.mounted, ['/dev/sda1'])

    def test_protected_or_replaced_drive_never_receives_commands(self):
        for change in ('protected', 'replaced'):
            with self.subTest(change=change):
                if change == 'protected':
                    self.protected['database'] = {'8:1'}
                else:
                    self.protected['database'] = {'179:2'}
                    self.disk['serial'] = 'synthetic-B'
                with self.assertRaises(RuntimeError):
                    self.execute()
                self.assertEqual(self.commands, [])

    def test_live_recheck_aborts_before_erasing_changed_drive(self):
        count = 0
        def discover(*_):
            nonlocal count
            count += 1
            if count == 2:
                self.disk['serial'] = 'replacement'
            return self.discover()
        with self.assertRaisesRegex(RuntimeError, 'information changed'):
            self.execute(discover=discover)
        self.assertEqual([c[0][0] for c in self.commands], ['umount'])

    def test_busy_drive_failure_stops_before_partitioning(self):
        def busy(*_, **__):
            raise RuntimeError('target is busy')
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            formatter.format_drive(self.request, '/synthetic', lambda *_: None,
                command=busy, discover=self.discover, check_device=lambda _: None, mount_drive=self.mounted.append)

    def test_incomplete_filesystem_verification_is_not_success(self):
        def command(args, **kwargs):
            result = self.command(args, **kwargs)
            if args[0] == 'mkfs.ext4':
                self.disk['children'][0]['fstype'] = None
            return result
        with self.assertRaisesRegex(RuntimeError, 'could not be verified'):
            formatter.format_drive(self.request, '/synthetic', lambda *_: None,
                command=command, discover=self.discover, check_device=lambda _: None, mount_drive=self.mounted.append)

    def test_mount_failure_is_reported_after_formatting_without_success(self):
        def fail_mount(_):
            raise RuntimeError('mount failed')
        with self.assertRaisesRegex(RuntimeError, 'formatted as ext4, but mounting setup failed'):
            formatter.format_drive(self.request, '/synthetic',
                lambda state, message: self.messages.append((state, message)),
                command=self.command, discover=self.discover, check_device=lambda _: None,
                mount_drive=fail_mount)
        self.assertNotIn('complete', [state for state, _ in self.messages])

    def test_live_collector_protects_media_mount_and_docker_storage(self):
        def command(args, **_):
            if args[0] == 'lsblk':
                return json.dumps({'blockdevices': [self.disk]})
            if args[:2] == ['docker', 'ps']:
                return 'synthetic-api'
            if args[:2] == ['docker', 'inspect']:
                return json.dumps({'labels': {'com.docker.compose.project.working_dir': '/synthetic'},
                                   'mounts': [{'Source': '/synthetic/data', 'Destination': '/app/data'},
                                              {'Source': '/media', 'Destination': '/external-media'},
                                              {'Source': str(formatter.MEDIA_ROOT), 'Destination': '/managed-media',
                                               'Propagation': 'rslave'}]})
            if args[:2] == ['docker', 'info']:
                return '/var/lib/docker'
            if args[0] == 'findmnt':
                return json.dumps({'filesystems': [{'maj:min': '8:1' if '/media/USB' in args else '179:2'}]})
            raise AssertionError(args)
        inventory, protected = formatter.live_inventory('/synthetic', command,
            settings_reader=lambda _: {'storage': {'media_target': '/external-media/USB'}})
        with self.assertRaisesRegex(RuntimeError, 'BirdNET data'):
            formatter.validate(self.request, inventory, protected)

    def test_interrupted_job_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            flags = Path(directory)
            journal = flags / 'journal.json'
            journal.write_text(json.dumps({'state': 'formatting', 'id': 'same', 'message': 'Formatting'}))
            request = flags / 'storage-format-request.json'
            request.write_text(json.dumps({'id': 'same', 'created_at': time.time()}))
            with patch.object(formatter, 'JOURNAL', journal), patch.object(formatter, 'format_drive') as perform:
                formatter.serve({'flags': str(flags), 'uid': flags.stat().st_uid})
            perform.assert_not_called()
            status = json.loads((flags / 'storage-format-status.json').read_text())
            self.assertEqual(status['state'], 'failed')
            self.assertIn('interrupted', status['message'])
            self.assertFalse(request.exists())

    def test_no_request_means_no_status_or_heartbeat_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            flags = Path(directory)
            journal = flags / 'journal.json'
            journal.write_text(json.dumps({'state': 'complete', 'id': 'previous'}))
            before = journal.stat().st_mtime_ns
            with patch.object(formatter, 'JOURNAL', journal), patch.object(formatter, 'format_drive') as perform:
                formatter.serve({'flags': str(flags), 'uid': flags.stat().st_uid})
            perform.assert_not_called()
            self.assertEqual(journal.stat().st_mtime_ns, before)
            self.assertFalse((flags / 'storage-format-status.json').exists())

    def test_completion_publishes_fresh_mount_inventory(self):
        self.disk['children'][0].update(fstype='ext4', mountpoints=['/managed-media/synthetic'])
        with tempfile.TemporaryDirectory() as directory:
            flags = Path(directory)
            (flags / 'storage-format-request.json').write_text(json.dumps(
                {'id': 'fresh-inventory', 'created_at': time.time()}))
            def complete(_request, _project, progress, **_kwargs):
                progress('complete', 'Drive formatted and mounted.')
            with patch.object(formatter, 'JOURNAL', flags / 'journal.json'), \
                    patch.object(formatter, 'format_drive', side_effect=complete), \
                    patch.object(formatter, 'live_inventory', return_value=self.discover()) as discover:
                formatter.serve({'flags': str(flags), 'uid': flags.stat().st_uid, 'project': '/synthetic'})
            discover.assert_called_once_with('/synthetic')
            status = json.loads((flags / 'storage-format-status.json').read_text())
            self.assertEqual(status['state'], 'complete')
            drive = status['storage_devices']['devices'][0]
            self.assertTrue(drive['mounted'])
            self.assertEqual(drive['filesystems'], ['ext4'])
            self.assertEqual(drive['mount_points'], ['/managed-media/synthetic'])

    def test_inventory_refresh_failure_does_not_report_formatting_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            flags = Path(directory)
            (flags / 'storage-format-request.json').write_text(json.dumps(
                {'id': 'refresh-failure', 'created_at': time.time()}))
            def complete(_request, _project, progress, **_kwargs):
                progress('complete', 'Drive formatted and mounted.')
            with patch.object(formatter, 'JOURNAL', flags / 'journal.json'), \
                    patch.object(formatter, 'format_drive', side_effect=complete), \
                    patch.object(formatter, 'live_inventory', side_effect=RuntimeError('inventory unavailable')):
                formatter.serve({'flags': str(flags), 'uid': flags.stat().st_uid, 'project': '/synthetic'})
            status = json.loads((flags / 'storage-format-status.json').read_text())
            self.assertEqual(status['state'], 'complete')
            self.assertNotIn('storage_devices', status)


if __name__ == '__main__':
    unittest.main()
