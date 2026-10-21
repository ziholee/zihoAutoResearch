"""Cost attribution is exclusive; instrumented and control CLI evidence agrees."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/profile_record_processing.py'
PROFILE = runpy.run_path(str(SCRIPT))


class RecordProcessingProfileTests(unittest.TestCase):
    def test_nested_and_exceptional_timings_are_exclusive(self):
        timer = PROFILE['Timer']()
        def fail():
            raise ValueError('original')
        inner = timer.wrap(fail, 'records_parse')
        outer = timer.wrap(inner, 'records_other')
        with patch.object(PROFILE['time'], 'perf_counter', side_effect=[0, 1, 3, 5]):
            with self.assertRaisesRegex(ValueError, 'original'):
                outer()
        self.assertEqual(timer.seconds['records_parse'], 2)
        self.assertEqual(timer.seconds['records_other'], 3)
        self.assertEqual(sum(timer.seconds.values()), timer.outer_seconds)
        self.assertEqual(timer.stack, [])
        same = PROFILE['Timer']()
        call = same.wrap(same.wrap(lambda: 1, 'serialize'), 'serialize')
        with patch.object(PROFILE['time'], 'perf_counter', side_effect=[0, 1, 3, 5]):
            self.assertEqual(call(), 1)
        self.assertEqual(same.seconds['serialize'], 5)
        self.assertEqual(same.calls['serialize'], 2)

    def test_background_work_does_not_corrupt_main_thread_partition(self):
        timer = PROFILE['Timer']()
        result = []
        worker = threading.Thread(target=lambda: result.append(timer.wrap(lambda: 7, 'serialize')()))
        worker.start(); worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [7])
        self.assertEqual(sum(timer.calls.values()), 0)

    def test_small_paired_profile_has_same_cli_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'profile'
            # -I ignores CI's PYTHONUTF8 environment setting; retain the
            # repository's UTF-8 mode explicitly in this isolated child.
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT), '--source', str(ROOT),
                '--output', str(output), '--records', '2', '--repeats', '1'],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((output / 'summary.json').read_text())
            for op, expected_reads in (('plan', 11), ('resume', 6)):
                trial = report['cases'][0]['operations'][op]['trials']
                control, profiled = trial['control'][0], trial['profiled'][0]
                self.assertEqual(control['semantic_sha256'], profiled['semantic_sha256'])
                self.assertTrue(control['validated'] and profiled['validated'])
                self.assertEqual(control['record_loads'], expected_reads)
                self.assertEqual(profiled['record_loads'], expected_reads)
                profile = profiled['profile']
                self.assertAlmostEqual(sum(profile['seconds'].values()), profile['body_seconds'])
                self.assertEqual(profile['calls']['records_read'], 2 * expected_reads)
                self.assertEqual(profile['calls']['records_parse'], 2 * expected_reads)
                self.assertEqual(profile['calls']['records_validate'], 2 * expected_reads)
                self.assertEqual(profile['calls']['projection_build'], 1)
                self.assertEqual(profile['calls']['snapshot_identity'], 1)
                self.assertEqual(profiled['stderr_bytes'], 0)
                self.assertIsNone(control['profile'])


if __name__ == '__main__':
    unittest.main()
