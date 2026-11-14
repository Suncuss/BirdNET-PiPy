"""Synthetic mounts: fake commands and temporary directories, never real drives."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mounts', ROOT / 'deployment/storage_mounts.py')
mounts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mounts)
UUID = '12345678-1234-1234-1234-123456789abc'


class MountTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / 'media'
        self.registry = Path(self.temporary.name) / 'mounts.json'
        self.mountinfo = Path(self.temporary.name) / 'mountinfo'
        self.mountinfo.write_text('')
        self.mounted = set()
        self.shared = False
        self.commands = []
        for attribute, value in [('MEDIA_ROOT', self.root), ('REGISTRY', self.registry),
                                 ('MOUNTINFO', self.mountinfo)]:
            patcher = patch.object(mounts, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for attribute in ('fchown', 'fchmod'):
            patcher = patch.object(mounts.os, attribute)
            patcher.start()
            self.addCleanup(patcher.stop)
        # Reproduce the original failure: ismount misses same-filesystem binds.
        patcher = patch.object(mounts.os.path, 'ismount', return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def command(self, args, **_):
        self.commands.append(args)
        if args[0] == 'blkid':
            return UUID
        if args[:2] == ['mount', '--bind']:
            self.mounted.add(args[-1])
        elif args[:2] == ['mount', '--make-rshared']:
            self.shared = True
        elif args[:2] == ['mount', '--make-private']:
            self.shared = False
        elif args[0] == 'mount':
            self.mounted.add(args[-1])
        elif args[0] == 'findmnt':
            return ('shared' if self.shared else 'private') if args[-1] == 'PROPAGATION' else UUID
        self.mountinfo.write_text(''.join(
            f'{index} 0 0:1 / {path} rw - ext4 synthetic rw\n'
            for index, path in enumerate(sorted(self.mounted), 1)))
        return ''

    def test_new_drive_is_mounted_saved_and_given_service_user_access(self):
        result = mounts.mount_new_drive('/dev/sda1', 1000, 1001, self.command)
        self.assertEqual(result, '/managed-media/' + UUID)
        self.assertEqual(json.loads(self.registry.read_text()), [UUID])
        mounts.os.fchown.assert_called_once_with(unittest.mock.ANY, 1000, 1001)
        self.assertIn(['mount', '--make-rshared', str(self.root)], self.commands)
        self.assertIn(['mount', '-t', 'ext4', '-o', 'nosuid,nodev', 'UUID=' + UUID, str(self.root / UUID)], self.commands)

    def test_saved_drive_remounts_by_uuid_after_reboot(self):
        self.registry.write_text(json.dumps([UUID]))
        mounts.restore_mounts(1000, 1001, self.command)
        self.assertIn(str(self.root / UUID), self.mounted)
        # Repeated service startup must not stack another bind or drive mount.
        self.commands.clear()
        mounts.restore_mounts(1000, 1001, self.command)
        self.assertFalse(any(command[0] == 'mount' for command in self.commands))

    def test_missing_saved_drive_does_not_mount_or_block_startup(self):
        self.registry.write_text(json.dumps([UUID]))
        def missing(args, **kwargs):
            if args[0] == 'blkid':
                raise RuntimeError('not connected')
            return self.command(args, **kwargs)
        mounts.restore_mounts(1000, 1001, missing)
        self.assertFalse(any('UUID=' + UUID in command for command in self.commands))

    def test_wrong_mounted_identity_does_not_change_ownership_or_save_registry(self):
        def wrong(args, **kwargs):
            if args[0] == 'findmnt' and args[-1] == 'UUID':
                return 'another-drive'
            return self.command(args, **kwargs)
        with self.assertRaisesRegex(RuntimeError, 'identity'):
            mounts.mount_new_drive('/dev/sda1', 1000, 1001, wrong)
        mounts.os.fchown.assert_not_called()
        self.assertFalse(self.registry.exists())

    def test_invalid_uuid_cannot_become_a_mount_path(self):
        self.root.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'UUID'):
            mounts.mount_uuid('../../elsewhere', 1000, 1001, self.command)
        self.assertEqual(self.commands, [])

    def test_unreadable_mount_table_never_creates_a_mount(self):
        self.mountinfo.unlink()
        with self.assertRaises(OSError):
            mounts.prepare_root(self.command)
        self.assertEqual(self.commands, [])


class MountTableTests(unittest.TestCase):
    def test_shared_parent_is_detached_but_independent_group_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / 'mountinfo'
            target = Path(directory).resolve() / 'media'
            parent = '1 0 0:1 / / rw shared:1 - ext4 synthetic rw\n'
            with patch.object(mounts, 'MOUNTINFO', table):
                for group, expected in [('shared:1', True), ('shared:2', False), ('', False)]:
                    table.write_text(parent + f'2 1 0:1 / {target} rw {group} - ext4 synthetic rw\n')
                    self.assertEqual(mounts.shares_parent_peer_group(target), expected)

    def test_kernel_mount_lookup_decodes_escapes_and_matches_exact_path(self):
        with tempfile.TemporaryDirectory() as directory:
            table = Path(directory) / 'mountinfo'
            target = Path(directory).resolve() / 'media with spaces'
            escaped = str(target).replace(' ', r'\040')
            table.write_text(f'42 1 0:1 / {escaped} rw shared:1 - ext4 synthetic rw\n')
            with patch.object(mounts, 'MOUNTINFO', table):
                self.assertTrue(mounts.is_mountpoint(target))
                self.assertFalse(mounts.is_mountpoint(target / 'not-mounted'))
                self.assertFalse(mounts.is_mountpoint(target.parent))


class InstallerWiringTests(unittest.TestCase):
    def test_installs_root_helpers_and_prepares_mounts_before_containers(self):
        # Execute the real installer function against a fake filesystem and
        # command stubs. No privileged operations or drive commands can run.
        source = (ROOT / 'install.sh').read_text()
        function = source[source.index('install_storage_formatter() {'):source.index('setup_sudoers() {')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / 'project'
            (project / 'deployment').mkdir(parents=True)
            (project / 'backend/core').mkdir(parents=True)
            for name in ('storage-format.py', 'birdnet-media-mounts.service',
                         'birdnet-storage-format.service', 'birdnet-storage-format.path'):
                (project / 'deployment' / name).write_text('synthetic fixture\n')
            (project / 'backend/core/storage_devices.py').write_text('synthetic policy\n')
            (project / 'deployment/storage_mounts.py').write_text(
                '#!/bin/sh\nprintf "prepared\\n" >> "' + str(root / 'events') + '"\n')
            helper_dir = root / 'libexec'
            config_dir = root / 'config'
            units_dir = root / 'units'
            # Restrict every absolute installation destination to the sandbox.
            function = function.replace('/usr/local/libexec/birdnet-pipy', str(helper_dir))
            function = function.replace('/etc/birdnet-pipy', str(config_dir))
            function = function.replace('/etc/systemd/system', str(units_dir))
            function = function.replace('/var/lib/birdnet-pipy', str(root / 'state'))
            units_dir.mkdir()
            stub = root / 'install-stub.py'
            stub.write_text("""import os, pathlib, shutil, sys
