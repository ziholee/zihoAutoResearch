"""Completed sessions create fresh consent and immutable parent provenance."""
import unittest
from unittest.mock import patch
from tests import test_research as fixture
from zar import research
from zar.continuation import next_session
from zar.codec import loads,dumps

class NextTests(unittest.TestCase):
    setUp=fixture.ResearchTests.setUp
    start=fixture.ResearchTests.start
    respond=fixture.ResearchTests.respond
    planned=fixture.ResearchTests.planned
    def complete(self,select=True):
        s=self.planned();research.approve(self.root,s['id'],s['approval_token']);research.run_session(self.root,s['id'])
        with patch('zar.research.chat',side_effect=self.respond):s=research.advance(self.root,s['id'],send=True)
        s=research.decide(self.root,s['id'],s['approval_token'],select=select)
        with patch('zar.research.chat',side_effect=self.respond):return research.advance(self.root,s['id'],send=True)
    def next(self,s,**answers):
        return next_session(self.root,s['id'],ask=lambda p:answers.get(p.split(':',1)[0], 'yes' if p.startswith('save:') else 'no' if p.startswith('send:') else ''),emit=lambda m:None)
    def test_next_preserves_parent_and_inherits_bound_evidence(self):
        s=self.complete();raw=research.session_path(self.root,s['id']).read_bytes()
        n=self.next(s)['session']
        self.assertEqual(n['experiment_mode'],'candidate');self.assertEqual(n['baseline_id'],s['experiment_id'])
        self.assertEqual(n['calls'],0);self.assertEqual(n['state'],'planning');self.assertIsNone(n['approval_token'])
        self.assertNotEqual(n['metric_file'],s['metric_file']);self.assertEqual(n['profile'],s['profile'])
        self.assertEqual(n['next_context']['experiment']['execution']['score'],.5)
        self.assertEqual(raw,research.session_path(self.root,s['id']).read_bytes())
        old=research.token(n);n['next_context']['memory_proposal']['lesson']='tampered';self.assertNotEqual(old,research.token(n))
        with self.assertRaisesRegex(ValueError,'Next context'):research.assert_fresh(self.root,n)
    def test_cancel_does_not_write(self):
        s=self.complete();before={p:p.read_bytes() for p in (self.root/'.autoresearch').rglob('*.json')}
        self.assertTrue(self.next(s,save='no')['cancelled'])
        self.assertEqual(before,{p:p.read_bytes() for p in (self.root/'.autoresearch').rglob('*.json')})
    def test_incomplete_rejected(self):
        with self.assertRaisesRegex(ValueError,'complete'):self.next(self.start())
    def test_mismatched_budget_rejected_before_settings_save(self):
        s=self.complete();before=(self.root/'.autoresearch/project.json').read_bytes()
        with self.assertRaisesRegex(ValueError,'run context'):self.next(s,budget_ref='changed')
        self.assertEqual(before,(self.root/'.autoresearch/project.json').read_bytes())
    def test_without_selection_requests_baseline(self):
        s=self.complete(select=False);n=self.next(s)['session']
        self.assertEqual(n['experiment_mode'],'baseline');self.assertIsNone(n['baseline_id'])
    def test_parent_changed_during_prompt_not_saved(self):
        s=self.complete();before=(self.root/'.autoresearch/project.json').read_bytes()
        def ask(prompt):
            if prompt.startswith('save:'):
                raw=research.load(self.root,s['id']);raw['goal']='changed';research.save(self.root,raw);return 'yes'
            return ''
        with self.assertRaisesRegex(ValueError,'Parent session changed'):next_session(self.root,s['id'],ask=ask,emit=lambda m:None)
        self.assertEqual(before,(self.root/'.autoresearch/project.json').read_bytes())
    def test_record_change_between_continuation_and_setup_is_rejected(self):
        from zar import continuation
        real=continuation.setup
        s=self.complete();before=(self.root/'.autoresearch/project.json').read_bytes()
        def raced(root,**kwargs):
            path=root/'.autoresearch/experiments'/(s['experiment_id']+'.json')
            exp=loads(path.read_text());exp['execution']['score']=99;path.write_text(dumps(exp))
            return real(root,**kwargs)
        with patch('zar.continuation.setup',side_effect=raced):
            with self.assertRaisesRegex(ValueError,'Research records changed'):self.next(s)
        self.assertEqual(before,(self.root/'.autoresearch/project.json').read_bytes())
    def test_next_partial_save_is_reported_without_modifying_parent(self):
        s=self.complete();before=research.session_path(self.root,s['id']).read_bytes()
        with patch('zar.research._start_locked',side_effect=OSError('disk full')):result=self.next(s)
        self.assertTrue(result['saved']);self.assertIn('save incomplete',result['error'])
        self.assertIsNone(result['session']);self.assertEqual(before,research.session_path(self.root,s['id']).read_bytes())
    def test_revision_retains_next_provenance(self):
        from zar.revision import revise
        s=self.complete();n=self.next(s)['session']
        r=revise(self.root,n['id'],ask=lambda p:'new hypothesis' if p.startswith('feedback:') else 'yes' if p.startswith('save:') else 'no' if p.startswith('send:') else '',emit=lambda m:None)['session']
        self.assertEqual(r['next_context'],n['next_context']);self.assertEqual(r['experiment_mode'],'candidate')
