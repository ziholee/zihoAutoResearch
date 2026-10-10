"""Exercise the published example through its command line, never ML."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal

from zar.codec import loads


REPO = Path(__file__).resolve().parents[1]


class MockCycleTests(unittest.TestCase):
    def run_example(self, destination, scenario='comparable', expected=0):
        environment = os.environ.copy()
        environment['PYTHONPATH'] = os.pathsep.join((str(REPO), environment.get('PYTHONPATH', '')))
        result = subprocess.run(
            [sys.executable, str(REPO / 'examples/mock-cycle.py'), '--output', str(destination),
             '--scenario', scenario], cwd=destination.parent, env=environment,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return loads(result.stdout) if expected == 0 else result

    def test_comparable_cycle_adopts_without_running_training(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'cycle with spaces'
            summary = self.run_example(output)
            self.assertTrue(summary['simulated'])
            self.assertTrue(summary['comparison']['comparable'])
            self.assertEqual(summary['comparison']['improvement'], Decimal('0.1'))
            self.assertEqual(summary['selected_experiment_id'], 'mock-candidate')
            self.assertTrue(summary['workspace_matches_selection'])
            self.assertEqual(summary['unfinished'], [])
            self.assertEqual(summary['budget_used'], 2)
            self.assertEqual(list(output.rglob('TRAINING_WAS_EXECUTED')), [])
            self.assertEqual(loads((output / 'summary.json').read_text()), summary)
            context = loads((output / 'context.json').read_text())
            self.assertEqual(context['selected_experiment_id'],'mock-candidate')
            self.assertFalse(context['safeguards']['evidence_checked'])
            page = loads((output / 'evidence-page.json').read_text())
            raw_log = (output / 'project/.autoresearch/evidence/mock-candidate.txt').read_bytes()
            self.assertEqual(page['text'], b''.join(raw_log.splitlines(keepends=True)[:2]).decode('utf-8'))
            self.assertEqual(page['source']['hash_state'],'matched')
            store = output / 'project/.autoresearch'
            baseline = loads((store / 'experiments/mock-baseline.json').read_text())
            candidate = loads((store / 'experiments/mock-candidate.json').read_text())
            self.assertEqual(baseline['decision']['status'], 'keep')
            self.assertEqual(candidate['review_ids'], ['mock-candidate-review'])
            self.assertTrue((store / 'submissions/mock-submission.json').is_file())
            report = Path(summary['report']).read_text()
            self.assertIn('mock-submission', report)
            self.assertIn('mock-candidate-review', report)
            self.assertIn('1.15', report)
            self.assertEqual(candidate['baseline_id'], baseline['id'])
            self.assertEqual(len(candidate['decision_history']), 1)
            self.assertNotEqual(baseline['code_ref'], candidate['code_ref'])
            events = loads((output / 'events.json').read_text())['events']
            self.assertTrue(all(e['exit_code'] == 0 for e in events))
            self.assertEqual(events[-2]['arguments'], ['check'])
            self.assertFalse(any(d['severity'] == 'error' for e in events for d in e['result']['diagnostics']))

    def test_scope_mismatch_holds_and_preserves_baseline_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'cycle'
            summary = self.run_example(output, 'scope-mismatch')
            self.assertFalse(summary['comparison']['comparable'])
            self.assertIsNone(summary['comparison']['improvement'])
            self.assertIn('scope_mismatch', summary['comparison']['reasons'])
            self.assertEqual(summary['decision']['status'], 'hold')
            self.assertEqual(summary['decision']['validity'], 'not_comparable')
            self.assertEqual(summary['selected_experiment_id'], 'mock-baseline')
            self.assertFalse(summary['workspace_matches_selection'])
            self.assertTrue(summary['next_action'])
            self.assertEqual(summary['unfinished'], [])
            self.assertEqual(list(output.rglob('TRAINING_WAS_EXECUTED')), [])

    def test_existing_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'existing'
            output.mkdir()
            marker = output / 'user.txt'
            marker.write_bytes(b'user content')
            self.run_example(output, expected=1)
            self.assertEqual(marker.read_bytes(), b'user content')
            self.assertEqual(list(output.iterdir()), [marker])
