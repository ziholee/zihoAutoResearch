"""Public setup uses a local HTTP provider, never executes proposed code."""
import io
import json
import os
import shutil
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from zar import cli
from tests import test_research_http as fixture


class SetupHTTPTests(unittest.TestCase):
    def test_fresh_project_to_first_plan_without_json_editing(self):
        harness=fixture.ResearchHTTPTests()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        shutil.rmtree(harness.root/'.autoresearch')
        stderr=io.StringIO();stdout=io.StringIO()
        answers=dict(experiment_mode='baseline',name='setup example',objective='Test one bounded experiment',
            comparison_id='cmp',dataset_ref='synthetic',split_ref='fixed',metric='score',
            direction='minimize',evaluation_ref='v1',min_delta='0',os='other',runtime='python',
            device='cpu',max_experiments='3',max_run_seconds='5',command='train',argv_count='2',
            argv_0=sys.executable,argv_1='train.py',cwd='.',editable_count='1',editable_0='train.py',
            read_count='1',read_0='train.py',base_url=harness.endpoint,model='mock',
            api_key_env='ZAR_TEST_KEY',metric_file='metric.json',metric_key='score',scope='full',
            seed='42',budget_ref='test',max_calls='9',session_seconds='1800',save='yes',send='yes')
        seen=[]
        class Terminal(io.StringIO):
            def isatty(self):return True
            def readline(self):
                prompt=stderr.getvalue().splitlines()[-1]
                key=prompt.split(':',1)[0]
                if key in seen:raise AssertionError('Unexpected reprompt: '+prompt)
                seen.append(key)
                return answers[key]+'\n'
        with patch('sys.stdin',Terminal()),patch.dict(os.environ,{
            'ZAR_TEST_KEY':fixture.KEY,'NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost'}),redirect_stdout(stdout),redirect_stderr(stderr):
            code=cli.main(['research','setup','--project',str(harness.root),'--json'])
        self.assertEqual(code,0,stdout.getvalue()+stderr.getvalue())
        result=json.loads(stdout.getvalue())
        self.assertTrue(result['ok'])
        self.assertTrue(result['data']['saved'])
        session=result['data']['session']
        self.assertEqual(session['state'],'awaiting_approval')
        self.assertEqual(session['diff'],'')
        harness.assert_no_execution()
        self.assertEqual([json.loads(p['messages'][-1]['content'])['role']
            for _,_,p in harness.requests],['analysis','evaluation','planning','implementation','review'])
        self.assertNotIn(fixture.KEY,stdout.getvalue()+stderr.getvalue())
        for path in (harness.root/'.autoresearch').rglob('*.json'):
            self.assertNotIn(fixture.KEY,path.read_text())
