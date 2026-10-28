"""Fixed evaluation and non-transmitted input identity across research boundaries."""
import json
import os
import unittest
from unittest.mock import patch

from zar import research
from zar.codec import dumps, loads
import test_research as fixtures


class FileProvenanceResearchTests(unittest.TestCase):
    start = fixtures.ResearchTests.start
    respond = fixtures.ResearchTests.respond
    planned = fixtures.ResearchTests.planned

    def setUp(self):
        fixtures.ResearchTests.setUp(self)
        self.sentinel = 'PRIVATE-EVALUATOR-CONTENT-DO-NOT-TRANSMIT'
        (self.root / 'evaluate.py').write_text(self.sentinel)
        (self.root / 'data.bin').write_bytes(b'\x00private-binary-data\xff')
        project = research.get_project(self.root)
        project['file_contract'] = dict(version=1, evaluation_paths=['evaluate.py'], provenance_paths=['data.bin'])
        (self.root / '.autoresearch/project.json').write_text(dumps(project))

    def change(self):
        path = self.root / 'evaluate.py'
        stamp = path.stat()
        path.write_text('X' * len(self.sentinel))
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    def approved(self):
        s = self.planned()
        research.approve(self.root, s['id'], s['approval_token'])
        return s

    def decision(self):
        s = self.approved()
        research.run_session(self.root, s['id'])
        with patch('zar.research.chat', side_effect=self.respond):
            return research.advance(self.root, s['id'], send=True)

    def test_untransmitted_files_have_hashes_but_never_raw_content(self):
        s = self.start()
        self.assertIn('file_manifest', s)
        self.assertEqual(set(s['sources']), {'train.py'})
        self.assertNotIn(self.sentinel, dumps(s))
        with patch('zar.research.chat', side_effect=self.respond) as chat:
            research.advance(self.root, s['id'], send=True)
        for call in chat.call_args_list:
            self.assertNotIn(self.sentinel, json.dumps(call.args[1]))
            self.assertNotIn('private-binary-data', json.dumps(call.args[1]))

    def test_nontransmitted_change_blocks_approval_and_run_before_writes(self):
        s = self.planned()
        self.change()
        with self.assertRaises(research.ResearchError):research.approve(self.root, s['id'], s['approval_token'])
        (self.root / 'evaluate.py').write_text(self.sentinel)
        research.approve(self.root, s['id'], s['approval_token'])
        self.change()
        with patch('zar.research.run') as run:
            with self.assertRaises(research.ResearchError):research.run_session(self.root, s['id'])
            run.assert_not_called()
        self.assertFalse((self.root / 'metric.json').exists())
        self.assertEqual(list((self.root / '.autoresearch/experiments').glob('*.json')), [])

    def test_change_during_call_blocks_response_and_following_role(self):
        s = self.start()
        def answer(profile, messages):
            self.change()
            return self.respond(profile, messages)
        with patch('zar.research.chat', side_effect=answer) as chat:
            with self.assertRaises(research.ResearchError):research.advance(self.root, s['id'], send=True)
            self.assertEqual(chat.call_count, 1)
        saved = research.load(self.root, s['id'])
        self.assertEqual(saved['state'], 'blocked')
        self.assertEqual(saved['outputs'], {})

    def test_changed_input_during_successful_process_rejects_score(self):
        s = self.approved()
        real = research.run
        def run(*args, **kwargs):
            result = real(*args, **kwargs)
            self.change()
            return result
        with patch('zar.research.run', side_effect=run):
            result = research.run_session(self.root, s['id'])
        experiment = loads((self.root / '.autoresearch/experiments' / (result['experiment_id'] + '.json')).read_text())
        self.assertEqual(experiment['execution']['status'], 'failed')
        self.assertEqual(experiment['execution']['exit_code'], 0)
        self.assertIsNone(experiment['execution']['score'])
        self.assertEqual(experiment['file_manifest'], s['file_manifest'])
        self.assertTrue(any('file-manifest' in e['ref'] for e in experiment['execution']['evidence']))

    def test_deleted_input_during_unknown_process_preserves_unknown(self):
        s = self.approved()
        def unknown(*args, **kwargs):
            (self.root / 'data.bin').unlink()
            return dict(status='unknown', started_at='2026-10-28T00:00:00Z', finished_at=None,
                        exit_code=None, note='Synthetic stop not confirmed')
        with patch('zar.research.run', side_effect=unknown):
            result = research.run_session(self.root, s['id'])
        self.assertEqual(result['state'], 'unknown')
        with self.assertRaises(research.ResearchError):research.run_session(self.root, s['id'])

    def test_changed_input_blocks_decision_recovery(self):
        s = self.decision()
        with patch('zar.research.finish_decision', side_effect=OSError('simulated crash')):
            with self.assertRaises(OSError):research.decide(self.root, s['id'], s['approval_token'])
        self.change()
        with self.assertRaises(research.ResearchError):research.recover(self.root, s['id'], confirm_stopped=True)
        self.assertEqual(research.load(self.root, s['id'])['state'], 'deciding')

    def test_reconcile_cannot_rebase_changed_fixed_input(self):
        s = self.approved()
        result = research.run_session(self.root, s['id'])
        saved = research.load(self.root, s['id'])
        saved['state'] = 'unknown'
        research.save(self.root, saved)
        self.change()
        with self.assertRaises(research.ResearchError):research.reconcile(self.root, s['id'])
        self.assertEqual(research.load(self.root, s['id'])['state'], 'unknown')

    def test_missing_manifest_cannot_downgrade_configured_session(self):
        s = self.start(); saved = research.load(self.root, s['id'])
        saved.pop('file_manifest', None);research.save(self.root, saved)
        with patch('zar.research.chat') as chat:
            with self.assertRaises(research.ResearchError):research.advance(self.root, s['id'], send=True)
            chat.assert_not_called()

    def test_legacy_session_remains_unverified_without_added_manifest(self):
        project = research.get_project(self.root);project.pop('file_contract')
        (self.root / '.autoresearch/project.json').write_text(dumps(project))
        s = self.planned()
        self.assertNotIn('file_manifest', s)
        self.assertEqual(s['file_provenance']['status'], 'legacy_unverified')
        research.approve(self.root, s['id'], s['approval_token'])
        result = research.run_session(self.root, s['id'])
        self.assertEqual(result['state'], 'observed')

    def test_unchanged_baseline_then_candidate_preserves_fixed_manifest(self):
        s = self.decision()
        research.decide(self.root, s['id'], s['approval_token'], select=True)
        with patch('zar.research.chat', side_effect=self.respond):research.advance(self.root, s['id'], send=True)
        (self.root / 'metric.json').unlink()
        candidate = self.start()
        self.assertEqual(candidate['experiment_mode'], 'candidate')
        self.assertEqual(candidate['file_manifest'], s['file_manifest'])
        with patch('zar.research.chat', side_effect=self.respond):candidate = research.advance(self.root, candidate['id'], send=True)
        research.approve(self.root, candidate['id'], candidate['approval_token'])
        observed = research.run_session(self.root, candidate['id'])
        self.assertEqual(observed['state'], 'observed')


    def test_legacy_baseline_cannot_seed_verified_candidate(self):
        project = research.get_project(self.root)
        policy = project.pop('file_contract')
        (self.root / '.autoresearch/project.json').write_text(dumps(project))
        s = self.decision()
        research.decide(self.root, s['id'], s['approval_token'], select=True)
        with patch('zar.research.chat', side_effect=self.respond):research.advance(self.root, s['id'], send=True)
        project = research.get_project(self.root);project['file_contract'] = policy
        (self.root / '.autoresearch/project.json').write_text(dumps(project))
        (self.root / 'metric.json').unlink()
        with self.assertRaises(research.ResearchError):self.start()

    @unittest.skipUnless(os.name == 'posix', 'symlink replacement fixture requires POSIX')
    def test_protected_read_source_replaced_by_symlink_records_failed_receipt(self):
        s = research.start(self.root, profile=self.profile, goal='test',
            read_paths=['train.py', 'evaluate.py'], command='train', metric_file='metric.json',
            metric_key='score', max_calls=9, session_seconds=120, scope='full', seed=42,
            budget_ref='test-five-seconds')
        with patch('zar.research.chat', side_effect=self.respond):s = research.advance(self.root, s['id'], send=True)
        research.approve(self.root, s['id'], s['approval_token'])
        real = research.run
        def swapped(*args, **kwargs):
            result = real(*args, **kwargs)
            (self.root / 'evaluate.py').unlink()
            (self.root / 'evaluate.py').symlink_to(self.root / 'train.py')
            return result
        with patch('zar.research.run', side_effect=swapped):
            result = research.run_session(self.root, s['id'])
        record = loads((self.root / '.autoresearch/experiments' / (result['experiment_id'] + '.json')).read_text())
        self.assertEqual(record['execution']['status'], 'failed')
        self.assertEqual(record['execution']['exit_code'], 0)
        self.assertTrue(any(e['ref'].endswith('/receipt.json') for e in record['execution']['evidence']))
        self.assertIsNone(record['execution']['score'])


    def test_fixed_input_alias_to_editable_path_is_rejected_before_session(self):
        (self.root / 'evaluate.py').unlink()
        os.link(self.root / 'train.py', self.root / 'evaluate.py')
        with self.assertRaises(research.ResearchError):self.start()
        self.assertEqual(list((self.root / '.autoresearch/sessions').glob('*.json')), [])
        self.assertFalse((self.root / 'metric.json').exists())


if __name__ == '__main__':unittest.main()
