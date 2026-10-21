"""Cost attribution is arithmetic, not a timing superiority assertion."""
from pathlib import Path
import json
import os
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest
import time
from unittest.mock import patch

from ci_cost_support import write_local_costs


ROOT = Path(__file__).resolve().parents[1]
PROFILER = runpy.run_path(str(ROOT / 'scripts/profile_local_cli.py'))
BENCHMARK = runpy.run_path(str(ROOT / 'scripts/benchmark_local_loop_costs.py'))


class LocalCostTimerTests(unittest.TestCase):
    def test_nested_categories_are_exclusive_including_same_category(self):
        timer = PROFILER['Timer']()
        leaf = timer.wrap(lambda: 17, 'validation')
        middle = timer.wrap(leaf, 'validation')
        outer = timer.wrap(middle, 'records')
        with patch.object(PROFILER['time'], 'perf_counter',
                          side_effect=[0, 1, 2, 4, 7, 10]):
            self.assertEqual(outer(), 17)
        self.assertEqual(timer.seconds, {'validation': 6, 'records': 4})
        self.assertEqual(timer.calls, {'validation': 2, 'records': 1})
        self.assertEqual(sum(timer.seconds.values()), 10)
        self.assertEqual(timer.stack, [])

    def test_failure_is_measured_without_suppressing_it(self):
        timer = PROFILER['Timer']()

        def fail():
            raise ValueError('original failure')

        with patch.object(PROFILER['time'], 'perf_counter', side_effect=[2, 5]):
            with self.assertRaisesRegex(ValueError, 'original failure'):
                timer.wrap(fail, 'storage')()
        self.assertEqual(timer.seconds, {'storage': 3})
        self.assertEqual(timer.calls, {'storage': 1})
        self.assertEqual(timer.stack, [])

    def test_background_calls_do_not_overlap_main_thread_partition(self):
        timer = PROFILER['Timer']()
        results = []
        thread = threading.Thread(target=lambda: results.append(
            timer.wrap(lambda: 7, 'validation')()))
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [7])
        self.assertEqual(timer.seconds, {})


class LocalCostReportTests(unittest.TestCase):
    def test_nested_diagnostics_and_milestones_are_not_added_twice(self):
        events = [
            {'kind': 'zar_cli', 'seconds': 10, 'profile': {
                'seconds': {'records': 2, 'validation': 1, 'other': 3},
                'calls': {'records': 1, 'validation': 2, 'other': 1},
                'startup_seconds': 2, 'entry_seconds': 0.5,
                'launcher_setup_seconds': 1.5}},
            {'kind': 'git', 'seconds': 3},
            {'kind': 'git_commit', 'seconds': 3},
            {'kind': 'provider', 'seconds': 1},
            {'kind': 'server_shutdown', 'seconds': 2},
        ]
        result = BENCHMARK['summarize'](events, 17)
        self.assertEqual(sum(result['partition_seconds'].values()), 17)
        self.assertEqual(result['partition_seconds']['worker_other'], 2)
        self.assertEqual(sum(result['cli_partition_seconds'].values()), 10)
        self.assertEqual(result['cli_partition_seconds']['launcher_exit_residual'], 2)
        with self.assertRaisesRegex(RuntimeError, 'Partial CLI profiling'):
            BENCHMARK['summarize'](events + [{'kind': 'zar_cli', 'seconds': 1}], 18)
        with self.assertRaises(RuntimeError):
            BENCHMARK['summarize'](events, 1)

    def test_real_profiled_and_unprofiled_workflows_preserve_evidence(self):
        diagnostic_started = time.perf_counter()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'costs'
            command = [sys.executable, str(ROOT / 'scripts/benchmark_local_loop_costs.py'),
                       '--output', str(output), '--repeats', '1']
            result = subprocess.run(command, cwd=temporary,
                                    env=dict(os.environ, PYTHONPATH=str(ROOT)),
                                    capture_output=True, text=True, timeout=540)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary, json.loads((output / 'summary.json').read_text()))
            for name, row in summary['trials'][0]['results'].items():
                self.assertTrue(row['verified']['verified'])
                self.assertEqual(row['verified']['execution_count'], 2)
                self.assertTrue(row['verified']['resumed_without_execution'])
                self.assertEqual(row['counts'], dict(
                    zar_cli=20, git=13, git_commit=4, approval=4,
                    provider=14, server_shutdown=2))
                self.assertAlmostEqual(sum(row['partition_seconds'].values()),
                                       row['total_seconds'])
                if name == 'profiled':
                    self.assertAlmostEqual(sum(row['cli_partition_seconds'].values()),
                                           row['partition_seconds']['cli'])
                    for category in ('records', 'validation', 'storage'):
                        self.assertGreater(row['cli_calls'][category], 0)
                    self.assertEqual(row['cli_calls']['git'], 0)
                else:
                    self.assertNotIn('cli_partition_seconds', row)
            # Refuse an existing output before changing its successful report.
            previous = (output / 'summary.json').read_bytes()
            retry = subprocess.run(command, cwd=temporary,
                                   env=dict(os.environ, PYTHONPATH=str(ROOT)),
                                   capture_output=True, timeout=10)
            self.assertNotEqual(retry.returncode, 0)
            self.assertEqual((output / 'summary.json').read_bytes(), previous)
            write_local_costs(summary, time.perf_counter() - diagnostic_started)


if __name__ == '__main__':
    unittest.main()
