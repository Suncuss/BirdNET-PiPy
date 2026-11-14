"""Run the host collector with synthetic commands only, on any development OS."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class StorageEligibilityCollectorTest(unittest.TestCase):
    def test_protected_filesystems_follow_specific_container_mounts(self):
        script = Path(__file__).resolve().parents[1] / 'storage-discovery.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            binaries = root / 'bin'
            binaries.mkdir()
            mapping = {}
            mounts = []
            for destination, name, identity in [
                ('/app', 'application', '179:2'),
                ('/app/data', 'media', '8:1'),
                ('/app/data/db', 'database', '8:17'),
                ('/app/data/config', 'settings', '8:33'),
            ]:
                folder = root / name
                folder.mkdir()
                mounts.append(f'{destination}\t{folder}')
                mapping[str(folder)] = identity
            (root / 'mounts.txt').write_text('\n'.join(mounts) + '\n')
            (root / 'filesystems.json').write_text(json.dumps(mapping))
            inventory = {'blockdevices': [{'name': 'sda', 'type': 'disk', 'tran': 'usb',
                                           'size': 1000, 'maj:min': '8:0'}]}
            (root / 'inventory.json').write_text(json.dumps(inventory))
            programs = {
                'timeout': 'os.execvp(sys.argv[2], sys.argv[2:])',
                'realpath': 'print(str(Path(sys.argv[-1]).resolve()))',
                'lsblk': 'print((root / "inventory.json").read_text())',
                'docker': '''
if sys.argv[1:3] == ['compose', 'ps']:
    print('synthetic-api')
elif sys.argv[1] == 'inspect':
    print((root / 'mounts.txt').read_text(), end='')
else:
    raise AssertionError('Unexpected Docker operation: ' + str(sys.argv[1:]))
''',
                'findmnt': '''
path = sys.argv[sys.argv.index('--target') + 1]
mounts = json.loads((root / 'filesystems.json').read_text())
matching = [p for p in mounts if path == p or path.startswith(p + '/')]
identity = mounts[max(matching, key=len)]
print(json.dumps({'filesystems': [{'maj:min': identity}]}))
''',
            }
            for name, body in programs.items():
                program = binaries / name
                program.write_text(f'#!{sys.executable}\nimport os,sys,json\nfrom pathlib import Path\nroot=Path({str(root)!r})\n' + body + '\n')
                program.chmod(0o755)
            output = root / 'snapshot.json'
            env = {**os.environ, 'PATH': str(binaries) + os.pathsep + os.environ['PATH']}
            result = subprocess.run(['bash', str(script), str(output)], env=env,
                                    text=True, capture_output=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            snapshot = json.loads(output.read_text())
            self.assertEqual(snapshot['inventory'], inventory)
            for role, identity in [('application', '179:2'), ('database', '8:17'), ('settings', '8:33')]:
                self.assertEqual(snapshot['protected'][role][0]['filesystems'][0]['maj:min'], identity)
            # Media on /app/data is not mistaken for the separately mounted DB or config.
            protected_ids = {fs['maj:min'] for reports in snapshot['protected'].values()
                             for report in reports for fs in report['filesystems']}
            self.assertNotIn('8:1', protected_ids)


if __name__ == '__main__':
    unittest.main(verbosity=2)
