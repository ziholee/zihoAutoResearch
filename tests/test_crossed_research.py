"""Crossed execution keeps existing CLI evidence checks in each arm."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/benchmark_crossed_research.py'
BENCH = runpy.run_path(str(SCRIPT))


class CrossedResearchTests(unittest.TestCase):
    def test_arm_order_alternates_with_separate_warmup(self):
        self.assertEqual([BENCH['arm_order'](i) for i in range(4)],
            [['after', 'before'], ['before', 'after'], ['after', 'before'], ['before', 'after']])

    def test_small_cli_crossed_trials_preserve_evidence_and_report_pairs(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'report'
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
                '--before', str(ROOT), '--after', str(ROOT), '--output', str(output),
                '--small-records', '2', '--mixed-records', '2', '--mixed-sessions', '6',
                '--memory-characters', '16000', '--repeats', '1'],
                capture_output=True, text=True, timeout=120)
            if result.returncode:
                errors = '\n'.join(p.read_text(encoding='utf-8') for p in (output / 'private').glob('*.stderr'))
                self.fail(result.stdout + result.stderr + errors)
            report = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(report['source_digest']['before'], report['source_digest']['after'])
            self.assertEqual([c['key'] for c in report['cases']], ['small', 'mixed'])
            self.assertEqual([c['dimensions']['completed_sessions'] for c in report['cases']], [0, 6])
            for case in report['cases']:
                for mode, data in case['operations'].items():
                    self.assertEqual(data['order'], [['before', 'after']])
                    before, after = [data['trials'][label][0] for label in ('before', 'after')]
                    self.assertEqual(before['semantic_sha256'], after['semantic_sha256'])
                    for sample in (before, after):
                        self.assertTrue(sample['validated'])
                        self.assertEqual(sample['stderr_bytes'], 0)
                        self.assertEqual(sample['model_calls'], {'plan': 5, 'status': 0, 'resume': 3}[mode])
                    for field in BENCH['FIELDS']:
                        expected = after[field] - before[field] if after[field] is not None else None
                        self.assertEqual(data['after_minus_before'][0][field], expected)

    def test_invalid_counts_do_not_create_report(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'report'
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
                '--before', str(ROOT), '--after', str(ROOT), '--output', str(output),
                '--mixed-records', '0'], capture_output=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
