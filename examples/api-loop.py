#!/usr/bin/env python3
"""Synthetic API-to-experiment demonstration; no cloud API or ML training.

Run with the Python interpreter where ziho-autoresearch is installed:
    python examples/api-loop.py --output /absolute/new-directory

The loopback provider emits deterministic proposals. The script explicitly
approves its known fixture change and command, then saves public CLI events.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

ROLES = ['analysis', 'evaluation', 'planning', 'implementation', 'review',
         'interpretation', 'memory']
KEY = 'synthetic-loopback-token'
ORIGINAL = 'raise RuntimeError("original script must not execute")\n'
PROPOSED = ('import os\nfrom pathlib import Path\n'
            'assert "ZAR_MOCK_API_KEY" not in os.environ\n'
            'Path("metric.json").write_text(\'{"score": 0.25}\')\n'
            'print("synthetic execution completed")\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='new directory; existing paths are refused')
    args = parser.parse_args()
    # Refuse an existing final path, including dangling symlinks.
    output = args.output.absolute()
    output.mkdir(parents=False, exist_ok=False)
    output = output.resolve()
    project = output / 'project'
    project.mkdir()
    events = []
    observed_roles = []
    env = dict(os.environ, ZAR_MOCK_API_KEY=KEY, NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')

    def command(*argv):
        result = subprocess.run([sys.executable, '-m', 'zar', *argv,
            '--project', str(project), '--json'], env=env, capture_output=True,
            text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f'CLI command {argv[0]} failed: {result.stdout} {result.stderr}')
        response = json.loads(result.stdout)
        if not response['ok']:
            raise RuntimeError('CLI did not report success')
        events.append(dict(command=list(argv), response=response))
        (output / 'events.json').write_text(json.dumps(events, indent=2) + '\n', encoding='utf-8')
        return response['data']

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != '/v1/chat/completions' or self.headers.get('Authorization') != 'Bearer ' + KEY:
                self.send_error(400)
                return
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            context = json.loads(payload['messages'][-1]['content'])
            role = context['role']
            observed_roles.append(role)
            body = dict(summary='Synthetic source evidence', evidence=['train.py'], uncertainties=[])
            body.update({
                'analysis': dict(missing=[]),
                'evaluation': dict(verdict='pass'),
                'planning': dict(hypothesis='Known approved fixture emits score 0.25'),
                'implementation': dict(changes=[dict(path='train.py',
                    before_sha256=context['sources']['train.py']['sha256'], content=PROPOSED)]),
                'review': dict(verdict='pass'),
                'interpretation': dict(decision='keep', reason='Measured local fixture result'),
                'memory': dict(next_action='stop', lesson='Known fixture completed', limitation='Synthetic, not ML evidence'),
            }[role])
            raw = json.dumps(dict(choices=[dict(message=dict(role='assistant', content=json.dumps(body)),
                finish_reason='stop')])).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        command('init')
        (project / 'train.py').write_text(ORIGINAL, encoding='utf-8')
        settings = json.loads((project / '.autoresearch/project.json').read_text())
        settings.update(name='synthetic-api-loop', objective='Demonstrate supervised local execution',
            comparison=dict(id='synthetic-v1', dataset_ref='synthetic', split_ref='fixed', metric='score',
                direction='minimize', evaluation_ref='synthetic-v1', min_delta=0),
            environment=dict(os='other', runtime='python', device='cpu'),
            commands=[dict(name='train', argv=[sys.executable, 'train.py'], cwd='.')],
            editable_paths=['train.py'], budget=dict(max_experiments=1, max_run_seconds=5))
        config = output / 'project-input.json'
        config.write_text(json.dumps(settings), encoding='utf-8')
        command('project', 'set', '--file', str(config))
        session = command('research', 'start', '--base-url', f'http://127.0.0.1:{server.server_port}/v1',
            '--model', 'synthetic', '--api-key-env', 'ZAR_MOCK_API_KEY', '--goal', 'Run the known fixture once',
            '--read', 'train.py', '--command', 'train', '--metric-file', 'metric.json', '--metric-key', 'score',
            '--budget-ref', 'synthetic-five-seconds', '--seed', '42')
        identifier = session['id']
        assert not observed_roles
        session = command('research', 'advance', identifier, '--send')
        assert session['state'] == 'awaiting_approval'
        assert (project / 'train.py').read_text() == ORIGINAL
        assert not (project / 'metric.json').exists()
        session = command('research', 'status', identifier)
        command('research', 'approve', identifier, '--token', session['approval_token'])
        session = command('research', 'run', identifier)
        assert session['state'] == 'observed'
        assert json.loads((project / 'metric.json').read_text())['score'] == .25
        session = command('research', 'advance', identifier, '--send')
        assert session['state'] == 'awaiting_decision'
        session = command('research', 'decide', identifier, '--token', session['approval_token'], '--select')
        assert session['state'] == 'remembering'
        session = command('research', 'advance', identifier, '--send')
        assert session['state'] == 'complete'
        assert observed_roles == ROLES
        final_project = json.loads((project / '.autoresearch/project.json').read_text())
        assert final_project['selected_experiment_id'] == session['experiment_id']
        experiment = json.loads((project / '.autoresearch/experiments' / (session['experiment_id'] + '.json')).read_text())
        assert experiment['execution']['score'] == .25
        assert experiment['decision']['status'] == 'keep'
        for path in output.rglob('*'):
            if path.is_file():
                assert KEY.encode() not in path.read_bytes(), f'Unexpected key in {path.name}'
        summary = dict(synthetic=True, state=session['state'], score=.25,
            selected_experiment_id=session['experiment_id'], roles=observed_roles,
            events=str(output / 'events.json'))
        (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(summary, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == '__main__':
    main()