args = sys.argv[1:]
assert args[0] in ('-d', '-o')
for flag in ('-o', '-g'):
    index = args.index(flag)
    expected = ('1000' if flag == '-o' else '1001') if args[-1].endswith('/data/flags') else 'root'
    assert args[index + 1] == expected
    del args[index:index + 2]
index = args.index('-m'); mode = int(args[index + 1], 8); del args[index:index + 2]
if args[0] == '-d':
    for path in args[1:]: pathlib.Path(path).mkdir(parents=True, exist_ok=True)
else:
    shutil.copyfile(*args); os.chmod(args[-1], mode)
""")
            script = root / 'install-test.sh'
            script.write_text('set -eu\n' +
                'install_prerequisites() { :; }\nprint_status() { :; }\n' +
                'set_env_var() { printf \'%s=%s\\n\' \"$1\" \"$2\" >> \"$PROJECT_ROOT/.env\"; }\n' +
                'chown() { :; }\nsystemctl() { printf "%s\\n" "$*" >> "' + str(root / 'events') + '"; }\n' +
                'install() { python3 "' + str(stub) + '" "$@"; }\n' +
                function + '\ninstall_storage_formatter\n')
            result = subprocess.run(['bash', str(script)], env=dict(os.environ,
                PROJECT_ROOT=str(project), ACTUAL_UID='1000', ACTUAL_GID='1001'),
                capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads((config_dir / 'storage-format.json').read_text())
            self.assertEqual((config['uid'], config['gid']), (1000, 1001))
            self.assertEqual((helper_dir / 'storage_mounts.py').stat().st_mode & 0o777, 0o755)
            self.assertIn('enable birdnet-media-mounts.service', (root / 'events').read_text())
            self.assertIn('prepared\n', (root / 'events').read_text())
            self.assertIn('enable --now birdnet-storage-format.path', (root / 'events').read_text())
            self.assertTrue((project / 'data/flags/storage-format-available').exists())
            self.assertIn('BIRDNET_MANAGED_MEDIA_PROPAGATION=rslave', (project / '.env').read_text())
        unit = (ROOT / 'deployment/birdnet-media-mounts.service').read_text()
        self.assertIn('Before=docker.service', unit)
        self.assertIn('WantedBy=docker.service', unit)
        install_stage = source[source.index('    # Application setup'):]
        self.assertLess(install_stage.index('    setup_sudoers'), install_stage.index('    pull_or_build'))


if __name__ == '__main__':
    unittest.main()
