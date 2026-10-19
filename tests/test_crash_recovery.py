"""Crash a real CLI process and inspect its durable recovery evidence."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / 'examples/crash-recovery.py'
SUPPORTED = sys.platform.startswith('linux') or sys.platform == 'darwin'


@unittest.skipUnless(SUPPORTED, 'Crash witness requires Linux waitpid or macOS kqueue')
class CrashRecoveryTests(unittest.TestCase):
    def invoke(self, output, *, success=True):
        self.assertTrue(EXAMPLE.is_file(), 'Crash recovery example is missing')
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        result = subprocess.run(
            [sys.executable, str(EXAMPLE), '--output', str(output)],
            cwd=output.parent, env=env, capture_output=True, text=True, timeout=120)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_killed_cli_retains_unknown_and_recovers_without_second_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'recovery'
            self.invoke(output)
            read = lambda path: json.loads(path.read_text(encoding='utf-8'))
            project = output / 'project'
            summary = read(output / 'summary.json')
            self.assertEqual(summary['state'], 'complete')
            records = list((project / '.autoresearch/experiments').glob('*.json'))
            self.assertEqual(len(records), 1)
            record = read(records[0])
            self.assertEqual(record['execution']['status'], 'interrupted')
            self.assertIsNone(record['execution']['score'])
            self.assertFalse((project / 'metric.json').exists())
            checkpoints = read(output / 'checkpoints.json')
            unknown = checkpoints['unknown']
            self.assertEqual(unknown['session']['state'], 'executing')
            self.assertEqual(unknown['experiment']['execution']['status'], 'unknown')
            self.assertEqual(checkpoints['after_denied'], unknown)
            self.assertEqual(read(output / 'unknown-experiment.json'), unknown['experiment'])
            self.assertEqual(record['id'], unknown['experiment']['id'])
            self.assertEqual(checkpoints['reconciled']['session']['state'], 'observed')
            self.assertEqual(checkpoints['reconciled']['session']['experiment_id'], record['id'])
            self.assertEqual(checkpoints['complete']['session']['state'], 'complete')
            self.assertEqual(record['decision']['status'], 'discard')
            self.assertEqual(record['execution']['evidence'][:len(unknown['experiment']['execution']['evidence'])],
                             unknown['experiment']['execution']['evidence'])
            ledger = project / 'executions.jsonl'
            launches = [json.loads(line) for line in ledger.read_text().splitlines()]
            self.assertEqual(len(launches), 1)
            receipt = read(project / 'recovery-evidence.json')
            self.assertEqual(launches[0]['pid'], receipt['child_pid'])
            self.assertEqual(launches[0]['event'], 'started')
            self.assertLess(receipt['cli_returncode'], 0)
            self.assertNotEqual(receipt['cli_pid'], receipt['child_pid'])
            self.assertTrue(receipt['child_exit_verified'])
            if sys.platform.startswith('linux'):
                self.assertEqual(receipt['child_exit_method'], 'subreaper-waitpid')
                self.assertEqual(receipt['child_exit_code'], 7)
            else:
                self.assertEqual(receipt['child_exit_method'], 'kqueue-note-exit')
                self.assertIsNone(receipt['child_exit_code'])
            # Check actual persisted evidence bytes, rather than trusting the
            # demonstration's same_experiment_id/unknown_preserved booleans.
            evidence = record['execution']['evidence']
            self.assertGreaterEqual(len(evidence), 2)
            refs = []
            for item in evidence:
                if item['kind'] == 'file':
                    path = project / item['ref']
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item['sha256'])
                    refs.append(path)
            self.assertIn(project / 'recovery-evidence.json', refs)
            events = read(output / 'events.json')
            denied = [event for event in events if event['returncode'] != 0]
            for command in (['research', 'run'], ['research', 'reconcile'],
                            ['experiment', 'update'], ['research', 'recover']):
                self.assertTrue(any(event['command'][:2] == command for event in denied), command)
            for event in denied:
                self.assertFalse(event['response']['ok'])
                self.assertTrue(any(d['severity'] == 'error' for d in event['response']['diagnostics']))
            states = [event['response']['data'] for event in events
                      if event['returncode'] == 0 and event['command'][:2] == ['research', 'status']]
            self.assertTrue(any(state['state'] == 'executing' for state in states))
            observed = next(state for state in reversed(states) if state['state'] == 'observed')
            self.assertEqual(observed['experiment_id'], record['id'])
            calling = checkpoints['calling']
            recovered = checkpoints['calling_recovered']
            retried = checkpoints['calling_retried']
            self.assertEqual(calling['state'], 'calling')
            self.assertEqual(calling['calls'], 1)
            self.assertEqual(recovered['state'], 'planning')
            self.assertEqual(recovered['calls'], 1)
            self.assertEqual(recovered['error'], 'previous_api_outcome_unknown')
            self.assertEqual(retried['state'], 'awaiting_approval')
            self.assertEqual(retried['calls'], 6)
            self.assertEqual(calling['id'], recovered['id'])
            self.assertEqual(calling['id'], retried['id'])
            self.assertIsNone(retried['experiment_id'])
            calling_denied = [event['command'] for event in denied
                              if len(event['command']) > 2 and event['command'][2] == calling['id']]
            self.assertIn(['research', 'advance', calling['id'], '--send'], calling_denied)
            self.assertIn(['research', 'recover', calling['id']], calling_denied)
            self.assertIn(['research', 'advance', calling['id']], calling_denied)
            # Retry in another real CLI process after reconciliation, and
            # independently prove the launch and records cannot be duplicated.
            session_path = project / '.autoresearch/sessions' / (observed['id'] + '.json')
            protected = {path: path.read_bytes() for path in (ledger, records[0], session_path)}
            result = subprocess.run(
                [sys.executable, '-m', 'zar', 'research', 'run', observed['id'],
                 '--project', str(project), '--json'], cwd=output.parent,
                env=dict(os.environ, PYTHONPATH=str(ROOT)), capture_output=True,
                text=True, timeout=10)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)['ok'])
            for path, original in protected.items():
                self.assertEqual(path.read_bytes(), original, str(path))

    def test_existing_output_is_refused_without_modification(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'existing'
            output.mkdir()
            marker = output / 'keep.txt'
            marker.write_text('user content', encoding='utf-8')
            self.invoke(output, success=False)
            self.assertEqual(list(output.iterdir()), [marker])
            self.assertEqual(marker.read_text(), 'user content')


if __name__ == '__main__':
    unittest.main()
