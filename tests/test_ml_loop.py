"""Actual regression fitting and persisted CLI lifecycle, with a loopback LLM only."""
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
EXAMPLE = ROOT / 'examples/ml-loop.py'


class MLLoopTests(unittest.TestCase):
    def invoke(self, output, *args, success=True):
        env = dict(os.environ)
        env['PYTHONPATH'] = str(ROOT)
        result = subprocess.run(
            [sys.executable, str(EXAMPLE), '--output', str(output), *args],
            cwd=output.parent, env=env, capture_output=True, text=True, timeout=90)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def test_fit_uses_training_labels_and_evaluator_uses_holdout(self):
        example = runpy.run_path(str(EXAMPLE))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'evaluate.py').write_text(example['EVALUATOR'], encoding='utf-8')
            (root / 'train.json').write_text(json.dumps([[0, 1], [1, 3], [2, 5]]))
            # The fitted train line predicts 7 and 9, while the holdout labels
            # deliberately disagree. Fitting on holdout or emitting a constant
            # metric cannot satisfy these independent expected losses.
            (root / 'holdout.json').write_text(json.dumps([[3, 8], [4, 11]]))
            for source, filename, expected in (
                ('BASELINE', 'baseline.json', 44.5),
                ('CANDIDATE', 'candidate.json', 2.5),
            ):
                (root / 'model.py').write_text(example[source], encoding='utf-8')
                result = subprocess.run([sys.executable, '-B', 'evaluate.py'], cwd=root,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads((root / filename).read_text())['mse'], expected)
            # Changing only training labels must change the trained prediction.
            (root / 'train.json').write_text(json.dumps([[0, 2], [1, 4], [2, 6]]))
            subprocess.run([sys.executable, '-B', 'evaluate.py'], cwd=root,
                           check=True, capture_output=True, text=True, timeout=10)
            self.assertEqual(json.loads((root / 'candidate.json').read_text())['mse'], .5)

    def test_pause_resume_preserves_baseline_and_compares_real_scores(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'demo'
            self.invoke(output, '--pause')
            project = output / 'project'
            read = lambda path: json.loads(path.read_text(encoding='utf-8'))
            checkpoint = read(output / 'checkpoint.json')
            self.assertEqual(checkpoint['state'], 'paused_after_observation')
            # Use public status events instead of assuming session storage layout.
            events = read(output / 'events.json')
            candidate_runs = [e for e in events if e['command'][:2] == ['research', 'run']]
            self.assertEqual(len(candidate_runs), 2)
            self.assertEqual(candidate_runs[-1]['response']['data']['state'], 'observed')
            records = project / '.autoresearch/experiments'
            baseline_path = records / (checkpoint['baseline_experiment_id'] + '.json')
            protected = {p: (project / p).read_bytes() for p in
                         ('evaluate.py', 'train.json', 'holdout.json', 'baseline.json', 'executions.jsonl')}
            baseline_record = baseline_path.read_bytes()
            self.assertEqual(len(protected['executions.jsonl'].splitlines()), 2)
            # A separately launched harness must reload persisted state. It may
            # interpret/select, but must not execute either learner again.
            self.invoke(output, '--resume')
            summary = read(output / 'summary.json')
            self.assertEqual(summary['state'], 'complete')
            for path, content in protected.items():
                self.assertEqual((project / path).read_bytes(), content, path)
            self.assertEqual(baseline_path.read_bytes(), baseline_record)
            train, holdout = read(project / 'train.json'), read(project / 'holdout.json')
            self.assertEqual(len(train), 96)
            self.assertEqual(len(holdout), 64)
            self.assertTrue(set(map(tuple, train)).isdisjoint(map(tuple, holdout)))
            # Recompute using raw moments, independently of the example's
            # centered covariance implementation and its reported summary.
            n = len(train)
            sx, sy = math.fsum(x for x, _ in train), math.fsum(y for _, y in train)
            slope = (n * math.fsum(x*y for x, y in train) - sx*sy) / (
                n * math.fsum(x*x for x, _ in train) - sx*sx)
            intercept = (sy - slope*sx) / n
            expected = {
                'baseline': math.fsum((sy/n-y)**2 for _, y in holdout) / len(holdout),
                'candidate': math.fsum((intercept+slope*x-y)**2 for x, y in holdout) / len(holdout),
            }
            for mode, score in expected.items():
                self.assertAlmostEqual(summary[mode + '_score'], score, places=12)
                self.assertAlmostEqual(read(project / (mode + '.json'))['mse'], score, places=12)
                record = read(records / (checkpoint[mode + '_experiment_id'] + '.json'))
                self.assertAlmostEqual(record['execution']['score'], score, places=12)
                self.assertEqual(record['decision']['status'], 'keep')
                metrics = summary['metrics'][mode]['total']
                self.assertEqual(metrics['attempts'], 7)
                self.assertIsNone(metrics['tokens']['total_tokens']['value'])
            self.assertGreater(expected['baseline'], expected['candidate'])
            self.assertAlmostEqual(summary['improvement'], expected['baseline']-expected['candidate'])
            candidate = read(records / (checkpoint['candidate_experiment_id'] + '.json'))
            self.assertEqual(candidate['baseline_id'], checkpoint['baseline_experiment_id'])
            config = read(project / '.autoresearch/project.json')
            self.assertEqual(config['selected_experiment_id'], checkpoint['candidate_experiment_id'])
            self.assertEqual(summary['execution_count'], 2)
            self.assertEqual(read(output / 'checkpoint.json')['state'], 'complete')
            self.invoke(output, '--resume', success=False)
            self.assertEqual((project / 'executions.jsonl').read_bytes(), protected['executions.jsonl'])

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
