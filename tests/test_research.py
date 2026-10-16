"""Public session behavior: approvals, observations and interrupted launches."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zar import cli
from zar.codec import dumps, loads
from zar import research

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();cli.initialize(self.root)
        self.code='from pathlib import Path\nPath("metric.json").write_text(\'{"score": 0.5}\')\n'
        (self.root/'train.py').write_text(self.code)
        p=loads((self.root/'.autoresearch/project.json').read_text())
        p.update(name='test',objective='bounded mock experiment',comparison=dict(id='cmp',dataset_ref='synthetic',split_ref='fixed',metric='score',direction='minimize',evaluation_ref='v1',min_delta=0),environment=dict(os='other',runtime='python',device='cpu'),commands=[dict(name='train',argv=[sys.executable,'train.py'],cwd='.')],budget=dict(max_experiments=3,max_run_seconds=5),editable_paths=['train.py'])
        (self.root/'.autoresearch/project.json').write_text(dumps(p))
        self.profile=dict(base_url='http://localhost:9999/v1',model='mock',api_key_env='ZAR_TEST_KEY')
    def start(self):
        return research.start(self.root,profile=self.profile,goal='test',read_paths=['train.py'],command='train',metric_file='metric.json',metric_key='score',max_calls=9,session_seconds=120,scope='full',seed=42,budget_ref='test-five-seconds')
    def respond(self,profile,messages):
        import json
        role=json.loads(messages[-1]['content'])['role']
        body=dict(summary='Observed test source',evidence=['train.py'],uncertainties=[])
        body.update({'analysis':dict(missing=[]),'evaluation':dict(verdict='pass'),'planning':dict(hypothesis='baseline'),'implementation':dict(changes=[]),'review':dict(verdict='pass'),'interpretation':dict(decision='keep',reason='observed valid baseline'),'memory':dict(next_action='stop',lesson='one run',limitation='synthetic only')}[role])
        return dict(content=dumps(body),usage=None)
    def planned(self):
        s=self.start()
        with patch('zar.research.chat',side_effect=self.respond):s=research.advance(self.root,s['id'],send=True)
        self.assertEqual(s['state'],'awaiting_approval');return s
    def test_complete_real_process_with_mock_llm(self):
        s=self.planned();self.assertFalse((self.root/'metric.json').exists())
        research.approve(self.root,s['id'],s['approval_token'])
        s=research.run_session(self.root,s['id']);self.assertEqual(s['state'],'observed')
        with patch('zar.research.chat',side_effect=self.respond):s=research.advance(self.root,s['id'],send=True)
        self.assertEqual(s['state'],'awaiting_decision')
        s=research.decide(self.root,s['id'],s['approval_token'])
        self.assertEqual(s['state'],'remembering')
        with patch('zar.research.chat',side_effect=self.respond):s=research.advance(self.root,s['id'],send=True)
        self.assertEqual(s['state'],'complete')
        e=loads((self.root/'.autoresearch/experiments'/ (s['experiment_id']+'.json')).read_text())
        self.assertEqual(e['execution']['score'],0.5);self.assertEqual(e['decision']['status'],'keep')
    def test_requires_transmission_consent_and_execution_approval(self):
        s=self.start()
        with patch('zar.research.chat') as mock:
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=False)
            mock.assert_not_called()
        with self.assertRaises(research.ResearchError):research.run_session(self.root,s['id'])
    def test_stale_workspace_blocks_approval(self):
        s=self.planned();(self.root/'train.py').write_text('# changed')
        with self.assertRaises(research.ResearchError):research.approve(self.root,s['id'],s['approval_token'])
    def test_rejection_leaves_code_and_outputs_unchanged(self):
        s=self.planned();research.reject(self.root,s['id'])
        self.assertEqual((self.root/'train.py').read_text(),self.code)
        with self.assertRaises(research.ResearchError):research.run_session(self.root,s['id'])
    def test_existing_metric_is_never_adopted_or_deleted(self):
        s=self.planned();research.approve(self.root,s['id'],s['approval_token'])
        (self.root/'metric.json').write_text('{"score":999}')
        with self.assertRaises(research.ResearchError):research.run_session(self.root,s['id'])
        self.assertEqual((self.root/'metric.json').read_text(),'{"score":999}')
    def test_unknown_launch_never_repeats(self):
        s=self.planned();research.approve(self.root,s['id'],s['approval_token'])
        with patch('zar.research.run',side_effect=SystemExit):
            with self.assertRaises(SystemExit):research.run_session(self.root,s['id'])
        with self.assertRaises(research.ResearchError):research.run_session(self.root,s['id'])
        s=research.status(self.root,s['id']);self.assertEqual(s['state'],'executing')
        e=loads((self.root/'.autoresearch/experiments'/ (s['experiment_id']+'.json')).read_text())
        self.assertEqual(e['execution']['status'],'unknown')

    def test_api_interrupt_can_retry_without_running_anything(self):
        s=self.start()
        with patch('zar.research.chat',side_effect=KeyboardInterrupt):
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
        s=research.status(self.root,s['id']);self.assertEqual(s['state'],'planning');self.assertEqual(s['calls'],1)
        self.assertFalse((self.root/'metric.json').exists())
        with patch('zar.research.chat',side_effect=self.respond):s=research.advance(self.root,s['id'],send=True)
        self.assertEqual(s['state'],'awaiting_approval')

    def test_environment_change_invalidates_approval(self):
        s=self.planned()
        with patch.dict('os.environ',{'CUDA_VISIBLE_DEVICES':'different-device'}):
            with self.assertRaises(research.ResearchError):research.approve(self.root,s['id'],s['approval_token'])

    def test_decision_crash_recovers_without_duplicate_history(self):
        s=self.planned();research.approve(self.root,s['id'],s['approval_token']);research.run_session(self.root,s['id'])
        with patch('zar.research.chat',side_effect=self.respond):s=research.advance(self.root,s['id'],send=True)
        original=research.save
        def fail_after_decision(root,value):
            if value['state']=='remembering':raise OSError('disk full')
            original(root,value)
        with patch('zar.research.save',side_effect=fail_after_decision):
            with self.assertRaises(OSError):research.decide(self.root,s['id'],s['approval_token'])
        self.assertEqual(research.status(self.root,s['id'])['state'],'deciding')
        s=research.recover(self.root,s['id'],confirm_stopped=True)
        self.assertEqual(s['state'],'remembering')
        e=loads((self.root/'.autoresearch/experiments'/ (s['experiment_id']+'.json')).read_text())
        self.assertEqual(len(e['decision_history']),1)

    def test_evidence_tampering_blocks_decision(self):
        s=self.planned();research.approve(self.root,s['id'],s['approval_token']);research.run_session(self.root,s['id'])
        with patch('zar.research.chat',side_effect=self.respond):s=research.advance(self.root,s['id'],send=True)
        (self.root/'.autoresearch/session-artifacts'/s['id']/'metric.json').write_text('{"score":99}')
        with self.assertRaises(research.ResearchError):research.decide(self.root,s['id'],s['approval_token'])

    def test_path_escape_proposal_is_rejected_and_retryable(self):
        s=self.start()
        def invalid(profile,messages):
            answer=self.respond(profile,messages);body=loads(answer['content'])
            if 'changes' in body:body['changes']=[dict(path='other.py',before_sha256=None,content='bad')]
            answer['content']=dumps(body);return answer
        with patch('zar.research.chat',side_effect=invalid):
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
        self.assertEqual(research.status(self.root,s['id'])['state'],'planning')
        self.assertFalse((self.root/'other.py').exists())

    def test_budget_exhaustion_stops_calls(self):
        s=self.start();s['max_calls']=1;research.save(self.root,s)
        with patch('zar.research.chat',side_effect=self.respond) as mock:
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
            self.assertEqual(mock.call_count,1)

    def test_total_api_wait_is_bounded_even_if_transport_stalls(self):
        import time
        with patch('zar.research.chat',side_effect=lambda *a:time.sleep(0.5)):
            started=time.monotonic()
            with self.assertRaises(research.LLMError):research.call_api({},[],0.03)
            self.assertLess(time.monotonic()-started,0.3)

    def test_success_without_metric_is_failed_not_zero(self):
        (self.root/'train.py').write_text('pass\n')
        s=self.planned();research.approve(self.root,s['id'],s['approval_token']);s=research.run_session(self.root,s['id'])
        e=loads((self.root/'.autoresearch/experiments'/ (s['experiment_id']+'.json')).read_text())
        self.assertEqual(e['execution']['status'],'failed');self.assertIsNone(e['execution']['score'])

    def test_calling_crash_requires_explicit_stopped_confirmation(self):
        s=self.start();s.update(state='calling',return_state='planning',calls=1);research.save(self.root,s)
        with self.assertRaises(research.ResearchError):research.recover(self.root,s['id'])
        s=research.recover(self.root,s['id'],confirm_stopped=True)
        self.assertEqual(s['state'],'planning');self.assertEqual(s['calls'],1)

    def test_unicode_proposal_byte_limit_rejected_before_source_write(self):
        s=self.start()
        def too_large(profile,messages):
            answer=self.respond(profile,messages);body=loads(answer['content'])
            if 'changes' in body:
                body['changes']=[dict(path='train.py',before_sha256=s['sources']['train.py']['sha256'],content='#'+'가'*40000)]
            answer['content']=dumps(body);return answer
        with patch('zar.research.chat',side_effect=too_large):
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
        self.assertEqual((self.root/'train.py').read_text(),self.code)
        self.assertEqual(research.status(self.root,s['id'])['state'],'planning')
        self.assertFalse((self.root/'metric.json').exists())

    def test_decision_recovery_rechecks_evidence(self):
        s=self.planned();research.approve(self.root,s['id'],s['approval_token']);research.run_session(self.root,s['id'])
        with patch('zar.research.chat',side_effect=self.respond):s=research.advance(self.root,s['id'],send=True)
        with patch('zar.research.finish_decision',side_effect=OSError('failure')):
            with self.assertRaises(OSError):research.decide(self.root,s['id'],s['approval_token'],select=True)
        (self.root/'.autoresearch/session-artifacts'/s['id']/'metric.json').write_text('{"score":999}')
        with self.assertRaises(research.ResearchError):research.recover(self.root,s['id'],confirm_stopped=True)
        p=loads((self.root/'.autoresearch/project.json').read_text())
        self.assertIsNone(p['selected_experiment_id'])

    def test_nondefault_metric_contract_reaches_roles_and_execution(self):
        (self.root/'train.py').write_text('from pathlib import Path\nPath("second-run.json").write_text(\'{"loss":0.125}\')\n')
        s=research.start(self.root,profile=self.profile,goal='new metric destination',
            read_paths=['train.py'],command='train',metric_file='second-run.json',metric_key='loss',
            max_calls=9,session_seconds=120,scope='proxy',seed=17,budget_ref='proxy-protocol')
        seen=[]
        def provider(profile,messages):
            payload=loads(messages[-1]['content']);role=payload['role'];seen.append(role)
            self.assertEqual(payload['metric_file'],'second-run.json')
            self.assertEqual(payload['metric_key'],'loss')
            self.assertEqual(payload['run_context'],dict(scope='proxy',seed=17,budget_ref='proxy-protocol'))
            answer=self.respond(profile,messages)
            return answer
        with patch('zar.research.chat',side_effect=provider):s=research.advance(self.root,s['id'],send=True)
        research.approve(self.root,s['id'],s['approval_token']);s=research.run_session(self.root,s['id'])
        e=loads((self.root/'.autoresearch/experiments'/ (s['experiment_id']+'.json')).read_text())
        self.assertEqual(e['execution']['score'],0.125)
        self.assertEqual(seen,['analysis','evaluation','planning','implementation','review'])
        self.assertFalse((self.root/'metric.json').exists())
