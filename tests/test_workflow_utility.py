"""Compare persisted paired workflows without asserting a performance winner."""
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/benchmark_workflow_utility.py'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WorkflowUtilityTests(unittest.TestCase):
    def invoke(self, output, *, repeats=2, success=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), '--output', str(output), '--repeats', str(repeats)],
            cwd=output.parent, env=dict(os.environ, PYTHONPATH=str(ROOT)),
            capture_output=True, text=True, timeout=180)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def expected_scores(self, project):
        train, holdout = read(project / 'train.json'), read(project / 'holdout.json')
        self.assertEqual(len(train), 96)
        self.assertEqual(len(holdout), 64)
        self.assertTrue(set(map(tuple, train)).isdisjoint(map(tuple, holdout)))
        # Raw moments, independent of the learner's centered-covariance fit.
        n = len(train)
        sx = math.fsum(x for x, _ in train)
        sy = math.fsum(y for _, y in train)
        slope = (n * math.fsum(x*y for x, y in train) - sx*sy) / (
            n * math.fsum(x*x for x, _ in train) - sx*sx)
        intercept = (sy - slope*sx) / n
        return {
            'baseline': math.fsum((sy/n-y)**2 for _, y in holdout) / len(holdout),
            'candidate': math.fsum((intercept+slope*x-y)**2 for x, y in holdout) / len(holdout),
        }

    def test_paired_workflows_preserve_measured_evidence_across_fresh_resume(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'comparison'
            self.invoke(output)
            summary = read(output / 'summary.json')
            self.assertEqual([trial['order'] for trial in summary['trials']],
                             [['direct', 'zar'], ['zar', 'direct']])
            for number in (1, 2):
                trial = output / ('trial-' + str(number))
                arm_evidence = {}
                responses = {}
                for arm in ('direct', 'zar'):
                    destination = trial / arm
                    project = destination / 'project'
                    expected = self.expected_scores(project)
                    checkpoint = read(destination / 'checkpoint.json')
                    evidence = read(destination / 'evidence.json')
                    self.assertEqual([row['mode'] for row in evidence], ['baseline', 'candidate'])
                    ledger = project / 'executions.jsonl'
                    self.assertEqual(ledger.read_bytes(), (destination / 'paused-executions.jsonl').read_bytes())
                    launches = [json.loads(line) for line in ledger.read_text().splitlines()]
                    self.assertEqual([row['metric_file'] for row in launches], ['baseline.json', 'candidate.json'])
                    baseline_path = project / checkpoint['baseline_record']
                    self.assertEqual(baseline_path.read_bytes(), (destination / 'paused-baseline-record.json').read_bytes())
                    for name in ('train.json', 'holdout.json', 'evaluate.py'):
                        self.assertEqual(sha(project / name), checkpoint['protected'][name])
                    for index, mode in enumerate(('baseline', 'candidate')):
                        entry = evidence[index]
                        record = read(project / checkpoint[mode + '_record'])
                        self.assertEqual(entry['id'], record['id'])
                        self.assertEqual(record['baseline_id'], None if mode == 'baseline' else evidence[0]['id'])
                        actual = record['score'] if arm == 'direct' else record['execution']['score']
                        self.assertAlmostEqual(actual, expected[mode], places=12)
                        self.assertEqual(actual, launches[index]['score'])
                        self.assertEqual(actual, read(project / (mode + '.json'))['mse'])
                        self.assertEqual(actual, entry['score'])
                        snapshot = project / 'evidence' / (mode + '-model.py')
                        self.assertEqual(sha(snapshot), entry['model_sha256'])
                        committed = subprocess.run(
                            ['git', 'show', entry['source_commit'] + ':model.py'],
                            cwd=project, check=True, capture_output=True, timeout=10).stdout
                        self.assertEqual(committed, snapshot.read_bytes())
                        # Final evidence/records must survive in Git, rather than
                        # existing only in disposable benchmark summary files.
                        archived = subprocess.run(
                            ['git', 'show', 'HEAD:evidence/' + mode + '-record.json'],
                            cwd=project, check=True, capture_output=True, timeout=10).stdout
                        self.assertEqual(archived, (project / checkpoint[mode + '_record']).read_bytes())
                    identities = subprocess.run(
                        ['git', 'log', '--format=%ae %ce'], cwd=project,
                        check=True, capture_output=True, text=True, timeout=10).stdout.splitlines()
                    self.assertEqual(identities, ['email@example.invalid email@example.invalid'] * 4)
                    events = read(destination / 'events.json')
                    provider = [event for event in events if event['kind'] == 'provider']
                    self.assertEqual(len(provider), 14)
                    self.assertEqual(sum(event['kind'] == 'approval' for event in events), 4)
                    responses[arm] = [event['response'] for event in provider]
                    arm_evidence[arm] = evidence
                self.assertEqual(responses['direct'], responses['zar'])
                for name in ('train.json', 'holdout.json', 'evaluate.py'):
                    self.assertEqual((trial / 'direct/project' / name).read_bytes(),
                                     (trial / 'zar/project' / name).read_bytes())
                for index in (0, 1):
                    for field in ('score', 'model_sha256', 'decision'):
                        self.assertEqual(arm_evidence['direct'][index][field], arm_evidence['zar'][index][field])
            # Prove the post-timing verifier detects corrupted primary evidence,
            # including duplicate launches even when result.json claims success.
            verify = runpy.run_path(str(SCRIPT))['verify_arm']
            for arm in ('direct', 'zar'):
                destination = output / 'trial-1' / arm
                path = destination / 'evidence.json'
                original = path.read_bytes()
                changed = read(path)
                changed[1]['score'] += 1
                path.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaises(RuntimeError):
                    verify(destination, arm)
                path.write_bytes(original)
                ledger = destination / 'project/executions.jsonl'
                original = ledger.read_bytes()
                ledger.write_bytes(original + original.splitlines(keepends=True)[0])
                with self.assertRaises(RuntimeError):
                    verify(destination, arm)
                ledger.write_bytes(original)
                verify(destination, arm)

    def test_existing_output_is_refused_without_modification(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'existing'
            output.mkdir()
            marker = output / 'keep.txt'
            marker.write_text('user content', encoding='utf-8')
            self.invoke(output, repeats=1, success=False)
            self.assertEqual(list(output.iterdir()), [marker])
            self.assertEqual(marker.read_text(), 'user content')


if __name__ == '__main__':
    unittest.main()
