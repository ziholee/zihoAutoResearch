"""Large-record boundaries retain the same padded indices and CLI contracts."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/benchmark_large_records.py'
BENCH = runpy.run_path(str(SCRIPT))


class LargeRecordTests(unittest.TestCase):
    def test_padding_keeps_three_positions_and_reports_real_utf8_sizes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / '.autoresearch/experiments'; directory.mkdir(parents=True)
            for i in range(65):
                (directory / f'exp-{i:06d}.json').write_text(json.dumps({'hypothesis': 'old'}), encoding='utf-8')
            result = BENCH['resize_records'](root, 9)
            self.assertEqual([x['index'] for x in result['large_records']], [0, 31, 62])
            self.assertEqual([x['hypothesis_utf8_bytes'] for x in result['large_records']], [9, 27, 36])
            self.assertEqual(json.loads((directory / 'exp-000064.json').read_text())['hypothesis'], 'old')
            self.assertEqual(result['total_file_bytes'], sum(p.stat().st_size for p in directory.glob('*.json')))

    def test_small_boundary_and_mixed_workers_preserve_bytes_and_cli_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'report'
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
                '--before', str(ROOT), '--after', str(ROOT), '--output', str(output),
                '--cases', '63', 'mixed', '--large-characters', '32', '--mixed-records', '63',
                '--mixed-sessions', '6', '--memory-characters', '100', '--repeats', '1'],
                capture_output=True, text=True, timeout=240)
            if result.returncode:
                private = '\n'.join(p.read_text(encoding='utf-8') for p in (output / 'private').glob('*.stderr'))
                self.fail(result.stdout + result.stderr + private)
            report = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual([c['key'] for c in report['cases']], ['63', 'mixed'])
            for case in report['cases']:
                self.assertTrue(case['digest_byte_equality_verified'])
                self.assertEqual(case['records']['records'], 63)
                for mode, section in case['digest'].items():
                    self.assertEqual(section['order'], [['before', 'after']])
                    for trials in section['trials'].values():
                        self.assertEqual(trials[0]['sha256'], case['digest_sha256'])
                        self.assertEqual(trials[0]['allocation'] is not None, mode == 'allocation')
                for mode, section in case['operations'].items():
                    self.assertEqual(section['order'], [['before', 'after']])
                    for trials in section['trials'].values():
                        self.assertTrue(trials[0]['validated'])
                        self.assertEqual(trials[0]['model_calls'], {'plan': 5, 'status': 0, 'resume': 3}[mode])

    def test_invalid_size_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'report'
            result = subprocess.run([sys.executable, str(SCRIPT), '--before', str(ROOT),
                '--after', str(ROOT), '--output', str(output), '--large-characters', '0'],
                capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
