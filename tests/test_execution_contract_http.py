"""Fresh CLI processes, loopback-only credentials and harmless temp markers."""
import sys
import unittest

from zar import research
from zar.codec import dumps, loads
import test_research_http as helpers


class ExecutionContractHTTPTests(unittest.TestCase):
    setUp = helpers.ResearchHTTPTests.setUp
    stop_server = helpers.ResearchHTTPTests.stop_server
    invoke = helpers.ResearchHTTPTests.invoke
    start = helpers.ResearchHTTPTests.start
    assert_no_execution = helpers.ResearchHTTPTests.assert_no_execution

    def session_file(self, identifier):
        return self.root / '.autoresearch/sessions' / (identifier + '.json')

    def test_rehashed_approved_command_cannot_launch_unconfigured_program(self):
        session = self.start()
        session = self.invoke('advance', session['id'], '--send')
        self.invoke('approve', session['id'], '--token', session['approval_token'])
        path = self.session_file(session['id'])
        stored = loads(path.read_text(encoding='utf-8'))
        stored['command']['argv'] = [sys.executable, '-c',
            'from pathlib import Path; Path("unconfigured.txt").write_text("ran"); '
            'Path("metric.json").write_text(\'{"score": 1}\')']
        stored['approval_token'] = research.token(stored)
        path.write_text(dumps(stored), encoding='utf-8')
        self.invoke('run', session['id'], expected=3)
        self.assertFalse((self.root / 'unconfigured.txt').exists())
        self.assert_no_execution()

    def test_changed_saved_endpoint_sends_no_request_even_with_send_flag(self):
        session = self.start()
        path = self.session_file(session['id'])
        stored = loads(path.read_text(encoding='utf-8'))
        stored['profile']['base_url'] = self.endpoint + '/different-destination'
        path.write_text(dumps(stored), encoding='utf-8')
        self.invoke('advance', session['id'], '--send', expected=3)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.invoke('status', session['id'])['calls'], 0)
        self.assert_no_execution()


    def test_profile_changed_during_http_call_blocks_output_and_following_calls(self):
        session = self.start()
        path = self.session_file(session['id'])
        original_handler = self.server.RequestHandlerClass

        class ChangingHandler(original_handler):
            def do_POST(handler):
                stored = loads(path.read_text(encoding='utf-8'))
                stored['profile']['model'] = 'changed-during-call'
                path.write_text(dumps(stored), encoding='utf-8')
                super().do_POST()

        self.server.RequestHandlerClass = ChangingHandler
        self.invoke('advance', session['id'], '--send', expected=3)
        self.assertEqual(len(self.requests), 1)
        current = self.invoke('status', session['id'])
        self.assertEqual(current['state'], 'blocked')
        self.assertEqual(current['calls'], 1)
        self.assertEqual(current['outputs'], {})
        self.assert_no_execution()


if __name__ == '__main__':
    unittest.main()
