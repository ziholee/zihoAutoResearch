import json
import os
import stat
import subprocess
import sys
import unittest

from test_cli import CliHarness, REPO
from zar.storage import atomic_write


class ReviewFixTests(CliHarness):
    def test_json_output_on_legacy_encoding_after_save(self):
        document = self.init()
        document['name'] = '한국어 연구 🧪'
        source = self.write_input(document)
        env = {**os.environ, 'PYTHONIOENCODING': 'cp1252', 'PYTHONPATH': str(REPO)}
        result = subprocess.run([sys.executable, '-m', 'zar', 'project', 'set',
                                 '--file', str(source), '--project', str(self.project), '--json'],
                                env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['data']['project']['name'], document['name'])
        self.assertEqual(output['data']['project']['revision'], 2)

    @unittest.skipIf(os.name == 'nt', 'POSIX mode bits')
    def test_init_uses_normal_directory_permissions(self):
        normal = self.project / 'ordinary'
        normal.mkdir()
        self.init()
        self.assertEqual(stat.S_IMODE(self.stored.parent.stat().st_mode),
                         stat.S_IMODE(normal.stat().st_mode))

    @unittest.skipIf(os.name == 'nt', 'POSIX mode bits')
    def test_replacement_preserves_existing_permissions(self):
        self.init()
        self.stored.chmod(0o640)
        atomic_write(self.stored, self.stored.read_text())
        self.assertEqual(stat.S_IMODE(self.stored.stat().st_mode), 0o640)
