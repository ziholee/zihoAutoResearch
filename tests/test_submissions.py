"""Confirmed external-result records; no training or external submission calls."""
import copy
from contextlib import redirect_stdout
from decimal import Decimal
import hashlib
import io
import json
from unittest.mock import patch

from test_experiments import ExperimentHarness
from zar.codec import dumps, loads


class SubmissionTests(ExperimentHarness):
    def setUp(self):
        super().setUp()
        self.artifact = self.project / 'predictions.csv'
        self.artifact.write_bytes(b'id,prediction\n1,0.25\n')
        self.digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()
        self.register()
        document = self.success(json.loads(self.record().read_text()))
        document['execution']['artifacts'] = [dict(
            role='submission', path=self.artifact.name, sha256=self.digest,
            code_ref=document['code_ref'], config_ref=document['config_ref'],
            evidence=copy.deepcopy(document['execution']['evidence']))]
        self.update(document)

    def body(self, record_id='submission-1', **changes):
        document = dict(
            id=record_id, supersedes_id=None, experiment_id='exp-1',
            competition='synthetic-competition', external_id='external-123',
            artifact=dict(path=self.artifact.name, sha256=self.digest),
            leaderboard='public', metric='external-rmse', direction='minimize',
            score=Decimal('0.12345678901234567890123456789'),
            submitted_at='2026-01-01T00:02:00Z', observed_at='2026-01-01T00:03:00Z',
            evidence=[dict(kind='user_report', ref='Synthetic external score observation',
                           locator=None, sha256=None)])
        document.update(changes)
        return document

    def input(self, document):
        path = self.root / 'submission-input.json'
        path.write_text(dumps(document), encoding='utf-8')
        return path

    def add(self, document=None, expected=0):
        return self.invoke('submission', 'add', '--file',
                           str(self.input(document if document is not None else self.body())),
                           expected=expected)

    def submission(self, record_id='submission-1'):
        return self.stored.parent / 'submissions' / (record_id + '.json')

    def originals(self):
        return (self.stored.read_bytes(), self.record().read_bytes())

    def test_success_preserves_exact_decimal_originals_and_generates_metadata(self):
        before = self.originals()
        body = self.body()
        output = self.add(body)
        saved = loads(self.submission().read_text())
        self.assertEqual(output['data']['submission'], saved)
        for key, value in body.items():
            self.assertEqual(saved[key], value)
        self.assertEqual(saved['schema_version'], 1)
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['created_at'], saved['updated_at'])
        self.assertTrue(saved['created_at'].endswith('Z'))
        self.assertEqual(self.originals(), before)
        self.invoke('check')

    def test_requires_succeeded_experiment_and_exact_registered_submission_artifact(self):
        self.register(self.create('exp-planned'))
        self.register(self.create('exp-other'))
        doc = self.success(json.loads(self.record('exp-other').read_text()))
        doc['execution']['artifacts'] = [dict(
            role='model', path=self.artifact.name, sha256=self.digest,
            code_ref='code-1', config_ref='config-1', evidence=doc['execution']['evidence'])]
        self.invoke('experiment', 'update', 'exp-other', '--file', str(self.write_input(doc)))
        before = self.originals()
        for changes in (
            {'experiment_id': 'missing'}, {'experiment_id': 'exp-planned'},
            {'experiment_id': 'exp-other'},
            {'artifact': {'path': 'other.csv', 'sha256': self.digest}},
            {'artifact': {'path': self.artifact.name, 'sha256': '0' * 64}},
        ):
            with self.subTest(changes=changes):
                self.add(self.body(**changes), expected=3)
                self.assertFalse(self.submission().exists())
        self.assertEqual(self.originals(), before)

    def test_changed_existing_artifact_rejected_missing_artifact_warns(self):
        before = self.originals()
        self.artifact.write_bytes(b'changed predictions\n')
        self.add(expected=3)
        self.assertFalse(self.submission().exists())
        self.artifact.unlink()
        output = self.add()
        self.assertIn('evidence_missing', {d['code'] for d in output['diagnostics']})
        self.assertEqual(loads(self.submission().read_text())['artifact']['sha256'], self.digest)
        self.assertEqual(self.originals(), before)

    def test_duplicate_identity_ids_and_distinct_leaderboard(self):
        self.add()
        before = self.submission().read_bytes()
        self.add(expected=3)
        self.add(self.body('duplicate-identity'), expected=3)
        self.add(self.body('exp-1', external_id='another'), expected=3)
        self.add(self.body(json.loads(self.stored.read_text())['id'], external_id='another'), expected=3)
        from test_reviews import ReviewTests
        self.invoke('review', 'add', '--file', str(self.write_input(ReviewTests.body(self, 'review-1'))))
        self.add(self.body('review-1', external_id='another'), expected=3)
        self.add(self.body('submission-private', leaderboard='private'))
        self.assertEqual(self.submission().read_bytes(), before)
        self.assertEqual({p.stem for p in self.submission().parent.iterdir()},
                         {'submission-1', 'submission-private'})

    def test_correction_is_append_only_requires_active_same_identity(self):
        before = self.originals()
        self.add()
        original = self.submission().read_bytes()
        self.add(self.body('submission-2', supersedes_id='submission-1', score=Decimal('0.2')))
        corrected = self.submission('submission-2').read_bytes()
        for changes in (
            {'supersedes_id': 'submission-1'}, {'supersedes_id': 'missing'},
            {'supersedes_id': 'submission-3'},
            {'supersedes_id': 'submission-2', 'competition': 'other'},
            {'supersedes_id': 'submission-2', 'external_id': 'other'},
            {'supersedes_id': 'submission-2', 'leaderboard': 'private'},
        ):
            with self.subTest(changes=changes):
                self.add(self.body('submission-3', **changes), expected=3)
                self.assertFalse(self.submission('submission-3').exists())
        self.add(self.body('submission-3', supersedes_id='submission-2'))
        self.assertEqual(self.submission().read_bytes(), original)
        self.assertEqual(self.submission('submission-2').read_bytes(), corrected)
        self.assertEqual(self.originals(), before)
        self.invoke('check')

    def test_invalid_fields_rejected_without_writes(self):
        before = self.originals()
        for changes in (
            {'score': None}, {'score': '0.5'}, {'score': True}, {'evidence': []},
            {'submitted_at': 'yesterday'},
            {'revision': 9}, {'created_at': '2026-01-01T00:00:00Z'},
            {'id': '../outside'}, {'direction': 'larger'},
            {'artifact': {'path': self.artifact.name, 'sha256': None}},
        ):
            with self.subTest(changes=changes):
                self.add(self.body(**changes), expected=2)
                self.assertFalse(self.submission().exists())
        self.add(self.body(observed_at='2025-01-01T00:00:00Z'), expected=3)
        self.assertFalse(self.submission().exists())
        path = self.input(self.body())
        path.write_text(path.read_text().replace(str(self.body()['score']), 'NaN'))
        self.invoke('submission', 'add', '--file', str(path), expected=2)
        self.assertEqual(self.originals(), before)

    def test_failed_atomic_write_leaves_no_record_or_lock_and_allows_retry(self):
        from zar.cli import main
        before = self.originals()
        output = io.StringIO()
        arguments = ['submission', 'add', '--file', str(self.input(self.body())),
                     '--project', str(self.project), '--json']
        with patch('zar.storage.os.replace', side_effect=OSError('simulated disk error')):
            with redirect_stdout(output):
                code = main(arguments)
        self.assertEqual(code, 4)
        self.assertFalse(json.loads(output.getvalue())['ok'])
        self.assertEqual(self.originals(), before)
        self.assertEqual(list(self.submission().parent.iterdir()), [])
        self.assertFalse((self.stored.parent / '.lock').exists())
        self.add()
