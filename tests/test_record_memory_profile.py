"""Allocation diagnostics preserve evidence and never own loaded snapshots."""
import gc
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import threading
import unittest
import weakref

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/profile_record_memory.py'
PROFILE = runpy.run_path(str(SCRIPT))


class RecordMemoryProfileTests(unittest.TestCase):
    def test_snapshot_tracking_is_weak_and_background_is_ignored(self):
        class Snapshot:
            records = {'experiment': {'one': {}}}
        trace = PROFILE['MemoryTrace']()
        loaded = trace.wrap(Snapshot, 'load', record_load=True)()
        reference = weakref.ref(loaded)
        self.assertEqual(trace.events[-1]['live_snapshots'], 1)
        self.assertEqual(trace.events[-1]['live_record_documents'], 1)
        count = len(trace.events)
        thread = threading.Thread(target=lambda: trace.observe('background'))
        thread.start(); thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(trace.events), count)
        del loaded
        gc.collect()
        self.assertIsNone(reference())
        trace.observe('released')
        self.assertEqual(trace.events[-1]['live_snapshots'], 0)
        self.assertEqual(trace.events[-1]['live_record_documents'], 0)

    def test_exception_restores_load_scope_and_counts_only_inside_it(self):
        trace = PROFILE['MemoryTrace']()
        parse = trace.count(lambda: 7, 'records_parse')
        self.assertEqual(parse(), 7)
        self.assertEqual(trace.counts['records_parse'], 0)
        def fail():
            parse()
            raise ValueError('original')
        with self.assertRaisesRegex(ValueError, 'original'):
            trace.wrap(fail, 'load', record_load=True)()
        self.assertEqual(trace.load_depth, 0)
        self.assertEqual(trace.counts['record_loads'], 1)
        self.assertEqual(trace.counts['records_parse'], 1)
        self.assertEqual([e['phase'] for e in trace.events], ['load_begin', 'load_end'])

    def test_small_fresh_process_trace_preserves_cli_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'memory'
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
                '--source', str(ROOT), '--output', str(output), '--records', '2'],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(report['warmups'], 0)
            for operation, loads, calls in (('plan', 11, 5), ('resume', 6, 3)):
                trial = report['cases'][0]['operations'][operation]['trials'][0]
                trace = trial['allocation_trace']
                self.assertTrue(trial['validated'])
                self.assertEqual(trial['stderr_bytes'], 0)
                self.assertEqual(trial['model_calls'], calls)
                self.assertEqual(trace['counts'], dict(record_loads=loads,
                    records_read=loads * 2, records_parse=loads * 2, records_validate=loads * 2))
                events = trace['events']
                self.assertEqual(events[0]['phase'], 'worker_begin')
                self.assertEqual(events[-1]['phase'], 'worker_end')
                self.assertEqual(events[-1]['live_snapshots'], 0)
                self.assertEqual(sum(e['phase'] == 'provider_begin' for e in events), calls)
                self.assertEqual(sum(e['phase'] == 'context_begin' for e in events), calls)
                self.assertEqual(sum(e['phase'] == 'freshness_begin' for e in events), calls * 2)
                self.assertEqual(trace['peak_traced_bytes'], max(e['cumulative_peak_traced_bytes'] for e in events))
                self.assertTrue(all(e['cumulative_peak_traced_bytes'] >= e['current_traced_bytes'] >= 0 for e in events))
                allowed = {'phase', 'current_traced_bytes', 'cumulative_peak_traced_bytes',
                           'live_snapshots', 'live_record_documents'}
                self.assertTrue(all(set(e) == allowed for e in events))


if __name__ == '__main__':
    unittest.main()
