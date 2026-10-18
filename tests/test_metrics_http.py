"""Public CLI measurements with a loopback provider; no paid model calls."""
import json
import unittest
from tests import test_research_http as fixture


class MetricsHTTPTests(unittest.TestCase):
    setUp=fixture.ResearchHTTPTests.setUp
    stop_server=fixture.ResearchHTTPTests.stop_server
    invoke=fixture.ResearchHTTPTests.invoke
    start=fixture.ResearchHTTPTests.start

    def test_metrics_count_actual_messages_and_provider_usage_read_only(self):
        s=self.start();identifier=s['id']
        before=self.invoke('metrics',identifier)
        self.assertEqual(before['total']['attempts'],0)
        self.assertIsNone(before['total']['call_seconds']['value'])
        self.assertEqual(self.requests,[])
        s=self.invoke('advance',identifier,'--send')
        self.assertEqual(s['state'],'awaiting_approval')
        sent=sum(len(m['content'].encode('utf-8')) for _,_,p in self.requests for m in p['messages'])
        report=self.invoke('metrics',identifier)
        self.assertEqual(report['total']['input_message_bytes'],{'value':sent,'observations':5})
        self.assertEqual(report['total']['tokens']['total_tokens'],{'value':600,'observations':5})
        self.assertEqual(report['roles']['analysis']['tokens']['input_tokens'],{'value':100,'observations':1})
        self.assertEqual(report['total']['call_seconds']['observations'],5)
        self.assertEqual(len(self.requests),5)
        serialized=json.dumps(report)
        for raw in ('train.py',fixture.KEY,self.endpoint,'Synthetic fixture evidence'):
            self.assertNotIn(raw,serialized)
        self.assertFalse((self.root/'metric.json').exists())

    def test_invalid_role_response_is_measured_before_validation(self):
        s=self.start();self.mode='malformed'
        self.invoke('advance',s['id'],'--send',expected=3)
        report=self.invoke('metrics',s['id'])
        self.assertEqual(report['total']['output_text_bytes'],{'value':len('{invalid'.encode()),'observations':1})
        self.assertEqual(report['total']['tokens']['total_tokens'],{'value':120,'observations':1})
        self.assertEqual(len(self.requests),1)
