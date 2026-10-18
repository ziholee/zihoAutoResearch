"""Per-attempt measurements preserve approvals, failures and unknown usage."""
import unittest
from unittest.mock import patch
from tests import test_research as fixture
from zar import research
from zar.llm import LLMError


class ResearchMetricsTests(unittest.TestCase):
    setUp=fixture.ResearchTests.setUp
    start=fixture.ResearchTests.start
    respond=fixture.ResearchTests.respond

    def test_success_measures_each_role_without_changing_approval(self):
        s=self.start();sizes=[]
        def answer(profile,messages):
            sizes.append(sum(len(m['content'].encode('utf-8')) for m in messages))
            response=self.respond(profile,messages)
            response['usage']={'prompt_tokens':8,'completion_tokens':3,'total_tokens':11}
            return response
        with patch('zar.research.chat',side_effect=answer):
            s=research.advance(self.root,s['id'],send=True)
        self.assertEqual(s['state'],'awaiting_approval')
        self.assertFalse((self.root/'metric.json').exists())
        for entry,size in zip(s['trace'],sizes):
            self.assertEqual(entry['measurement']['input_message_bytes'],size)
            self.assertGreaterEqual(entry['measurement']['call_seconds'],0)
        report=research.metrics(self.root,s['id'])
        self.assertEqual(report['total']['attempts'],5)
        self.assertEqual(report['total']['tokens']['input_tokens'],{'value':40,'observations':5})
        self.assertEqual(report['total']['tokens']['cached_input_tokens'],{'value':None,'observations':0})
        path=research.session_path(self.root,s['id']);before=path.read_bytes()
        research.metrics(self.root,s['id'])
        self.assertEqual(path.read_bytes(),before)
        research.approve(self.root,s['id'],s['approval_token'])

    def test_invalid_role_retains_returned_usage_and_size(self):
        s=self.start()
        with patch('zar.research.chat',return_value={'content':'not-json','usage':{'prompt_tokens':4,'completion_tokens':0}}):
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
        entry=research.status(self.root,s['id'])['trace'][0]
        self.assertEqual(entry['measurement']['output_text_bytes'],8)
        self.assertEqual(entry['measurement']['tokens']['output_tokens'],0)
        self.assertIsNone(entry['measurement']['tokens']['total_tokens'])

    def test_failed_attempt_and_retry_have_separate_measurements(self):
        s=self.start()
        with patch('zar.research.chat',side_effect=LLMError('timeout','safe')):
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
        with patch('zar.research.chat',side_effect=self.respond):
            s=research.advance(self.root,s['id'],send=True)
        report=research.metrics(self.root,s['id'])
        self.assertEqual(report['roles']['analysis']['attempts'],2)
        self.assertEqual(report['total']['measured_attempts'],6)
        self.assertIsNone(report['total']['tokens']['total_tokens']['value'])
        first=s['trace'][0]['measurement']
        self.assertIsNone(first['output_text_bytes'])
        self.assertGreaterEqual(first['call_seconds'],0)

    def test_inputs_changed_after_response_keeps_call_measurement(self):
        s=self.start()
        def changed(*args):
            (self.root/'train.py').write_text('# concurrent change')
            return self.respond(*args)
        with patch('zar.research.chat',side_effect=changed):
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
        s=research.status(self.root,s['id'])
        self.assertEqual(s['state'],'blocked')
        self.assertEqual(s['trace'][0]['result'],'inputs_changed')
        self.assertIsNotNone(s['trace'][0]['measurement']['output_text_bytes'])

    def test_preparation_failure_does_not_claim_call_time_or_transmission(self):
        s=self.start()
        with patch('zar.research.role_messages',side_effect=ValueError('bad context')),patch('zar.research.chat') as chat:
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
            chat.assert_not_called()
        m=research.status(self.root,s['id'])['trace'][0]['measurement']
        self.assertIsNone(m['call_seconds']);self.assertIsNone(m['input_message_bytes'])

    def test_crash_and_recovery_leave_unmeasured_attempt_visible(self):
        s=self.start()
        with patch('zar.research.chat',side_effect=SystemExit):
            with self.assertRaises(SystemExit):research.advance(self.root,s['id'],send=True)
        report=research.metrics(self.root,s['id'])
        self.assertEqual(report['state'],'calling')
        self.assertEqual(report['total']['unmeasured_attempts'],1)
        self.assertIsNone(report['total']['call_seconds']['value'])
        research.recover(self.root,s['id'],confirm_stopped=True)
        self.assertEqual(research.metrics(self.root,s['id'])['total']['unmeasured_attempts'],1)

    def test_timed_out_http_worker_cannot_later_change_measurements(self):
        import threading
        s=self.start();release=threading.Event();finished=threading.Event()
        original=research.call_api
        def delayed(*args):
            release.wait(2)
            try:return self.respond(*args)
            finally:finished.set()
        try:
            with patch('zar.research.chat',side_effect=delayed),patch('zar.research.call_api',side_effect=lambda p,m,r:original(p,m,.02)):
                with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
                path=research.session_path(self.root,s['id']);before=path.read_bytes()
                release.set();self.assertTrue(finished.wait(2))
                self.assertEqual(path.read_bytes(),before)
        finally:release.set()
        report=research.metrics(self.root,s['id'])
        self.assertEqual(report['total']['call_seconds']['observations'],1)
        self.assertIsNone(report['total']['output_text_bytes']['value'])
        self.assertIsNone(report['total']['tokens']['total_tokens']['value'])
