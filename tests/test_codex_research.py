"""Codex profiles share the existing session approval and execution contract."""
import unittest
from unittest.mock import patch
from zar import cli, research
from zar.llm import validate_profile, LLMError
from tests import test_research


class CodexResearchTests(unittest.TestCase):
    setUp = test_research.ResearchTests.setUp
    start = test_research.ResearchTests.start
    respond = test_research.ResearchTests.respond

    def test_codex_profile_and_transmission_without_api_key(self):
        self.profile = dict(provider='codex', model='mock', command='codex')
        s = self.start()
        self.assertEqual(s['transmission']['provider'], 'codex')
        self.assertEqual(s['transmission']['command'], 'codex')
        self.assertIsNone(s['transmission']['server'])
        self.assertNotIn('api_key_env', s['profile'])
        with patch('zar.research.chat') as call:
            with self.assertRaises(research.ResearchError):
                research.advance(self.root, s['id'], send=False)
            call.assert_not_called()
        with self.assertRaises(research.ResearchError):
            research.run_session(self.root, s['id'])

    def test_codex_call_uses_owned_lifecycle_not_detached_thread(self):
        profile = dict(provider='codex', model='mock', command='codex', timeout_seconds=60)
        with patch('zar.research.chat', return_value={'content':'{}','usage':None}) as call, patch('zar.research.threading.Thread') as thread:
            research.call_api(profile, [], .2)
        thread.assert_not_called()
        self.assertLessEqual(call.call_args.args[0]['timeout_seconds'], .2)
        self.assertEqual(profile['timeout_seconds'], 60)
        with patch('zar.research.chat') as call:
            with self.assertRaises(LLMError):research.call_api(profile, [], -1)
            call.assert_not_called()

    def test_codex_roles_stop_at_each_existing_approval(self):
        self.profile = dict(provider='codex', model='mock', command='codex')
        s = self.start()
        with patch('zar.research.chat', side_effect=self.respond):
            s = research.advance(self.root, s['id'], send=True)
            self.assertEqual(s['state'], 'awaiting_approval')
            self.assertFalse((self.root/'metric.json').exists())
            with self.assertRaises(research.ResearchError):research.run_session(self.root, s['id'])
            research.approve(self.root, s['id'], s['approval_token'])
            self.assertFalse((self.root/'metric.json').exists())
            research.run_session(self.root, s['id'])
            s = research.advance(self.root, s['id'], send=True)
            self.assertEqual(s['state'], 'awaiting_decision')
            research.decide(self.root, s['id'], s['approval_token'])
            s = research.advance(self.root, s['id'], send=True)
        self.assertEqual(s['state'], 'complete')
        self.assertEqual(s['calls'], 7)

    def test_unconfirmed_agent_cleanup_requires_manual_recovery(self):
        self.profile = dict(provider='codex', model='mock', command='codex')
        s = self.start()
        with patch('zar.research.chat', side_effect=LLMError('agent_cleanup_unconfirmed','Cleanup unconfirmed.')):
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
        s=research.status(self.root,s['id'])
        self.assertEqual(s['state'],'calling')
        self.assertEqual(s['error'],'agent_cleanup_unconfirmed')
        with patch('zar.research.chat') as call:
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
            call.assert_not_called()
        with self.assertRaises(research.ResearchError):research.recover(self.root,s['id'])
        s=research.recover(self.root,s['id'],confirm_stopped=True)
        self.assertEqual(s['state'],'planning')
        self.assertEqual(s['calls'],1)

    def test_http_profile_compatibility_and_unknown_provider(self):
        self.assertNotIn('provider', validate_profile(self.profile))
        with self.assertRaises(LLMError):validate_profile({**self.profile, 'provider':'other'})
        with self.assertRaises(LLMError):validate_profile({**self.profile, 'provider':'codex'})

    def test_public_start_codex_and_reject_mixed_flags(self):
        import contextlib, io, json
        args=['--project',str(self.root),'--json','research','start','--provider','codex','--model','mock',
              '--goal','test','--read','train.py','--command','train','--metric-file','metric.json',
              '--metric-key','score','--budget-ref','test']
        for extra, expected in (([],0), (['--base-url','http://localhost:9/v1'],3),
                                (['--api-key-env','KEY'],3)):
            with self.subTest(extra=extra):
                stream=io.StringIO()
                with contextlib.redirect_stdout(stream):code=cli.main(args+extra)
                self.assertEqual(code,expected,stream.getvalue())
                self.assertIsInstance(json.loads(stream.getvalue()),dict)


