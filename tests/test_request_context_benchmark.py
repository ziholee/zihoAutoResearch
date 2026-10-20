"""Validate public measurement extraction without repeating expensive ML runs."""
import copy
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/benchmark_request_context.py'
MODULE = runpy.run_path(str(SCRIPT))


class RequestContextBenchmarkTests(unittest.TestCase):
    def fixture(self):
        components = {name: {'value': index, 'observations': 1}
                      for index, name in enumerate(MODULE['COMPONENTS'])}
        bucket = {'attempts': 1, 'input_message_bytes': {'value': 15, 'observations': 1},
                  'input_components_bytes': components}
        metrics = {'total': {'attempts': 7},
                   'roles': {role: copy.deepcopy(bucket) for role in MODULE['ROLES']}}
        return dict(state='complete', execution_count=2, resumed_without_execution=True,
                    mock_llm=True, actual_training=True, synthetic_data=True,
                    baseline_score=4.0, candidate_score=.1,
                    metrics={mode: copy.deepcopy(metrics) for mode in ('baseline', 'candidate')},
                    events='/private/unpublishable', baseline_experiment_id='private-id')

    def report(self, data):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / 'summary.json').write_text(json.dumps(data), encoding='utf-8')
            return MODULE['build_report'](path)

    def test_extracts_exact_observations_without_private_fields(self):
        result = self.report(self.fixture())
        self.assertEqual(result['requests'], 14)
        self.assertEqual(result['total_input_message_bytes'], 210)
        self.assertEqual(sum(result['total_input_components_bytes'].values()), 210)
        self.assertEqual([r['role'] for r in result['sessions']['candidate']], list(MODULE['ROLES']))
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('events', result)

    def test_rejects_missing_partial_invalid_or_mismatched_measurements(self):
        for change in ('missing', 'partial', 'boolean', 'observations_boolean', 'mismatch', 'retry'):
            data = self.fixture()
            bucket = data['metrics']['candidate']['roles']['review']
            if change == 'missing':
                del bucket['input_components_bytes']
            elif change == 'partial':
                bucket['input_components_bytes']['sources']['observations'] = 0
            elif change == 'boolean':
                bucket['input_components_bytes']['sources']['value'] = True
            elif change == 'observations_boolean':
                bucket['input_components_bytes']['sources']['observations'] = True
            elif change == 'mismatch':
                bucket['input_message_bytes']['value'] = 16
            else:
                bucket['attempts'] = 2
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.report(data)

    def test_requires_completed_mock_training_and_safe_resume(self):
        for key, value in (('state', 'observed'), ('execution_count', 3),
                           ('resumed_without_execution', False), ('mock_llm', False),
                           ('baseline_score', float('nan'))):
            data = self.fixture()
            data[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.report(data)

    def test_existing_output_refuses_before_launch_and_preserves_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            marker = output / 'keep'
            marker.write_text('user content', encoding='utf-8')
            with patch('subprocess.run') as run, self.assertRaises(FileExistsError):
                MODULE['benchmark'](output)
            run.assert_not_called()
            self.assertEqual(marker.read_text(encoding='utf-8'), 'user content')
            self.assertEqual(list(output.iterdir()), [marker])


if __name__ == '__main__':
    unittest.main()
