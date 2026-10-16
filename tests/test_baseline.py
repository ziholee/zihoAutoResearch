"""A first baseline measures unchanged source and cannot hide an LLM edit."""
from unittest.mock import patch
from tests import test_research as fixture
from zar import research
from zar.codec import dumps, loads

import unittest

class BaselineTests(unittest.TestCase):
    setUp=fixture.ResearchTests.setUp
    start=fixture.ResearchTests.start
    respond=fixture.ResearchTests.respond
    planned=fixture.ResearchTests.planned
    def test_auto_baseline_is_explicit_and_token_bound(self):
        s=self.start();self.assertEqual(s['experiment_mode'],'baseline');self.assertIsNone(s['baseline_id'])
        old=research.token(s);s['experiment_mode']='candidate';self.assertNotEqual(old,research.token(s))
    def test_candidate_requires_selected_baseline(self):
        with self.assertRaisesRegex(ValueError,'baseline'):
            research.start(self.root,profile=self.profile,goal='test',read_paths=['train.py'],command='train',metric_file='metric.json',metric_key='score',mode='candidate')
    def test_baseline_rejects_llm_source_changes(self):
        def reply(profile,messages):
            answer=self.respond(profile,messages);body=loads(answer['content'])
            if 'changes' in body:body['changes']=[dict(path='train.py',before_sha256=research.digest(self.code.encode()),content='# edit')]
            answer['content']=dumps(body);return answer
        s=self.start()
        with patch('zar.research.chat',side_effect=reply):
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
        self.assertEqual((self.root/'train.py').read_text(),self.code)

    def test_selected_candidate_with_superseded_base_is_rejected(self):
        p=research.get_project(self.root);p['selected_experiment_id']='selected'
        base=dict(id='selected',baseline_id='original',execution=dict(status='succeeded'),decision=dict(status='keep',validity='valid'),comparison=p['comparison'],environment=p['environment'],run_context=dict(scope='full',budget_ref='test'))
        with patch('zar.experiments.superseded_ids',return_value={'original'}):
            with self.assertRaisesRegex(ValueError,'superseded'):research.experiment_target(p,{'experiment':{'selected':base}},dict(scope='full',budget_ref='test'),'candidate')
    def test_execution_rechecks_approved_plan_token(self):
        s=self.planned();research.approve(self.root,s['id'],s['approval_token'])
        stored=research.load(self.root,s['id'])
        stored['command']['argv']=['not-the-approved-program']
        research.save(self.root,stored)
        with self.assertRaisesRegex(research.ResearchError,'approval'):
            research.run_session(self.root,s['id'])
        self.assertFalse((self.root/'metric.json').exists())
        self.assertEqual(list((self.root/'.autoresearch/experiments').glob('*.json')),[])
