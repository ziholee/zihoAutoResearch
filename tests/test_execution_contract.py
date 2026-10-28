"""Revalidate stored plans before local execution or mock-provider transmission."""
from copy import deepcopy
import sys
import unittest
from unittest.mock import patch

from zar import research
from zar.codec import dumps, loads
import test_research as fixtures


class ExecutionContractTests(unittest.TestCase):
    setUp = fixtures.ResearchTests.setUp
    start = fixtures.ResearchTests.start
    respond = fixtures.ResearchTests.respond
    planned = fixtures.ResearchTests.planned

    def stored(self, session):
        return research.load(self.root, session['id'])

    def approved(self):
        s = self.planned()
        research.approve(self.root, s['id'], s['approval_token'])
        return self.stored(s)

    def rewrite(self, s):
        # Recomputing a review checksum must not bypass project-owned constraints.
        s['approval_token'] = research.token(s)
        research.save(self.root, s)

    def assert_no_run(self):
        self.assertFalse((self.root / 'metric.json').exists())
        self.assertEqual((self.root / 'train.py').read_text(), self.code)
        self.assertEqual(list((self.root / '.autoresearch/experiments').glob('*.json')), [])

    def test_recomputed_token_cannot_substitute_project_command(self):
        s = self.approved()
        s['command']['argv'] = [sys.executable, '-c', 'from pathlib import Path; Path("unapproved.txt").write_text("marker")']
        self.rewrite(s)
        with self.assertRaises(research.ResearchError):
            research.run_session(self.root, s['id'])
        self.assertFalse((self.root / 'unapproved.txt').exists())
        self.assert_no_run()

    def test_recomputed_token_cannot_change_command_working_directory(self):
        s = self.approved()
        (self.root / 'other').mkdir()
        s['command']['cwd'] = 'other'
        self.rewrite(s)
        with patch('zar.research.run') as run:
            with self.assertRaises(research.ResearchError):research.run_session(self.root, s['id'])
            run.assert_not_called()
        self.assert_no_run()

    def legacy_proposal(self):
        s = self.approved()
        # A legacy session still needs current execution constraints; no automatic
        # baseline field migration is necessary for this test or the implementation.
        s.pop('experiment_mode'); s.pop('baseline_id')
        return s

    def test_recomputed_token_cannot_write_unconfigured_source(self):
        s = self.legacy_proposal()
        (self.root / 'protected.py').write_text('original')
        s['sources'].update(research.snapshot(self.root, ['protected.py']))
        s['outputs']['implementation']['changes'] = [dict(path='protected.py', before_sha256=s['sources']['protected.py']['sha256'], content='changed')]
        self.rewrite(s)
        with self.assertRaises(research.ResearchError):research.run_session(self.root, s['id'])
        self.assertEqual((self.root / 'protected.py').read_text(), 'original')
        self.assert_no_run()

    def test_recomputed_token_cannot_apply_stale_proposal(self):
        s = self.legacy_proposal()
        s['outputs']['implementation']['changes'] = [dict(path='train.py', before_sha256='0'*64, content=self.code)]
        self.rewrite(s)
        with self.assertRaises(research.ResearchError):research.run_session(self.root, s['id'])
        self.assert_no_run()

    def test_recomputed_token_cannot_apply_duplicate_or_oversized_changes(self):
        s = self.legacy_proposal()
        original = deepcopy(s)
        change = dict(path='train.py', before_sha256=s['sources']['train.py']['sha256'], content=self.code)
        for changes in ([change, change], [dict(change, content='#'+'가'*40000)]):
            with self.subTest(size=len(changes)):
                s = deepcopy(original)
                s['outputs']['implementation']['changes'] = changes
                self.rewrite(s)
                with self.assertRaises(research.ResearchError):research.run_session(self.root, s['id'])
                self.assert_no_run()

    def test_profile_changes_rejected_before_any_call_or_budget_charge(self):
        s = self.start(); original = self.stored(s)
        alternatives = dict(base_url='http://127.0.0.1:9998/v1', model='other', api_key_env='OTHER_TEST_KEY', max_output_tokens=99, timeout_seconds=3, max_response_bytes=512)
        for key, value in alternatives.items():
            with self.subTest(field=key):
                changed = deepcopy(original); changed['profile'][key] = value
                research.save(self.root, changed)
                with patch('zar.research.chat', side_effect=self.respond) as chat:
                    with self.assertRaises(research.ResearchError):research.advance(self.root, s['id'], send=True)
                    chat.assert_not_called()
                self.assertEqual(self.stored(s)['calls'], 0)
        self.assert_no_run()

    def test_codex_command_pin_checked_without_launching_agent(self):
        self.profile = dict(provider='codex', command='codex', model='mock')
        s = self.start(); changed = self.stored(s)
        changed['profile']['command'] = 'other-codex'
        research.save(self.root, changed)
        with patch('zar.research.chat', side_effect=self.respond) as chat:
            with self.assertRaises(research.ResearchError):research.advance(self.root, s['id'], send=True)
            chat.assert_not_called()
        self.assertEqual(self.stored(s)['calls'], 0)

    def test_profile_edit_during_call_blocks_output_and_following_call(self):
        s = self.start()
        def changed(profile, messages):
            current = self.stored(s); current['profile']['model'] = 'modified-during-call'
            research.save(self.root, current)
            return self.respond(profile, messages)
        with patch('zar.research.chat', side_effect=changed) as chat:
            with self.assertRaises(research.ResearchError):research.advance(self.root, s['id'], send=True)
            self.assertEqual(chat.call_count, 1)
        saved = self.stored(s)
        self.assertEqual(saved['state'], 'blocked')
        self.assertEqual(saved['error'], 'inputs_changed')
        self.assertEqual(saved['outputs'], {})
        self.assertEqual(saved['calls'], 1)

    def test_legacy_profile_edit_during_failed_call_blocks_retry(self):
        s = self.start(); saved = self.stored(s)
        saved.pop('transmission_contract')
        research.save(self.root, saved)
        def interrupted(profile, messages):
            current = self.stored(s); current['profile']['model'] = 'changed'
            research.save(self.root, current)
            raise research.LLMError('timeout', 'mock timeout')
        with patch('zar.research.chat', side_effect=interrupted) as chat:
            with self.assertRaises(research.ResearchError):research.advance(self.root, s['id'], send=True)
            self.assertEqual(chat.call_count, 1)
        saved = self.stored(s)
        self.assertEqual((saved['state'], saved['error'], saved['calls']), ('blocked', 'inputs_changed', 1))
        self.assertNotIn('transmission_contract', saved)

    def test_profile_change_does_not_clear_unconfirmed_agent_ownership(self):
        s = self.start()
        def interrupted(profile, messages):
            current = self.stored(s); current['profile']['model'] = 'changed'
            research.save(self.root, current)
            raise research.LLMError('agent_cleanup_unconfirmed', 'mock unconfirmed cleanup')
        with patch('zar.research.chat', side_effect=interrupted):
            with self.assertRaises(research.ResearchError):research.advance(self.root, s['id'], send=True)
        saved = self.stored(s)
        self.assertEqual((saved['state'], saved['error']), ('calling', 'agent_cleanup_unconfirmed'))
        with self.assertRaises(research.ResearchError):research.advance(self.root, s['id'], send=True)

    def test_legacy_sessions_keep_token_and_report_unpinned_profile(self):
        s = self.start(); saved = self.stored(s)
        saved.pop('transmission_contract', None)
        research.save(self.root, saved)
        before = research.token(saved)
        research.assert_fresh(self.root, saved)
        self.assertEqual(research.token(self.stored(s)), before)
        self.assertEqual(research.status(self.root, s['id'])['transmission']['contract_status'], 'legacy_unpinned')
        with patch('zar.research.chat', side_effect=self.respond):
            result = research.advance(self.root, s['id'], send=True)
        self.assertEqual(result['state'], 'awaiting_approval')
        self.assertNotIn('transmission_contract', self.stored(s))

    def test_partial_or_unsupported_connection_contract_cannot_downgrade(self):
        s = self.start(); original = self.stored(s)
        for contract in (None, {}, dict(version=2, profile_sha256='0'*64)):
            changed = deepcopy(original); changed['transmission_contract'] = contract
            research.save(self.root, changed)
            with patch('zar.research.chat', side_effect=self.respond) as chat:
                with self.assertRaises(research.ResearchError):research.advance(self.root, s['id'], send=True)
                chat.assert_not_called()


if __name__ == '__main__':
    unittest.main()
