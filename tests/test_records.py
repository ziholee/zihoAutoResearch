"""Invocation-scoped record snapshots and explicit metadata-only validation."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from zar.codec import loads, dumps
from zar.records import load_records
from zar.validation import inspect_project


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[1] / 'examples/contract-v1'
        self.project = loads((source / 'project.json').read_text())
        for kind in ('review', 'experiment', 'submission'):
            (self.root / '.autoresearch' / (kind + 's')).mkdir(parents=True)
        for name, kind in [('review', 'review'), ('baseline', 'experiment'),
                           ('candidate', 'experiment'), ('submission', 'submission')]:
            doc = loads((source / (name + '.json')).read_text())
            self.save(kind, doc)
        shutil.copytree(source / 'logs', self.root / 'logs')
        shutil.copyfile(source / 'submission-example.txt', self.root / 'submission-example.txt')

    def save(self, kind, doc):
        path = self.root / '.autoresearch' / (kind + 's') / (doc['id'] + '.json')
        path.write_text(dumps(doc))
        return path

    def test_snapshot_reuse_and_overlay_do_not_read_records_again(self):
        snapshot = load_records(self.root, self.project)
        original = copy.deepcopy(snapshot.records)
        exp = copy.deepcopy(snapshot.records['experiment']['exp-baseline'])
        exp['hypothesis'] = 'Updated hypothesis'
        with patch.object(Path, 'read_text', side_effect=AssertionError('Record reread')):
            self.assertFalse(any(d['severity'] == 'error' for d in inspect_project(self.root, self.project, snapshot=snapshot)))
            self.assertFalse(any(d['severity'] == 'error' for d in inspect_project(self.root, self.project, snapshot=snapshot, experiment=exp)))
            exp['id'] = 'exp-new'
            self.assertFalse(any(d['severity'] == 'error' for d in inspect_project(self.root, self.project, snapshot=snapshot, experiment=exp)))
        self.assertEqual(snapshot.records, original)

    def test_overlay_checks_schema_links_and_cross_kind_ids(self):
        snapshot = load_records(self.root, self.project)
        exp = copy.deepcopy(snapshot.records['experiment']['exp-baseline'])
        for id in ('review-1', self.project['id']):
            exp['id'] = id
            result = inspect_project(self.root, self.project, snapshot=snapshot, experiment=exp)
            self.assertTrue(any(d['message'] == 'Duplicate record ID' for d in result))
        exp['id'] = 'exp-new'
        exp['parent_id'] = 'missing'
        self.assertTrue(any(d['message'] == 'Invalid parent_id' for d in inspect_project(self.root, self.project, snapshot=snapshot, experiment=exp)))
        exp['execution'] = None
        self.assertTrue(any(d['code'] == 'schema' for d in inspect_project(self.root, self.project, snapshot=snapshot, experiment=exp)))

    def test_metadata_skips_files_but_not_submission_relationships(self):
        snapshot = load_records(self.root, self.project)
        (self.root / 'submission-example.txt').write_text('changed')
        full = inspect_project(self.root, self.project, snapshot=snapshot)
        self.assertTrue(any(d['code'] == 'conflict' and 'hash has changed' in d['message'] for d in full))
        with patch('zar.validation.hashlib.file_digest', side_effect=AssertionError('Hash read')), patch.object(Path, 'is_file', side_effect=AssertionError('File existence check')):
            metadata = inspect_project(self.root, self.project, snapshot=snapshot, check_files=False)
        self.assertEqual(sum(d['code'] == 'evidence_not_checked' for d in metadata), 1)
        self.assertFalse(any(d['severity'] == 'error' for d in metadata))
        exp = copy.deepcopy(snapshot.records['experiment']['exp-candidate'])
        exp['execution']['artifacts'] = []
        metadata = inspect_project(self.root, self.project, snapshot=snapshot, experiment=exp, check_files=False)
        self.assertTrue(any(d['message'] == 'Submission artifact does not match experiment artifact' for d in metadata))

    def test_loader_reports_bad_files_and_does_not_overlay_away_errors(self):
        directory = self.root / '.autoresearch/experiments'
        (directory / 'bad.json').write_bytes(b'\xff')
        (directory / 'invalid.json').write_text('{')
        (directory / 'link.json').symlink_to(directory / 'exp-baseline.json')
        snapshot = load_records(self.root, self.project)
        self.assertEqual(sum(d['code'] == 'json' for d in snapshot.diagnostics), 2)
        self.assertTrue(any(d['code'] == 'io' for d in snapshot.diagnostics))
        exp = copy.deepcopy(snapshot.records['experiment']['exp-baseline'])
        result = inspect_project(self.root, self.project, snapshot=snapshot, experiment=exp, check_files=False)
        self.assertTrue(any(d['code'] == 'json' for d in result))
        self.assertEqual(sum(d['code'] == 'evidence_not_checked' for d in result), 1)

    def test_loader_rejects_filename_duplicates_schema_and_symlink_directory(self):
        exp = loads((self.root / '.autoresearch/experiments/exp-baseline.json').read_text())
        alias = self.root / '.autoresearch/experiments/alias.json'
        alias.write_text(dumps(exp))
        bad = copy.deepcopy(exp)
        bad['id'] = 'bad-schema'
        bad['execution'] = None
        self.save('experiment', bad)
        cross_kind = copy.deepcopy(exp)
        cross_kind['id'] = 'review-1'
        self.save('experiment', cross_kind)
        snapshot = load_records(self.root, self.project)
        self.assertTrue(any(d['message'] == 'Filename does not match record ID' for d in snapshot.diagnostics))
        self.assertGreaterEqual(sum(d['message'] == 'Duplicate record ID' for d in snapshot.diagnostics), 2)
        self.assertTrue(any(d['code'] == 'schema' for d in snapshot.diagnostics))
        self.assertNotIn('bad-schema', snapshot.records['experiment'])
        review_dir = self.root / '.autoresearch/reviews'
        moved = self.root / 'reviews'
        review_dir.rename(moved)
        review_dir.symlink_to(moved, target_is_directory=True)
        snapshot = load_records(self.root, self.project)
        self.assertEqual(snapshot.records['review'], {})
        self.assertTrue(any(d['code'] == 'io' and d['path'] == str(review_dir) for d in snapshot.diagnostics))

    def test_full_validation_rechecks_file_hashes_on_same_snapshot(self):
        snapshot = load_records(self.root, self.project)
        self.assertFalse(any(d['severity'] == 'error' for d in inspect_project(self.root, self.project, snapshot=snapshot)))
        (self.root / 'submission-example.txt').write_text('changed after first validation')
        self.assertTrue(any(d['code'] == 'conflict' and 'hash has changed' in d['message'] for d in inspect_project(self.root, self.project, snapshot=snapshot)))

    def test_metadata_retains_schema_and_state_conflicts(self):
        snapshot = load_records(self.root, self.project)
        exp = copy.deepcopy(snapshot.records['experiment']['exp-baseline'])
        exp['execution']['exit_code'] = 1
        full = inspect_project(self.root, self.project, snapshot=snapshot, experiment=exp)
        metadata = inspect_project(self.root, self.project, snapshot=snapshot, experiment=exp, check_files=False)
        self.assertEqual([d for d in full if d['severity'] == 'error'], [d for d in metadata if d['severity'] == 'error'])
