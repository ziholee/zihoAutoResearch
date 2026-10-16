"""Interactive setup preserves consent and existing project history."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zar import cli, research
from zar.codec import loads, dumps
from zar.setup import setup

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        (self.root/'train.py').write_text('print("test")\n')
        self.answers=dict(experiment_mode='baseline',name='test',objective='test experiment',comparison_id='cmp',dataset_ref='synthetic',split_ref='fixed',metric='score',direction='minimize',evaluation_ref='v1',min_delta='0',os='other',runtime='python',device='cpu',max_experiments='3',max_run_seconds='5',command='train',argv_count='2',argv_0='python',argv_1='train.py',cwd='.',editable_count='1',editable_0='train.py',read_count='1',read_0='train.py',base_url='http://localhost:9999/v1',model='mock',api_key_env='ZAR_TEST_KEY',metric_file='metric.json',metric_key='score',scope='full',seed='',budget_ref='test',max_calls='9',session_seconds='120',save='yes',send='no')
    def ask(self,prompt):return self.answers[prompt.split(':',1)[0]]
    def test_cancel_does_not_initialize(self):
        self.answers['save']='no'
        result=setup(self.root,ask=self.ask,emit=lambda x:None)
        self.assertTrue(result['cancelled']);self.assertFalse(result['saved'])
        self.assertFalse((self.root/'.autoresearch').exists())
    def test_no_send_without_consent(self):
        with patch('zar.research.chat') as chat:
            result=setup(self.root,ask=self.ask,emit=lambda x:None)
        chat.assert_not_called();self.assertTrue(result['saved'])
        self.assertEqual(result['session']['state'],'planning')
    def test_eof_does_not_write(self):
        def ask(prompt):raise EOFError
        self.assertTrue(setup(self.root,ask=ask,emit=lambda x:None)['cancelled'])
        self.assertFalse((self.root/'.autoresearch').exists())
    def test_existing_preserves_identity_and_unrelated_command(self):
        cli.initialize(self.root)
        path=self.root/'.autoresearch/project.json';old=loads(path.read_text())
        old['commands']=[dict(name='other',argv=['echo','ok'],cwd='.')];path.write_text(dumps(old))
        setup(self.root,ask=self.ask,emit=lambda x:None)
        current=loads(path.read_text())
        self.assertEqual(current['id'],old['id']);self.assertEqual(current['created_at'],old['created_at'])
        self.assertEqual(current['commands'][0],old['commands'][0]);self.assertEqual(current['revision'],2)
    def test_min_delta_reprompts(self):
        values=iter(['NaN','-1','0'])
        def ask(prompt):return next(values) if prompt.startswith('min_delta:') else self.ask(prompt)
        self.assertTrue(setup(self.root,ask=ask,emit=lambda x:None)['saved'])
    def test_stale_source_does_not_save(self):
        def ask(prompt):
            if prompt.startswith('save:'):(self.root/'train.py').write_text('changed')
            return self.ask(prompt)
        with self.assertRaisesRegex(ValueError,'Source'):setup(self.root,ask=ask,emit=lambda x:None)
        self.assertFalse((self.root/'.autoresearch').exists())
    def test_stale_project_does_not_overwrite(self):
        cli.initialize(self.root)
        path=self.root/'.autoresearch/project.json'
        def ask(prompt):
            if prompt.startswith('save:'):
                p=loads(path.read_text());p['name']='concurrent';path.write_text(dumps(p))
            return self.ask(prompt)
        with self.assertRaisesRegex(ValueError,'Project settings changed'):setup(self.root,ask=ask,emit=lambda x:None)
        self.assertEqual(loads(path.read_text())['name'],'concurrent')
    def test_cancel_after_save_retains_local_session(self):
        def ask(prompt):
            if prompt.startswith('send:'):raise EOFError
            return self.ask(prompt)
        result=setup(self.root,ask=ask,emit=lambda x:None)
        self.assertTrue(result['cancelled']);self.assertTrue(result['saved'])
        self.assertEqual(result['session']['state'],'planning')
        self.assertEqual(research.status(self.root,result['session']['id'])['state'],'planning')
    def test_invalid_paths_do_not_initialize(self):
        for key,value in [('read_0','missing.py'),('cwd','missing'),('metric_file','train.py'),('editable_0','../outside.py')]:
            with self.subTest(key=key):
                old=self.answers[key];self.answers[key]=value
                with self.assertRaises(ValueError):setup(self.root,ask=self.ask,emit=lambda x:None)
                self.assertFalse((self.root/'.autoresearch').exists());self.answers[key]=old
    def test_comparison_fields_need_new_id(self):
        setup(self.root,ask=self.ask,emit=lambda x:None)
        path=self.root/'.autoresearch/project.json';before=path.read_bytes()
        self.answers['split_ref']='new-split'
        with self.assertRaisesRegex(ValueError,'new comparison ID'):setup(self.root,ask=self.ask,emit=lambda x:None)
        self.assertEqual(path.read_bytes(),before)
        self.answers['comparison_id']='new-cmp'
        self.assertTrue(setup(self.root,ask=self.ask,emit=lambda x:None)['saved'])
    def test_api_failure_retains_session(self):
        from zar.llm import LLMError
        self.answers['send']='yes'
        with patch('zar.research.chat',side_effect=LLMError('transport_error','Unable to contact API.')):
            result=setup(self.root,ask=self.ask,emit=lambda x:None)
        self.assertTrue(result['saved']);self.assertIsNotNone(result['session'])
        self.assertEqual(result['session']['state'],'planning')
        self.assertTrue(result['session']['error'])
        self.assertFalse((self.root/'metric.json').exists())
    def test_literal_argument_is_preserved(self):
        self.answers['argv_1']='path with spaces.py'
        result=setup(self.root,ask=self.ask,emit=lambda x:None)
        self.assertEqual(result['session']['command']['argv'][1],'path with spaces.py')
    def test_changed_record_identity_does_not_save(self):
        cli.initialize(self.root)
        path=self.root/'.autoresearch/project.json';before=path.read_bytes()
        with patch('zar.research.records_identity',side_effect=['before','after']):
            with self.assertRaisesRegex(ValueError,'Research records changed'):
                setup(self.root,ask=self.ask,emit=lambda x:None)
        self.assertEqual(path.read_bytes(),before)
    def test_env_key_value_is_not_read_or_emitted(self):
        import os
        messages=[]
        with patch.dict(os.environ,{'ZAR_TEST_KEY':'private-test-secret'}):
            setup(self.root,ask=self.ask,emit=messages.append)
        self.assertNotIn('private-test-secret','\n'.join(messages))
        self.assertIn('ZAR_TEST_KEY','\n'.join(messages))
