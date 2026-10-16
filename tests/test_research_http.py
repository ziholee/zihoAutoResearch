"""Unmocked CLI + loopback HTTP + local execution lifecycle (no paid API)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from zar import cli
from zar.codec import dumps, loads

REPO = Path(__file__).resolve().parents[1]
KEY = 'synthetic-local-api-key-not-a-real-secret'
NEW_CODE = ('import os\nfrom pathlib import Path\n'
            'assert "ZAR_TEST_KEY" not in os.environ\n'
            'Path("executed.txt").write_text("once")\n'
            'Path("metric.json").write_text(\'{"score": 0.25}\')\n')


class ResearchHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        cli.initialize(self.root)
        self.original = NEW_CODE
        (self.root / 'train.py').write_text(self.original)
        project = loads((self.root / '.autoresearch/project.json').read_text())
        project.update(name='loopback', objective='Synthetic approved execution',
            comparison=dict(id='cmp', dataset_ref='synthetic', split_ref='fixed',
                metric='score', direction='minimize', evaluation_ref='v1', min_delta=0),
            environment=dict(os='other', runtime='python', device='cpu'),
            commands=[dict(name='train', argv=[sys.executable, 'train.py'], cwd='.')],
            budget=dict(max_experiments=3, max_run_seconds=5), editable_paths=['train.py'])
        (self.root / '.autoresearch/project.json').write_text(dumps(project))
        self.requests = []
        self.mode = 'normal'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.path, self.headers.get('Authorization'), payload))
                context = json.loads(payload['messages'][-1]['content'])
                role = context['role']
                body = dict(summary='Synthetic fixture evidence', evidence=['train.py'], uncertainties=[])
                body.update({
                    'analysis': dict(missing=[]),
                    'evaluation': dict(verdict='hold' if owner.mode == 'hold' else 'pass'),
                    'planning': dict(hypothesis='Approved new script produces a measured score'),
                    'implementation': dict(changes=[] if context.get('experiment_mode')=='baseline' else [dict(path='train.py',
                        before_sha256=context['sources']['train.py']['sha256'], content=NEW_CODE)]),
                    'review': dict(verdict='pass'),
                    'interpretation': dict(decision='keep', reason='Observed score from local execution'),
                    'memory': dict(next_action='stop', lesson='One approved execution', limitation='Synthetic only'),
                }[role])
                content = '{invalid' if owner.mode == 'malformed' else json.dumps(body)
                response = json.dumps(dict(choices=[dict(message=dict(role='assistant', content=content),
                    finish_reason='stop')], usage=dict(prompt_tokens=100, completion_tokens=20, total_tokens=120))).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/v1'

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def invoke(self, *args, expected=0):
        env = dict(os.environ, ZAR_TEST_KEY=KEY, NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
        proc = subprocess.run([sys.executable, '-m', 'zar', 'research', *args,
            '--project', str(self.root), '--json'], cwd=REPO, env=env,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        self.assertNotIn(KEY, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result['ok'], expected == 0)
        return result['data'] if expected == 0 else result

    def start(self):
        return self.invoke('start', '--base-url', self.endpoint, '--model', 'mock',
            '--api-key-env', 'ZAR_TEST_KEY', '--goal', 'Run one synthetic experiment',
            '--read', 'train.py', '--command', 'train', '--metric-file', 'metric.json',
            '--metric-key', 'score', '--budget-ref', 'test', '--seed', '42')

    def assert_no_execution(self):
        self.assertEqual((self.root / 'train.py').read_text(), self.original)
        self.assertFalse((self.root / 'metric.json').exists())
        self.assertFalse((self.root / 'executed.txt').exists())
        self.assertEqual(list((self.root / '.autoresearch/experiments').glob('*.json')), [])

    def test_public_cli_runs_unchanged_baseline_and_selects_observed_result(self):
        session = self.start()
        identifier = session['id']
        self.assertEqual(session['state'], 'planning')
        self.assertEqual(self.requests, [])
        self.invoke('advance', identifier, expected=3)
        self.assertEqual(self.requests, [])
        session = self.invoke('advance', identifier, '--send')
        self.assertEqual(session['state'], 'awaiting_approval')
        self.assertEqual(session['diff'],'')
        self.assert_no_execution()
        self.invoke('run', identifier, expected=3)
        self.assert_no_execution()
        session = self.invoke('status', identifier)
        self.invoke('approve', identifier, '--token', session['approval_token'])
        self.assert_no_execution()
        session = self.invoke('run', identifier)
        self.assertEqual(session['state'], 'observed')
        self.assertEqual((self.root / 'train.py').read_text(), NEW_CODE)
        self.assertEqual(json.loads((self.root / 'metric.json').read_text())['score'], .25)
        self.invoke('run', identifier, expected=3)
        session = self.invoke('advance', identifier, '--send')
        self.assertEqual(session['state'], 'awaiting_decision')
        session = self.invoke('decide', identifier, '--token', session['approval_token'], '--select')
        self.assertEqual(session['state'], 'remembering')
        session = self.invoke('advance', identifier, '--send')
        self.assertEqual(session['state'], 'complete')
        project = loads((self.root / '.autoresearch/project.json').read_text())
        self.assertEqual(project['selected_experiment_id'], session['experiment_id'])
        experiment = loads((self.root / '.autoresearch/experiments' / (session['experiment_id'] + '.json')).read_text())
        self.assertEqual(experiment['execution']['score'], .25)
        self.assertEqual(experiment['decision']['status'], 'keep')
        roles = []
        systems = []
        for path, auth, payload in self.requests:
            self.assertEqual(path, '/v1/chat/completions')
            self.assertEqual(auth, 'Bearer ' + KEY)
            self.assertEqual(payload['model'], 'mock')
            self.assertFalse(payload['stream'])
            self.assertNotIn('tools', payload)
            context = json.loads(payload['messages'][-1]['content'])
            roles.append(context['role'])
            systems.append(payload['messages'][0]['content'])
            self.assertIn('role=' + context['role'], systems[-1])
            if context['role'] == 'interpretation':
                self.assertEqual(context['observation']['execution']['score'], .25)
            if context['role'] == 'memory':
                self.assertEqual(context['observation']['decision']['status'], 'keep')
        self.assertEqual(roles, ['analysis', 'evaluation', 'planning', 'implementation', 'review', 'interpretation', 'memory'])
        self.assertEqual(len(set(systems)), 7)
        for path in (self.root / '.autoresearch').rglob('*'):
            if path.is_file():
                self.assertNotIn(KEY.encode(), path.read_bytes(), str(path))

    def test_evaluation_hold_stops_before_edit_or_execution(self):
        self.mode = 'hold'
        session = self.start()
        session = self.invoke('advance', session['id'], '--send')
        self.assertEqual(session['state'], 'blocked')
        self.assertEqual(len(self.requests), 2)
        self.assert_no_execution()
        self.invoke('run', session['id'], expected=3)

    def test_malformed_response_consumes_call_without_edit_or_execution(self):
        self.mode = 'malformed'
        session = self.start()
        self.invoke('advance', session['id'], '--send', expected=3)
        session = self.invoke('status', session['id'])
        self.assertEqual(session['state'], 'planning')
        self.assertEqual(session['calls'], 1)
        self.assertEqual(session['outputs'], {})
        self.assertEqual(session['error'], 'invalid_role_response')
        self.assert_no_execution()