@unittest.skipUnless(__import__('os').name == 'posix', 'Codex adapter requires POSIX')
class CodexExecutableLoopTests(unittest.TestCase):
    setUp = test_research.ResearchTests.setUp

    def test_public_cli_fake_agent_full_loop_and_persisted_usage(self):
        import contextlib, io, json, sys
        fake = self.root/'fake-codex'
        fake.write_text('#!' + sys.executable + '\n' + r'''
import json,sys
from pathlib import Path
if '--version' in sys.argv:
    print('codex-cli 0.162.1');sys.exit(0)
assert Path.cwd() != Path(__file__).parent
assert '--ignore-user-config' in sys.argv and '--ephemeral' in sys.argv
assert sys.argv[sys.argv.index('--sandbox')+1] == 'read-only'
assert sys.argv[sys.argv.index('-a')+1] == 'never'
assert 'features.shell_tool=false' in sys.argv
messages=json.loads(sys.stdin.read().split('\n',1)[1])
assert messages[0]['role']=='system'
context=json.loads(messages[-1]['content'])
role=context['role']
body=dict(summary='Synthetic source review',evidence=['train.py'],uncertainties=[])
body.update({'analysis':dict(missing=[]),'evaluation':dict(verdict='pass'),
'planning':dict(hypothesis='unchanged baseline'),'implementation':dict(changes=[]),
'review':dict(verdict='pass'),'interpretation':dict(decision='keep',reason='observed baseline'),
'memory':dict(next_action='stop',lesson='one baseline',limitation='fake agent only')}[role])
print(json.dumps(dict(type='thread.started',thread_id='fake')))
print(json.dumps(dict(type='turn.started')))
print(json.dumps(dict(type='item.completed',item=dict(id='fake',type='agent_message',text=json.dumps(body)))))
print(json.dumps(dict(type='turn.completed',usage=dict(input_tokens=10,output_tokens=5))))
''')
        fake.chmod(0o700)
        def invoke(*args, success=True):
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):
                code=cli.main(['--project',str(self.root),'--json','research',*args])
            envelope=json.loads(stream.getvalue())
            self.assertEqual(code==0,success,envelope)
            return envelope['data']
        s=invoke('start','--provider','codex','--codex-command',str(fake),'--model','fake',
            '--goal','baseline','--read','train.py','--command','train','--metric-file','metric.json',
            '--metric-key','score','--budget-ref','fake')
        identifier=s['id']
        invoke('advance',identifier,success=False)
        invoke('run',identifier,success=False)
        s=invoke('advance',identifier,'--send')
        self.assertEqual(s['state'],'awaiting_approval')
        self.assertFalse((self.root/'metric.json').exists())
        self.assertEqual((self.root/'train.py').read_text(),self.code)
        invoke('approve',identifier,'--token','stale',success=False)
        invoke('approve',identifier,'--token',s['approval_token'])
        self.assertFalse((self.root/'metric.json').exists())
        invoke('run',identifier)
        invoke('run',identifier,success=False)
        s=invoke('advance',identifier,'--send')
        self.assertEqual(s['state'],'awaiting_decision')
        invoke('decide',identifier,'--token',s['approval_token'])
        s=invoke('advance',identifier,'--send')
        self.assertEqual(s['state'],'complete')
        self.assertEqual(s['calls'],7)
        self.assertTrue(all(t['usage'] for t in s['trace']))
        report=invoke('metrics',identifier)
        self.assertEqual(report['total']['tokens']['input_tokens'],{'value':70,'observations':7})
        self.assertEqual(report['total']['tokens']['output_tokens'],{'value':35,'observations':7})
        self.assertEqual(report['total']['tokens']['total_tokens'],{'value':None,'observations':0})
        self.assertEqual(report['total']['call_seconds']['observations'],7)
        from zar.codec import loads
        record=loads((self.root/'.autoresearch/experiments'/(s['experiment_id']+'.json')).read_text())
        self.assertEqual(record['execution']['score'],.5)
        self.assertEqual(record['decision']['status'],'keep')
