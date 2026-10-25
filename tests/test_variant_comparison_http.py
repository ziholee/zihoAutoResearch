"""Approved role variants across fresh CLI processes and a loopback provider."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler
import json
import os
import subprocess
import sys
import threading
import unittest

from zar.codec import dumps, loads
import test_research_http as helpers


class VariantComparisonHTTPTests(unittest.TestCase):
    setUp = helpers.ResearchHTTPTests.setUp
    stop_server = helpers.ResearchHTTPTests.stop_server
    invoke = helpers.ResearchHTTPTests.invoke
    start = helpers.ResearchHTTPTests.start
    assert_no_execution = helpers.ResearchHTTPTests.assert_no_execution

    def saved(self, identifier):
        return loads((self.root / '.autoresearch/sessions' / (identifier + '.json')).read_text())

    def prepare(self, session):
        path = self.root / 'variant.md'
        path.write_text('Review the supplied evidence carefully. State missing evidence explicitly.\n')
        comparison = self.invoke('variant-prepare', session['id'], '--file', path.relative_to(self.root).as_posix())
        self.assertEqual(comparison['state'], 'awaiting_approval')
        return comparison, path

    def approve(self, comparison):
        return self.invoke('variant-approve', comparison['id'], '--token', comparison['approval_token'])

    def test_approved_pair_shares_input_model_budget_without_selecting_or_executing(self):
        session = self.start()
        original_outputs = deepcopy(self.saved(session['id'])['outputs'])
        comparison, _ = self.prepare(session)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.invoke('status', session['id'])['state'], 'comparing')
        self.invoke('variant-advance', comparison['id'], '--send', expected=3)
        self.invoke('advance', session['id'], '--send', expected=3)
        self.assertEqual(self.requests, [])
        self.approve(comparison)
        self.invoke('variant-advance', comparison['id'], expected=3)
        self.assertEqual(self.requests, [])
        result = self.invoke('variant-advance', comparison['id'], '--send')
        self.assertEqual(len(self.requests), 2)
        original, variant = [entry[2] for entry in self.requests]
        self.assertEqual(original['model'], variant['model'])
        self.assertEqual(original['max_completion_tokens'], variant['max_completion_tokens'])
        self.assertEqual(original['messages'][-1], variant['messages'][-1])
        self.assertNotEqual(original['messages'][:-1], variant['messages'][:-1])
        self.assertEqual(result['summary']['status'], 'hold')
        self.assertFalse(result['summary']['automatic_selection'])
        self.assertEqual([result['arms'][name]['state'] for name in ('original', 'variant')], ['validated', 'validated'])
        parent = self.saved(session['id'])
        self.assertEqual(parent['calls'], 2)
        self.assertEqual(parent['outputs'], original_outputs)
        self.assertEqual(parent['state'], session['state'])
        self.assert_no_execution()
        resumed = self.invoke('advance', session['id'], '--send')
        self.assertEqual(resumed['state'], 'awaiting_approval')
        self.assertEqual(resumed['calls'], 7)
        self.invoke('run', session['id'], expected=3)
        self.invoke('approve', session['id'], '--token', resumed['approval_token'])
        self.assertEqual(self.invoke('run', session['id'])['state'], 'observed')

    def test_changed_variant_file_blocks_transmission_and_can_be_cancelled(self):
        session = self.start()
        comparison, path = self.prepare(session)
        self.approve(comparison)
        path.write_text('A changed instruction after approval.\n')
        self.invoke('variant-advance', comparison['id'], '--send', expected=3)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.saved(session['id'])['calls'], 0)
        self.invoke('variant-cancel', comparison['id'])
        self.assertEqual(self.invoke('status', session['id'])['state'], session['state'])
        self.assert_no_execution()

    def test_changed_source_blocks_transmission(self):
        session = self.start()
        comparison, _ = self.prepare(session)
        self.approve(comparison)
        (self.root / 'train.py').write_text(self.original + '\n# Changed after approval\n')
        self.invoke('variant-advance', comparison['id'], '--send', expected=3)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.saved(session['id'])['calls'], 0)

    def test_insufficient_parent_call_budget_rejects_pair_before_transmission(self):
        session = self.start()
        saved = self.saved(session['id'])
        saved['max_calls'] = 1
        (self.root / '.autoresearch/sessions' / (session['id'] + '.json')).write_text(dumps(saved))
        path = self.root / 'variant.md'
        path.write_text('State missing evidence explicitly.\n')
        self.invoke('variant-prepare', session['id'], '--file', path.relative_to(self.root).as_posix(), expected=3)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.saved(session['id'])['state'], 'planning')

    def test_versionless_parent_retains_legacy_contract_after_pair(self):
        session = self.start()
        saved = self.saved(session['id'])
        for key in ('memory_contract_version', 'memory_selection_version'):
            saved.pop(key, None)
        (self.root / '.autoresearch/sessions' / (session['id'] + '.json')).write_text(dumps(saved))
        comparison, _ = self.prepare(session)
        self.approve(comparison)
        self.invoke('variant-advance', comparison['id'], '--send')
        parent = self.saved(session['id'])
        self.assertNotIn('memory_contract_version', parent)
        self.assertNotIn('memory_selection_version', parent)
        resumed = self.invoke('advance', session['id'], '--send')
        self.assertEqual(resumed['state'], 'awaiting_approval')
        self.assertEqual(resumed['calls'], 7)
        self.assert_no_execution()

    def test_killed_cli_preserves_unknown_and_sends_only_unattempted_variant(self):
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.path, self.headers.get('Authorization'), payload))
                first = len(owner.requests) == 1
                if first:
                    entered.set()
                    release.wait(timeout=10)
                body = dict(summary='Synthetic analysis', evidence=['train.py'], uncertainties=[], missing=[])
                response = json.dumps(dict(choices=[dict(message=dict(role='assistant', content=json.dumps(body)),
                    finish_reason='stop')], usage=dict(prompt_tokens=100, completion_tokens=20, total_tokens=120))).encode()
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # The original CLI was deliberately killed after its request arrived.
                finally:
                    if first:
                        finished.set()

        self.server.RequestHandlerClass = Handler
        self.addCleanup(release.set)
        session = self.start()
        comparison, _ = self.prepare(session)
        self.approve(comparison)
        env = dict(os.environ, ZAR_TEST_KEY=helpers.KEY,
                   NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
        process = subprocess.Popen([sys.executable, '-m', 'zar', 'research',
            'variant-advance', comparison['id'], '--send', '--project', str(self.root), '--json'],
            cwd=helpers.REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(entered.wait(timeout=5), 'The original request never reached the provider')
            self.assertEqual(self.invoke('variant-status', comparison['id'])['state'], 'calling')
            process.kill()
            process.communicate(timeout=5)
            self.assertIsNotNone(process.returncode)
            release.set()
            self.assertTrue(finished.wait(timeout=5), 'The mock original handler did not stop')
            self.invoke('variant-advance', comparison['id'], '--send', expected=3)
            self.invoke('variant-cancel', comparison['id'], expected=3)
            self.invoke('variant-recover', comparison['id'], expected=3)
            recovered = self.invoke('variant-recover', comparison['id'], '--confirm-stopped')
            self.assertEqual(recovered['arms']['original']['state'], 'unknown')
            self.assertEqual(recovered['arms']['variant']['state'], 'pending')
            self.assertEqual(len(self.requests), 1)
            result = self.invoke('variant-advance', comparison['id'], '--send')
            self.assertEqual(result['state'], 'complete')
            self.assertEqual(result['arms']['original']['state'], 'unknown')
            self.assertEqual(result['arms']['variant']['state'], 'validated')
            self.assertEqual(result['summary']['status'], 'hold')
            self.assertFalse(result['summary']['automatic_selection'])
            self.assertEqual(len(self.requests), 2)
            self.assertEqual(self.requests[0][2]['messages'], comparison['bundle']['messages']['original'])
            self.assertEqual(self.requests[1][2]['messages'], comparison['bundle']['messages']['variant'])
            parent = self.saved(session['id'])
            self.assertEqual(parent['calls'], 2)
            self.assertEqual(parent['outputs'], {})
            self.assertEqual(parent['state'], 'planning')
            self.assert_no_execution()
        finally:
            release.set()
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
