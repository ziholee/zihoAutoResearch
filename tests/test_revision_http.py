"""Loopback provider sees human clarification, never previous approvals."""
import os
import io
from contextlib import redirect_stderr,redirect_stdout
import unittest
from unittest.mock import patch
from tests import test_research_http as fixture
from zar import research,cli
from zar.codec import loads

class RevisionHTTPTests(unittest.TestCase):
    setUp=fixture.ResearchHTTPTests.setUp
    stop_server=fixture.ResearchHTTPTests.stop_server
    invoke=fixture.ResearchHTTPTests.invoke
    start=fixture.ResearchHTTPTests.start
    assert_no_execution=fixture.ResearchHTTPTests.assert_no_execution

    def test_hold_feedback_reruns_all_roles_over_real_http(self):
        self.mode='hold';parent=self.start()
        parent=self.invoke('advance',parent['id'],'--send')
        self.assertEqual(parent['state'],'blocked');self.mode='normal'
        stderr=io.StringIO();stdout=io.StringIO();seen=set()
        class Terminal(io.StringIO):
            def isatty(self):return True
            def readline(self):
                key=stderr.getvalue().splitlines()[-1].split(':',1)[0]
                if key in seen:raise AssertionError('Unexpected reprompt: '+key)
                seen.add(key)
                return {'feedback':'Fixed evaluation protocol; reconsider the hold.','save':'yes','send':'yes'}.get(key,'')+'\n'
        with patch('sys.stdin',Terminal()),patch.dict(os.environ,{'ZAR_TEST_KEY':fixture.KEY,'NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost'}),redirect_stderr(stderr),redirect_stdout(stdout):
            code=cli.main(['research','revise',parent['id'],'--project',str(self.root),'--json'])
        self.assertEqual(code,0,stdout.getvalue()+stderr.getvalue())
        result=loads(stdout.getvalue())['data']
        self.assertNotIn(fixture.KEY,stdout.getvalue()+stderr.getvalue())
        self.assertEqual(result['session']['state'],'awaiting_approval',result)
        payloads=[loads(request[2]['messages'][-1]['content']) for request in self.requests[2:]]
        self.assertEqual([p['role'] for p in payloads],list(research.PRE))
        self.assertEqual(payloads[0]['outputs'],{})
        self.assertEqual(payloads[0]['revision_context']['prior_proposal']['evaluation']['verdict'],'hold')
        self.assertEqual(payloads[0]['revision_context']['parent_id'],parent['id'])
        self.assert_no_execution()
        for path in (self.root/'.autoresearch').rglob('*.json'):
            self.assertNotIn(fixture.KEY,path.read_text())
