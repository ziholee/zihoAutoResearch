from unittest.mock import patch
import unittest
from tests import test_research as fixture
from zar import research

class RevisionTests(unittest.TestCase):
    setUp=fixture.ResearchTests.setUp
    start=fixture.ResearchTests.start
    respond=fixture.ResearchTests.respond
    planned=fixture.ResearchTests.planned
    def revise(self,s,**answers):
        from zar.revision import revise
        return revise(self.root,s['id'],ask=lambda p:answers.get(p.split(':',1)[0], 'yes' if p.startswith('save:') else 'no' if p.startswith('send:') else ''),emit=lambda m:None)
    def test_revision_invalidates_approval_and_preserves_sources(self):
        s=self.planned();research.approve(self.root,s['id'],s['approval_token'])
        result=self.revise(s,feedback='Try a simpler hypothesis')
        child=result['session'];self.assertEqual(child['state'],'planning')
        self.assertEqual(child['revision_context']['parent_id'],s['id'])
        self.assertEqual(child['outputs'],{});self.assertIsNone(child['approval_token'])
        self.assertEqual(research.status(self.root,s['id'])['state'],'rejected')
        with self.assertRaises(ValueError):research.run_session(self.root,s['id'])
        self.assertEqual((self.root/'train.py').read_text(),self.code)
    def test_cancel_preserves_parent_and_project(self):
        s=self.planned();before=(self.root/'.autoresearch/project.json').read_bytes()
        result=self.revise(s,feedback='Later',save='no')
        self.assertTrue(result['cancelled']);self.assertEqual(research.status(self.root,s['id'])['state'],'awaiting_approval')
        self.assertEqual((self.root/'.autoresearch/project.json').read_bytes(),before)
    def test_no_revision_of_attempted_execution(self):
        s=self.start();raw=research.load(self.root,s['id']);raw['state']='unknown';research.save(self.root,raw)
        with self.assertRaises(ValueError):self.revise(s,feedback='Retry')
    def test_revision_context_bound_to_approval(self):
        parent=self.planned()
        result=self.revise(parent,feedback='Simplify')
        with patch('zar.research.chat',side_effect=self.respond):s=research.advance(self.root,result['session']['id'],send=True)
        with self.assertRaises(ValueError):research.approve(self.root,s['id'],parent['approval_token'])
        raw=research.load(self.root,s['id']);raw['revision_context']['feedback']='changed';research.save(self.root,raw)
        with self.assertRaises(ValueError):research.approve(self.root,s['id'],s['approval_token'])
    def test_parent_concurrent_change_prevents_any_settings_write(self):
        from zar.revision import revise
        s=self.planned();before=(self.root/'.autoresearch/project.json').read_bytes()
        def ask(prompt):
            if prompt.startswith('save:'):
                research.reject(self.root,s['id']);return 'yes'
            return 'change' if prompt.startswith('feedback:') else ''
        with self.assertRaisesRegex(ValueError,'Parent session changed'):revise(self.root,s['id'],ask=ask,emit=lambda m:None)
        self.assertEqual((self.root/'.autoresearch/project.json').read_bytes(),before)
        self.assertEqual(len(list((self.root/'.autoresearch/sessions').glob('*.json'))),1)
    def test_defaults_preserve_profile_and_run_context(self):
        self.profile.update(timeout_seconds=17,max_output_tokens=1234,max_response_bytes=65536)
        s=self.start();child=self.revise(s,feedback='simpler')['session']
        self.assertEqual(child['profile'],s['profile']);self.assertEqual(child['run_context'],s['run_context'])
        self.assertEqual(child['goal'],s['goal']);self.assertEqual(child['session_seconds'],120)
        self.assertEqual(child['max_calls'],s['max_calls'])
    def test_missing_answers_are_transmitted_and_old_outputs_not_reused(self):
        from zar.codec import loads
        s=self.start();raw=research.load(self.root,s['id']);raw['state']='blocked'
        raw['outputs']={'analysis':dict(summary='Missing split',missing=['Which split?'],evidence=[],uncertainties=[])};research.save(self.root,raw)
        captured=[]
        def respond(profile,messages):
            captured.append(loads(messages[-1]['content']));return self.respond(profile,messages)
        with patch('zar.research.chat',side_effect=respond):result=self.revise(s,answer_0='Chronological split',send='yes')
        self.assertEqual(result['session']['state'],'awaiting_approval');self.assertEqual(len(captured),5)
        self.assertEqual(captured[0]['outputs'],{})
        self.assertEqual(captured[0]['revision_context']['answers'][0]['answer'],'Chronological split')
        self.assertEqual((self.root/'train.py').read_text(),self.code)
    def test_postexecution_blocked_parent_cannot_revise(self):
        s=self.start();raw=research.load(self.root,s['id']);raw.update(state='blocked',experiment_id='attempted');research.save(self.root,raw)
        with self.assertRaises(ValueError):self.revise(s,feedback='no')
    def test_cancel_after_save_keeps_link_and_invalidates_parent(self):
        from zar.revision import revise
        s=self.planned()
        def ask(prompt):
            if prompt.startswith('send:'):raise EOFError
            return 'yes' if prompt.startswith('save:') else 'change' if prompt.startswith('feedback:') else ''
        result=revise(self.root,s['id'],ask=ask,emit=lambda m:None)
        self.assertTrue(result['cancelled']);self.assertTrue(result['saved'])
        self.assertEqual(research.status(self.root,s['id'])['superseded_by'],result['session']['id'])
    def test_crash_during_project_write_invalidates_old_approval(self):
        s=self.planned();research.approve(self.root,s['id'],s['approval_token'])
        with patch('zar.setup.atomic_write',side_effect=OSError('disk full')):
            result=self.revise(s,feedback='change')
        self.assertIn('incomplete',result['error']);self.assertFalse(result['saved'])
        parent=research.status(self.root,s['id']);self.assertEqual(parent['state'],'rejected')
        self.assertIsNone(parent['approval_token']);self.assertEqual(parent['error'],'revision_save_started')
        with self.assertRaises(ValueError):research.run_session(self.root,s['id'])
    def test_next_actions_never_suggest_revision_for_unknown(self):
        s=self.start();s['state']='unknown'
        self.assertEqual([v['action'] for v in research.view(s)['next_actions']],['reconcile'])
        s['state']='calling';action=research.view(s)['next_actions'][0]
        self.assertIn('verifying',action['reason']);self.assertEqual(action['action'],'recover')
    def test_recovered_partial_application_needs_manual_inspection(self):
        s=self.start();raw=research.load(self.root,s['id']);raw.update(state='blocked',error='inspect_partial_changes_and_records_before_new_session');research.save(self.root,raw)
        with self.assertRaisesRegex(ValueError,'partial source'):self.revise(s,feedback='Retry')
        self.assertEqual([a['action'] for a in research.view(raw)['next_actions']],['inspect'])
    def test_interrupt_during_save_reports_partial_state(self):
        s=self.planned()
        with patch('zar.setup.atomic_write',side_effect=KeyboardInterrupt):
            result=self.revise(s,feedback='change')
        self.assertTrue(result['cancelled']);self.assertFalse(result['saved'])
        self.assertIn('interrupted',result['error'])
        self.assertIsNone(research.status(self.root,s['id'])['approval_token'])
