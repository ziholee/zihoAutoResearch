"""Public candidate rationale: recorded intentions are not observed winners."""
import json
from unittest.mock import patch
from test_experiments import ExperimentHarness
from zar.cli import main


class CandidateTests(ExperimentHarness):
    def body(self, identifier='candidate-1', **changes):
        value = dict(id=identifier, supersedes_id=None, status='selected',
                     hypothesis='Test records only', parent_id=None, analysis='Explore a synthetic change',
                     evidence=[], exploratory_reason='No prior observation; explicit exploratory test',
                     expected_effect='Unknown improvement; compare supplied mock observations',
                     expected_cost=dict(run_seconds=30, note='Author estimate; not measured resource use'),
                     uncertainty='Synthetic inputs only', decision_reason='Try this candidate within existing budget',
                     reconsideration=dict(trigger='initial', reason='No previous attempt'), memory_ids=[])
        value.update(changes)
        return value

    def add(self, value=None, expected=0):
        return self.invoke('candidate', 'add', '--file', str(self.write_input(value or self.body())), expected=expected)

    def candidate(self, identifier='candidate-1'):
        return self.stored.parent / 'candidates' / (identifier + '.json')

    def test_add_and_legacy_directory_preserve_budget_and_project(self):
        directory = self.candidate().parent
        if directory.exists(): directory.rmdir()
        before = self.stored.read_bytes()
        data = self.add()['data']['candidate']
        self.assertEqual(data['revision'], 1)
        self.assertEqual(data['conditions']['comparison']['id'], 'comparison-1')
        self.assertEqual(self.stored.read_bytes(), before)
        self.assertEqual(self.invoke('status')['data']['budget_used'], 0)
        self.assertIsNone(self.invoke('status')['data']['selected_experiment_id'])
        self.assertEqual(self.invoke('context')['data']['candidate_counts']['selected'], 1)

    def test_evidence_or_exploration_and_unused_ids_required(self):
        for changes, code in ((dict(exploratory_reason=None), 3), (dict(analysis=''), 2),
                              (dict(expected_cost=dict(run_seconds=-1, note='bad')), 2),
                              (dict(memory_ids=['missing']), 3), (dict(parent_id='missing'), 3),
                              (dict(revision=1), 2)):
            with self.subTest(changes=changes): self.add(self.body(**changes), expected=code)
        self.add(); self.add(expected=3)
        self.register(self.create('candidate-1'), expected=3)
        self.assertFalse(self.record('candidate-1').exists())

    def test_selected_version_binds_plan_and_preserves_forecasts(self):
        self.add(); before = self.candidate().read_bytes()
        self.register(self.create(candidate_id='candidate-1'))
        self.assertEqual(json.loads(self.record().read_text())['candidate_id'], 'candidate-1')
        self.add(self.body('candidate-2', supersedes_id='candidate-1', status='deferred',
                           decision_reason='Wait for more evidence'))
        self.assertEqual(self.candidate().read_bytes(), before)
        self.assertEqual(json.loads(self.record().read_text())['candidate_id'], 'candidate-1')
        self.invoke('check')
        self.register(self.create('retry', candidate_id='candidate-1'), expected=3)
        self.register(self.create('retry', candidate_id='candidate-2'), expected=3)
        doc = json.loads(self.record().read_text()); doc['candidate_id'] = None
        self.update(doc, expected=3)
        self.assertEqual(json.loads(self.record().read_text())['candidate_id'], 'candidate-1')

    def test_comparison_id_cannot_reuse_candidate_conditions(self):
        self.add()
        project = json.loads(self.stored.read_text())
        project['comparison']['id'] = 'comparison-2'
        self.invoke('project', 'set', '--file', str(self.write_input(project)))
        before = self.stored.read_bytes()
        project = json.loads(before)
        project['comparison']['id'] = 'comparison-1'
        project['comparison']['min_delta'] = 0.9
        self.invoke('project', 'set', '--file', str(self.write_input(project)), expected=3)
        self.assertEqual(self.stored.read_bytes(), before)

    def test_creation_rejects_changed_hypothesis_and_scope(self):
        self.add()
        self.register(self.create(candidate_id='candidate-1', hypothesis='Different hypothesis'), expected=3)
        project = json.loads(self.stored.read_text()); project['environment']['runtime'] = 'different runtime'
        self.invoke('project', 'set', '--file', str(self.write_input(project)))
        self.register(self.create(candidate_id='candidate-1'), expected=3)
        self.assertFalse(self.record().exists())

    def test_deferred_state_pages_and_retirement_preserve_originals(self):
        for index in range(7): self.add(self.body(f'candidate-{index}', status='deferred', analysis='분석' * 300))
        source = self.candidate().read_bytes()
        offset, seen, snapshot = 0, [], None
        while offset is not None:
            args = ['context', '--candidates', '--offset', str(offset), '--limit', '2', '--max-bytes', '8192']
            if snapshot: args += ['--snapshot', snapshot]
            result = self.invoke(*args); data = result['data']; snapshot = data['snapshot_id']
            from zar.codec import dumps
            self.assertLessEqual(len(dumps(result, ensure_ascii=True).encode('ascii')) + 1, 8192)
            self.assertEqual(data['candidate_counts']['deferred'], 7)
            self.assertTrue(all(c['truncated_fields'] for c in data['cards']))
            seen += [c['id'] for c in data['cards']]; offset = data['page']['next_offset']
        self.assertEqual(len(set(seen)), 7)
        self.add(self.body('candidate-retired', supersedes_id='candidate-1', status='retired'))
        self.assertEqual(self.candidate().read_bytes(), source)
        self.add(self.body('revived', supersedes_id='candidate-retired'), expected=3)
        self.invoke('context', '--candidates', '--snapshot', snapshot, expected=3)
        self.invoke('context', '--memories', '--candidates', expected=2)
        self.invoke('report', '--output', 'candidates.md')
        report = (self.stored.parent / 'reports/candidates.md').read_text()
        self.assertIn('candidate-retired', report)
        self.assertIn('.autoresearch/candidates/candidate-1.json', report)
        self.assertEqual(self.invoke('status')['data']['budget_used'], 0)

    def test_failed_first_write_and_symlink_are_safe(self):
        directory = self.candidate().parent; directory.rmdir()
        original = self.stored.read_bytes()
        with patch('zar.storage.os.replace', side_effect=OSError('mock write failure')):
            result = main(['candidate', 'add', '--file', str(self.write_input(self.body())), '--project', str(self.project), '--json'])
        self.assertEqual(result, 4); self.assertFalse(directory.exists())
        self.assertEqual(self.stored.read_bytes(), original)
        outside = self.root / 'outside'; outside.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
        self.add(expected=3)
        self.assertEqual(list(outside.iterdir()), [])
