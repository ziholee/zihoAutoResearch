"""Review registration contract, with synthetic observations and no ML runs."""
import hashlib
import json

from test_cli import CliHarness
from test_experiments import ExperimentHarness


class ReviewTests(CliHarness):
    def setUp(self):
        super().setUp()
        self.init()

    def body(self, record_id='review-1', **changes):
        document = dict(id=record_id, supersedes_id=None, code_ref='code-1',
                        data_ref='data-1', items=[dict(
                            id='scope', topic='declared changes',
                            applicability='Synthetic code scope only',
                            observation='No real source inspected',
                            assessment='unverifiable', evidence=[],
                            limitation='No source evidence available',
                            next_action='Inspect source before running')])
        document.update(changes)
        return document

    def add(self, document=None, expected=0):
        return self.invoke('review', 'add', '--file',
                           str(self.write_input(document or self.body())), expected=expected)

    def review(self, record_id='review-1'):
        return self.stored.parent / 'reviews' / (record_id + '.json')

    def test_incomplete_project_accepts_review_and_generates_metadata(self):
        before = self.stored.read_bytes()
        body = self.body()
        output = self.add(body)
        saved = json.loads(self.review().read_text())
        self.assertEqual(output['data']['review'], saved)
        for key, value in body.items():
            self.assertEqual(saved[key], value)
        self.assertEqual(saved['schema_version'], 1)
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['created_at'], saved['updated_at'])
        self.assertTrue(saved['created_at'].endswith('Z'))
        self.assertIn('freshness_unknown', {d['code'] for d in output['diagnostics']})
        self.assertEqual(self.stored.read_bytes(), before)
        self.assertFalse(self.invoke('status')['data']['ready'])

    def test_duplicate_generated_fields_invalid_id_and_project_id_preserve_records(self):
        self.add()
        before = self.review().read_bytes()
        self.add(expected=3)
        for changes in ({'revision': 99}, {'created_at': '2026-01-01T00:00:00Z'},
                        {'id': '../outside'}, {'items': []}):
            with self.subTest(changes=changes):
                self.add(self.body(**changes), expected=2)
        self.add(self.body(json.loads(self.stored.read_text())['id']), expected=3)
        self.assertEqual(self.review().read_bytes(), before)
        self.assertEqual([p.name for p in self.review().parent.iterdir()], ['review-1.json'])

    def test_findings_require_proof_or_an_explicit_limitation_or_next_step(self):
        for assessment, field, expected in (
            ('confirmed_issue', 'evidence', 2), ('passed_in_scope', 'evidence', 2),
            ('unverifiable', 'limitation', 3), ('suspected', 'next_action', 3),
            ('not_applicable', 'applicability', 2),
        ):
            with self.subTest(assessment=assessment):
                body = self.body()
                body['items'][0]['assessment'] = assessment
                body['items'][0][field] = [] if field == 'evidence' else None if field in ('limitation', 'next_action') else ''
                self.add(body, expected=expected)
                self.assertFalse(self.review().exists())

    def test_missing_or_changed_evidence_remains_explicitly_unverified(self):
        source = self.project / 'review-proof.txt'
        original = b'synthetic inspected source\n'
        source.write_bytes(original)
        digest = hashlib.sha256(original).hexdigest()
        body = self.body()
        body['items'][0].update(assessment='passed_in_scope', evidence=[dict(
            kind='file', ref=source.name, locator='line 1', sha256=digest)])
        source.write_text('changed source\n')
        result = self.add(body)
        self.assertIn('evidence_changed', {d['code'] for d in result['diagnostics']})
        source.unlink()
        body['id'] = 'review-missing'
        result = self.add(body)
        self.assertIn('evidence_missing', {d['code'] for d in result['diagnostics']})
        saved = json.loads(self.review('review-missing').read_text())
        self.assertEqual(saved['items'][0]['evidence'][0]['sha256'], digest)

    def test_registered_hashed_evidence_can_be_read_and_rejects_later_changes(self):
        source = self.project / 'proof.txt'
        text = 'Synthetic scoped inspection\n'
        source.write_bytes(text.encode('utf-8'))
        body = self.body()
        body['items'][0].update(assessment='confirmed_issue', evidence=[dict(
            kind='file', ref=source.name, locator='line 1',
            sha256=hashlib.sha256(text.encode()).hexdigest())])
        self.add(body)
        before = self.review().read_bytes()
        arguments = ('evidence', 'read', '--kind', 'review', '--id', 'review-1',
                     '--pointer', '/items/0/evidence/0', '--revision', '1')
        output = self.invoke(*arguments)
        self.assertEqual(output['data']['text'], text)
        self.assertEqual(output['data']['source']['hash_state'], 'matched')
        source.write_text('Changed after review\n')
        result = self.invoke(*arguments, expected=3)
        self.assertIsNone(result['data'])
        self.assertEqual(self.review().read_bytes(), before)

    def test_correction_chain_preserves_original_and_rejects_branch_and_changed_identity(self):
        self.add()
        before = self.review().read_bytes()
        self.add(self.body('review-2', supersedes_id='review-1'))
        for changes in (
            {'supersedes_id': 'review-1'},
            {'supersedes_id': 'missing'},
            {'supersedes_id': 'review-3'},
            {'supersedes_id': 'review-2', 'code_ref': 'code-2'},
            {'supersedes_id': 'review-2', 'data_ref': 'data-2'},
        ):
            with self.subTest(changes=changes):
                self.add(self.body('review-3', **changes), expected=3)
                self.assertFalse(self.review('review-3').exists())
        self.add(self.body('review-3', supersedes_id='review-2'))
        self.assertEqual(self.review().read_bytes(), before)
        self.add(self.body('review-new-code', code_ref='code-2'))

    def test_review_does_not_rewrite_experiment_links_or_selection(self):
        settings = self.ready(json.loads(self.stored.read_text()))
        self.invoke('project', 'set', '--file', str(self.write_input(settings)))
        self.add()
        plan = ExperimentHarness.create(self, review_ids=['review-1'])
        self.invoke('experiment', 'create', '--file', str(self.write_input(plan)))
        experiment = self.stored.parent / 'experiments' / 'exp-1.json'
        experiment_before = experiment.read_bytes()
        project_before = self.stored.read_bytes()
        result = self.add(self.body('review-2', supersedes_id='review-1'))
        self.assertIn('review_superseded', {d['code'] for d in result['diagnostics']})
        self.assertEqual(experiment.read_bytes(), experiment_before)
        self.assertEqual(self.stored.read_bytes(), project_before)
        self.add(self.body('exp-1'), expected=3)
        self.assertFalse(self.review('exp-1').exists())
