"""Codex setup keeps explicit transmission consent and inherited profiles."""
import unittest
from unittest.mock import patch
from tests import test_setup as setup_fixture
from tests import test_next as next_fixture
from zar import research
from zar.setup import setup
from zar.revision import revise


class CodexSetupTests(unittest.TestCase):
    setUp=setup_fixture.SetupTests.setUp

    def ask(self,prompt):
        key=prompt.split(':',1)[0]
        self.prompts.append(prompt)
        self.assertNotIn(key,('base_url','api_key_env'))
        return self.answers[key]

    def prepare(self):
        self.prompts=[]
        self.answers.update(provider='codex',codex_command='codex',model='mock-codex')

    def test_save_without_send_never_invokes_agent(self):
        self.prepare()
        with patch('zar.research.advance') as advance:
            result=setup(self.root,ask=self.ask,emit=lambda m:None)
        advance.assert_not_called()
        self.assertTrue(result['saved'])
        self.assertEqual(result['session']['state'],'planning')
        self.assertEqual(result['session']['profile']['provider'],'codex')
        self.assertEqual(result['session']['profile']['command'],'codex')
        send=next(p for p in self.prompts if p.startswith('send:'))
        self.assertIn('authenticated service',send)
        self.assertIn('charges',send)

    def test_save_cancel_creates_no_project(self):
        self.prepare();self.answers['save']='no'
        result=setup(self.root,ask=self.ask,emit=lambda m:None)
        self.assertTrue(result['cancelled'])
        self.assertFalse((self.root/'.autoresearch').exists())

    def test_send_consent_uses_existing_advance_boundary(self):
        self.prepare();self.answers['send']='yes'
        with patch('zar.research.advance',side_effect=lambda root,sid,send:research.status(root,sid)) as advance:
            result=setup(self.root,ask=self.ask,emit=lambda m:None)
        advance.assert_called_once_with(self.root,result['session']['id'],send=True)
        self.assertIsNone(result['session']['approval_token'])
        self.assertFalse((self.root/'metric.json').exists())

    def test_revision_inherits_codex_profile_limits_without_api_prompts(self):
        self.prepare();s=setup(self.root,ask=self.ask,emit=lambda m:None)['session']
        raw=research.load(self.root,s['id']);raw['profile'].update(timeout_seconds=17,max_response_bytes=65536)
        research.save(self.root,raw)
        def ask(prompt):
            self.assertNotIn(prompt.split(':',1)[0],('base_url','api_key_env'))
            return 'simpler' if prompt.startswith('feedback:') else 'yes' if prompt.startswith('save:') else 'no' if prompt.startswith('send:') else ''
        child=revise(self.root,s['id'],ask=ask,emit=lambda m:None)['session']
        self.assertEqual(child['profile'],raw['profile'])
        self.assertEqual(child['state'],'planning')
        self.assertEqual(child['calls'],0)


class CodexNextSetupTests(unittest.TestCase):
    setUp=next_fixture.NextTests.setUp
    start=next_fixture.NextTests.start
    respond=next_fixture.NextTests.respond
    planned=next_fixture.NextTests.planned
    complete=next_fixture.NextTests.complete
    next=next_fixture.NextTests.next

    def test_next_can_switch_api_to_codex_without_stale_api_fields(self):
        parent=self.complete()
        child=self.next(parent,provider='codex',codex_command='codex',model='mock-codex')['session']
        self.assertEqual(child['profile']['provider'],'codex')
        self.assertNotIn('base_url',child['profile'])
        self.assertNotIn('api_key_env',child['profile'])
        self.assertNotIn('max_output_tokens',child['profile'])
        self.assertEqual(child['next_context']['parent_id'],parent['id'])
        self.assertEqual(child['calls'],0)

    def test_next_inherits_codex_profile_and_limits(self):
        self.profile=dict(provider='codex',command='codex',model='mock-codex',timeout_seconds=17,max_response_bytes=65536)
        with patch('zar.research.call_api',side_effect=lambda profile,messages,remaining:self.respond(profile,messages)):
            parent=self.complete()
        child=self.next(parent)['session']
        self.assertEqual(child['profile'],parent['profile'])
        self.assertEqual(child['state'],'planning')
        self.assertEqual(child['calls'],0)
        self.assertIsNone(child['approval_token'])
