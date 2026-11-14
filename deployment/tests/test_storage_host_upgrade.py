"""Host-setup handoff checks with synthetic files; no drives are modified."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class HostUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        (self.project / 'deployment').mkdir(parents=True)
        self.source = (ROOT / 'deployment/birdnet-service.sh').read_text()
        self.source = self.source.removesuffix('main\n')
        # Relocate every host path; source the real runtime functions without
        # starting services, sudo, Docker or device commands.
        for original, target in (
            ('/usr/local/libexec/birdnet-pipy', self.root / 'libexec'),
            ('/etc/systemd/system', self.root / 'units'),
            ('/etc/birdnet-pipy', self.root / 'config'),
            ('/var/lib/birdnet-pipy', self.root / 'state'),
        ):
            self.source = self.source.replace(original, str(target))
        self.script = self.project / 'deployment/birdnet-service.sh'
        self.script.write_text(self.source)

    def run_shell(self, body):
        return subprocess.run(['bash', '-c',
            'source "$TEST_SCRIPT"\nPROJECT_ROOT="$TEST_PROJECT"\n' + body],
            env=dict(os.environ, TEST_SCRIPT=str(self.script), TEST_PROJECT=str(self.project)),
            capture_output=True, text=True, timeout=15, check=False)

    def test_first_restart_completes_setup_before_containers_without_another_update(self):
        result = self.run_shell(r'''
            host_storage_setup_current() { test -f "$PROJECT_ROOT/ready"; }
            git() { printf 'main\n'; }
            sudo() {
                printf 'sudo %s\n' "$*" >> "$PROJECT_ROOT/events"
                test "$*" = "-n $PROJECT_ROOT/install.sh --update --branch main --configure-host" || return 1
                touch "$PROJECT_ROOT/ready"
            }
            enable_swap_if_available() { :; }
            setup_audio_socket() { :; }
            start_containers() {
                test -f "$PROJECT_ROOT/ready" || return 1
                printf 'containers\n' >> "$PROJECT_ROOT/events"
            }
            monitor_flags() { :; }
            main
            ensure_host_storage_setup
            cat "$PROJECT_ROOT/events"
        ''')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        events = (self.project / 'events').read_text().splitlines()
        self.assertEqual(len(events), 2)
        self.assertTrue(events[0].endswith('--update --branch main --configure-host'))
        self.assertEqual(events[1], 'containers')

    def test_failure_does_not_stop_existing_recording(self):
        result = self.run_shell(r'''
            host_storage_setup_current() { return 1; }
            git() { printf 'main\n'; }
            sudo() { return 1; }
            enable_swap_if_available() { :; }
            setup_audio_socket() { :; }
            start_containers() { printf 'containers started\n'; }
            monitor_flags() { :; }
            main
        ''')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('Host storage setup failed', result.stdout)
        self.assertIn('Continuing recording without drive formatting', result.stdout)
        self.assertIn('containers started', result.stdout)

    def test_success_exit_without_complete_setup_is_reported(self):
        result = self.run_shell(r'''
            host_storage_setup_current() { return 1; }
            git() { printf 'main\n'; }
            sudo() { return 0; }
            ensure_host_storage_setup
        ''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('setup is incomplete', result.stdout)

    def prepare_current_setup(self):
        for name in ('libexec', 'units', 'config'):
            (self.root / name).mkdir()
        (self.project / 'backend/core').mkdir(parents=True)
        (self.project / 'data/flags').mkdir(parents=True)
        (self.project / 'data/flags/storage-format-available').touch()
        for name in ('storage-format.py', 'storage_mounts.py'):
            (self.project / 'deployment' / name).write_text('# synthetic helper\n')
            shutil.copyfile(self.project / 'deployment' / name, self.root / 'libexec' / name)
            (self.root / 'libexec' / name).chmod(0o755)
        (self.project / 'backend/core/storage_devices.py').write_text('# synthetic rules\n')
        shutil.copyfile(self.project / 'backend/core/storage_devices.py', self.root / 'libexec/storage_devices.py')
        (self.project / 'deployment/birdnet-media-mounts.service').write_text('# synthetic unit\n')
        shutil.copyfile(self.project / 'deployment/birdnet-media-mounts.service', self.root / 'units/birdnet-media-mounts.service')
        (self.project / 'deployment/birdnet-storage-format.service').write_text('# synthetic formatter unit\n')
        shutil.copyfile(self.project / 'deployment/birdnet-storage-format.service', self.root / 'units/birdnet-storage-format.service')
        template = '[Path]\nPathExists=@REQUEST_PATH@\n'
        (self.project / 'deployment/birdnet-storage-format.path').write_text(template)
        (self.root / 'units/birdnet-storage-format.path').write_text(template.replace(
            '@REQUEST_PATH@', str(self.project / 'data/flags/storage-format-request.json')))
        (self.root / 'config/storage-format.json').write_text(json.dumps({
            'project': str(self.project), 'flags': str(self.project / 'data/flags'),
            'uid': os.getuid(), 'gid': os.getgid(),
        }))
        (self.project / '.env').write_text(
            f'BIRDNET_MANAGED_MEDIA_PATH={self.root}/state/media\n'
            'BIRDNET_MANAGED_MEDIA_PROPAGATION=rslave\n')

    def test_current_setup_is_not_reinstalled(self):
        self.prepare_current_setup()
        result = self.run_shell('systemctl() { return 0; }; sudo() { return 0; }; ensure_host_storage_setup')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn('Installing host', result.stdout)

    def test_partial_or_outdated_setup_needs_refresh(self):
        self.prepare_current_setup()
        for relative in ('libexec/storage-format.py', 'libexec/storage_mounts.py',
                         'libexec/storage_devices.py', 'units/birdnet-media-mounts.service',
                         'config/storage-format.json', 'project/.env',
                         'units/birdnet-storage-format.service', 'units/birdnet-storage-format.path'):
            with self.subTest(file=relative):
                path = self.root / relative
                saved = path.read_bytes()
                path.write_text('stale or incomplete\n')
                result = self.run_shell('systemctl() { return 0; }; sudo() { return 0; }; host_storage_setup_current')
                self.assertNotEqual(result.returncode, 0)
                path.write_bytes(saved)
        for stub in ('systemctl() { return 1; }; sudo() { return 0; };',
                     'systemctl() { return 0; }; sudo() { return 1; };'):
            result = self.run_shell(stub + ' host_storage_setup_current')
            self.assertNotEqual(result.returncode, 0)


class InstallerHandoffTests(unittest.TestCase):
    def test_host_only_mode_uses_normal_setup_without_fetch_or_build(self):
        source = (ROOT / 'install.sh').read_text()
        source = source.replace('\nsetup_logging\n', '\n').replace('\nmain "$@"\n', '\n')
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'installer.sh'
            script.write_text(source)
            result = subprocess.run(['bash', '-c', r'''
                source "$1"
                detect_platform() { :; }; check_root() { :; }
                validate_install_user() { :; }; init_user_vars() { :; }
                setup_sudoers() { printf 'normal host setup\n'; }
                perform_update() { printf 'unexpected update\n'; exit 99; }
                IS_LOCAL_INSTALL=true
                main --update --branch main --configure-host
            ''', 'test', str(script)], capture_output=True, text=True, check=False, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('normal host setup', result.stdout)
        self.assertIn('no images fetched or built', result.stdout)
        self.assertNotIn('unexpected update', result.stdout)


if __name__ == '__main__':
    unittest.main()
