"""Memory evidence contract across fresh CLI processes and a loopback provider."""
from http.server import BaseHTTPRequestHandler
import hashlib
import json
import unittest

from zar.codec import dumps, loads
import test_research_http as http_helpers


class SessionMemoryHTTPTests(unittest.TestCase):
    # Reuse fixtures without inheriting (and re-running) unrelated test methods.
    stop_server = http_helpers.ResearchHTTPTests.stop_server
    invoke = http_helpers.ResearchHTTPTests.invoke
    start = http_helpers.ResearchHTTPTests.start
    assert_no_execution = http_helpers.ResearchHTTPTests.assert_no_execution

    def setUp(self):
        http_helpers.ResearchHTTPTests.setUp(self)
        self.memory_mode = 'valid'
        self.memory_responses = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.path, self.headers.get('Authorization'), request))
                context = json.loads(request['messages'][-1]['content'])
                body = owner.response(context)
                response = json.dumps(dict(choices=[dict(message=dict(
                    role='assistant', content=json.dumps(body)), finish_reason='stop')],
                    usage=dict(prompt_tokens=100, completion_tokens=20, total_tokens=120))).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        self.server.RequestHandlerClass = Handler

    def response(self, context):
        role = context['role']
        body = dict(summary='Synthetic evidence', evidence=['train.py'], uncertainties=[])
        body.update({
            'analysis': dict(missing=[]),
            'evaluation': dict(verdict='pass'),
            'planning': dict(hypothesis='One synthetic score improves'),
            'implementation': dict(changes=[] if context.get('experiment_mode') == 'baseline' else [
                dict(path='train.py', before_sha256=context['sources']['train.py']['sha256'],
                     content=http_helpers.NEW_CODE.replace('0.25', '0.125'))]),
            'review': dict(verdict='pass'),
            'interpretation': dict(decision='keep', reason='Observed local execution'),
            'memory': dict(next_action='stop', lesson='A single local observation', limitation='Synthetic only'),
        }[role])
        if role == 'memory':
            if self.memory_mode != 'missing':
                body['contrast'] = dict(effect='helped', applicability='This synthetic comparison only',
                    evidence=self.evidence_handles(context))
                if self.memory_mode == 'unsupported':
                    body['contrast']['effect'] = 'causally_proven'
                elif self.memory_mode == 'forged':
                    body['contrast']['evidence'] = ['forged:unobserved-experiment']
            self.memory_responses.append(body)
        return body

    def evidence_handles(self, context):
        return list(context['memory_evidence']['handles'])

    def saved(self, identifier):
        return loads((self.root / '.autoresearch/sessions' / (identifier + '.json')).read_text())

    def through_decision(self, session):
        identifier = session['id']
        session = self.invoke('advance', identifier, '--send')
        self.assertEqual(session['state'], 'awaiting_approval')
        self.invoke('run', identifier, expected=3)
        self.invoke('approve', identifier, '--token', session['approval_token'])
        self.invoke('run', identifier)
        session = self.invoke('advance', identifier, '--send')
        self.assertEqual(session['state'], 'awaiting_decision')
        session = self.invoke('decide', identifier, '--token', session['approval_token'], '--select')
        self.assertEqual(session['state'], 'remembering')
        return session

    def complete(self, session):
        return self.invoke('advance', self.through_decision(session)['id'], '--send')

    def test_single_comparison_keeps_claim_separate_and_holds_without_extra_calls(self):
        baseline = self.complete(self.start())
        self.assertEqual(baseline['state'], 'complete')
        (self.root / 'metric.json').unlink()
        candidate = self.start()
        self.assertEqual(candidate['memory_contract_version'], 1)
        candidate = self.complete(candidate)
        assessment = candidate['memory_assessment']
        self.assertEqual(candidate['state'], 'complete')
        self.assertEqual(assessment['status'], 'hold')
        self.assertEqual(assessment['claim_effect'], 'helped')
        self.assertEqual(assessment['observed_effect'], 'helped')
        self.assertTrue(assessment['reasons'])
        self.assertIn('single_comparison_not_causal_evidence', assessment['reasons'])
        self.assertEqual(candidate['outputs']['memory'], self.memory_responses[-1])
        self.assertEqual(self.saved(candidate['id'])['memory_assessment'], assessment)
        self.assertEqual(candidate['calls'], 7)
        self.assertEqual(len(self.requests), 14)
        context = json.loads(self.requests[-1][2]['messages'][-1]['content'])
        self.assertTrue(context['comparison']['comparable'])
        self.assertTrue(context['memory_evidence']['handles'])
        self.assertEqual(context['observation']['execution']['score'], .125)
        self.assertEqual(len(context['memory_evidence']['handles']), 2)
        for handle, evidence in context['memory_evidence']['handles'].items():
            record = loads((self.root / '.autoresearch/experiments' /
                            (evidence['record_id'] + '.json')).read_text())
            sha = hashlib.sha256(dumps(record).encode('utf-8')).hexdigest()
            self.assertEqual(handle, f"experiment:{record['id']}:{sha}:/execution/score")
            self.assertEqual(evidence['sha256'], sha)
            self.assertEqual(evidence['revision'], record['revision'])
            self.assertEqual(evidence['score'], record['execution']['score'])
        self.assertEqual(assessment['provenance'], context['memory_evidence']['provenance'])

    def test_malicious_contrast_rejections_consume_budget_and_preserve_pending_state(self):
        session = self.through_decision(self.start())
        identifier = session['id']
        for index, mode in enumerate(('unsupported', 'forged', 'forged'), start=7):
            self.memory_mode = mode
            self.invoke('advance', identifier, '--send', expected=3)
            current = self.invoke('status', identifier)
            self.assertEqual(current['calls'], index)
            self.assertEqual(len(self.requests), index)
            self.assertEqual(current['state'], 'remembering')
            self.assertEqual(current['error'], 'invalid_role_response')
            self.assertNotIn('memory', current['outputs'])
            self.assertNotIn('memory_assessment', current)
        self.memory_mode = 'valid'
        self.invoke('advance', identifier, '--send', expected=3)
        current = self.invoke('status', identifier)
        self.assertEqual(current['calls'], 9)
        self.assertEqual(len(self.requests), 9)
        self.assertEqual(current['state'], 'remembering')
        self.assertEqual((self.root / 'executed.txt').read_text(), 'once')

    def test_missing_contrast_remains_accepted_conservatively(self):
        self.memory_mode = 'missing'
        session = self.complete(self.start())
        self.assertEqual(session['state'], 'complete')
        self.assertEqual(session['memory_assessment']['status'], 'hold')
        self.assertEqual(session['outputs']['memory'], self.memory_responses[-1])
        self.assertNotIn('contrast', session['outputs']['memory'])
        self.assertEqual(session['calls'], 7)

    def test_legacy_pending_session_resumes_with_approval_gate_unchanged(self):
        self.memory_mode = 'missing'
        session = self.start()
        identifier = session['id']
        saved = self.saved(identifier)
        saved.pop('memory_contract_version')
        (self.root / '.autoresearch/sessions' / (identifier + '.json')).write_text(dumps(saved))
        self.invoke('advance', identifier, expected=3)
        self.assertEqual(self.requests, [])
        self.assert_no_execution()
        session = self.invoke('advance', identifier, '--send')
        approval_token = session['approval_token']
        self.invoke('run', identifier, expected=3)
        self.assert_no_execution()
        self.assertEqual(self.invoke('status', identifier)['approval_token'], approval_token)
        self.invoke('approve', identifier, '--token', approval_token)
        self.assert_no_execution()
        self.invoke('run', identifier)
        session = self.invoke('advance', identifier, '--send')
        self.invoke('decide', identifier, '--token', session['approval_token'])
        session = self.invoke('advance', identifier, '--send')
        self.assertEqual(session['state'], 'complete')
        self.assertEqual(session['calls'], 7)
        self.assertNotIn('memory_contract_version', self.saved(identifier))
        self.assertEqual(session['outputs']['memory'], self.memory_responses[-1])
