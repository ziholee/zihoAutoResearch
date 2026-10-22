"""Small real-process scale protocol tests; no timing superiority gate."""
import copy
import json
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    BENCH = runpy.run_path(str(ROOT / 'scripts/benchmark_research_scale.py'))
finally:
    sys.path.pop(0)


class ResearchScaleTests(unittest.TestCase):
    def test_legacy_memory_oracle_does_not_hide_assessment_changes(self):
        original = dict(session_id='old', experiment_id='exp', created_at='then',
                        proposal={'lesson': 'one observation'})
        expected = [original]
        verify = BENCH['verify_legacy_lessons']
        verify(expected, expected)
        assessed = dict(original, assessment=dict(version=1, status='unassessed',
            claim_effect=None, observed_effect=None, reasons=['legacy_or_missing_assessment']))
        verify([assessed], expected)
        for changed in (dict(assessed, proposal={'lesson': 'different'}),
                        dict(assessed, assessment={**assessed['assessment'], 'status': 'verified'})):
            with self.assertRaises(AssertionError):
                verify([changed], expected)

    def test_normalization_keeps_actions_budgets_and_other_evidence(self):
        envelope = [{'ok': True, 'diagnostics': [], 'data': {
            'id': 'session-a', 'created_at': 'now', 'deadline': 123,
            'approval_token': 'token-a', 'max_calls': 9, 'error': None,
            'next_actions': [{'command': 'zar research approve session-a'}],
            'trace': [{'input_hash': 'hash-a', 'measurement': {
                'call_seconds': 0.1, 'input_message_bytes': 123}}],
            'prior': {'created_at': 'historical time'}}}]
        changed = copy.deepcopy(envelope)
        data = changed[0]['data']
        data.update(id='session-b', created_at='later', deadline=456, approval_token='token-b')
        data['next_actions'][0]['command'] = 'zar research approve session-b'
        data['trace'][0]['input_hash'] = 'hash-b'
        data['trace'][0]['measurement']['call_seconds'] = 0.9
        normalize = BENCH['normalize_cli_results']
        expected = normalize(envelope, 'session-a')
        self.assertEqual(normalize(changed, 'session-b'), expected)
        for field, value in (('max_calls', 10), ('error', 'changed'),
                             ('next_actions', [{'command': 'zar research run session-b'}]),
                             ('prior', {'created_at': 'changed history'})):
            modified = copy.deepcopy(changed)
            modified[0]['data'][field] = value
            self.assertNotEqual(normalize(modified, 'session-b'), expected)
        self.assertEqual(envelope[0]['data']['id'], 'session-a')

    def test_plan_query_and_interrupted_resume_preserve_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)
            seed = private / 'seed'
            lessons = BENCH['fixture'](ROOT, seed, 2, 6, private, 60)
            self.assertEqual([item['session_id'] for item in lessons],
                             ['session-' + format(i, '032x') for i in (4, 3, 2, 1, 0)])
            records = BENCH['records_digest'](seed)
            history = BENCH['history_digest'](seed)
            for mode in ('plan', 'status', 'resume'):
                root = private / mode
                shutil.copytree(seed, root)
                if mode != 'plan':
                    prepared = BENCH['run'](
                        ROOT, root, 'plan' if mode == 'status' else 'prepare',
                        private / (mode + '-preparation'), 60)
                    identifier = prepared['session_id']
                    (root / 'active-session.txt').write_text(identifier)
                    if mode == 'resume':
                        before = json.loads((root / '.autoresearch/sessions' /
                                             (identifier + '.json')).read_text())
                        self.assertEqual(list(before['outputs']), ['analysis', 'evaluation'])
                        self.assertEqual(before['calls'], 3)
                        self.assertEqual(before['max_calls'], 9)
                result = BENCH['run'](ROOT, root, mode, private / (mode + '-measured'), 60)
                raw = copy.deepcopy(result)
                BENCH['verify'](root, result, mode, lessons, records, history)
                self.assertTrue(result['validated'])
                self.assertEqual(result['model_calls'], {'plan': 5, 'status': 0, 'resume': 3}[mode])
                self.assertGreater(result['stdout_bytes'], 0)
                self.assertEqual(result['stderr_bytes'], 0)
                if result['peak_rss_bytes'] is not None:
                    self.assertGreater(result['peak_rss_bytes'], 0)
                # Verification must reject a changed historical record even if
                # the measured CLI operation itself returned success.
                history_file = root / '.autoresearch/sessions' / ('session-' + '0' * 32 + '.json')
                original = history_file.read_bytes()
                history_file.write_bytes(original + b' ')
                with self.assertRaises(AssertionError):
                    BENCH['verify'](root, copy.deepcopy(raw), mode, lessons, records, history)
                history_file.write_bytes(original)
                if raw['calls']:
                    corrupt = copy.deepcopy(raw)
                    corrupt['calls'][0]['prior_lessons'].reverse()
                    with self.assertRaises(AssertionError):
                        BENCH['verify'](root, corrupt, mode, lessons, records, history)


if __name__ == '__main__':
    unittest.main()
