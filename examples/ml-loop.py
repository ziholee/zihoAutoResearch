#!/usr/bin/env python3
"""Real synthetic-data regression with a mock LLM and explicit CLI approvals.

python examples/ml-loop.py --output /absolute/new-directory [--pause]
python examples/ml-loop.py --output /absolute/same-directory --resume

Default runs the resume stage in a fresh process. --pause exits after candidate
execution and before interpretation/selection. This is a safe-boundary pause,
not interruption/recovery of an in-flight process. No external API is called.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import threading

KEY = 'local-ml-demo-token'
BASELINE = '''METRIC_FILE = 'baseline.json'
def fit(rows):
    mean = sum(y for x, y in rows) / len(rows)
    return lambda x: mean
'''
CANDIDATE = '''METRIC_FILE = 'candidate.json'
def fit(rows):
    mx = sum(x for x, y in rows) / len(rows)
    my = sum(y for x, y in rows) / len(rows)
    slope = sum((x-mx)*(y-my) for x, y in rows) / sum((x-mx)**2 for x, y in rows)
    intercept = my - slope * mx
    return lambda x: intercept + slope * x
'''
EVALUATOR = '''import json
import os
from pathlib import Path
import model
assert 'ZAR_MOCK_API_KEY' not in os.environ
train = json.loads(Path('train.json').read_text())
predict = model.fit(train)
holdout = json.loads(Path('holdout.json').read_text())
score = sum((predict(x)-y)**2 for x, y in holdout) / len(holdout)
Path(model.METRIC_FILE).write_text(json.dumps({'mse': score}) + '\\n')
with Path('executions.jsonl').open('a') as log:
    log.write(json.dumps({'metric_file': model.METRIC_FILE, 'score': score}) + '\\n')
print(json.dumps({'mse': score}))
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dataset(seed, size):
    rng = random.Random(seed)
    return [[x := rng.uniform(-2, 2), 1.5 + 2.0*x + rng.gauss(0, .15)] for _ in range(size)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--pause', action='store_true')
    mode.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    output = args.output.absolute()
    if not args.resume:
        output.mkdir(parents=False, exist_ok=False)
    output = output.resolve(strict=True)
    project = output / 'project'
    checkpoint_path = output / 'checkpoint.json'
    checkpoint = load(checkpoint_path) if args.resume else {}
    if args.resume:
        require(checkpoint['state'] == 'paused_after_observation', 'Only a paused observation can resume')
    else:
        project.mkdir()
    events = load(output / 'events.json') if args.resume else []
    roles = load(output / 'roles.json') if args.resume else []
    env = dict(os.environ, ZAR_MOCK_API_KEY=KEY, NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')

    def command(*argv):
        result = subprocess.run([sys.executable, '-m', 'zar', *argv, '--project', str(project), '--json'],
                                env=env, capture_output=True, text=True, timeout=30)
        require(result.returncode == 0, f'CLI {argv} failed: {result.stdout} {result.stderr}')
        response = json.loads(result.stdout)
        require(response['ok'], 'CLI did not report success')
        require(not any(d['severity'] == 'error' for d in response['diagnostics']), 'CLI reported error diagnostics')
        events.append(dict(command=list(argv), response=response))
        save(output / 'events.json', events)
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
            roles.append(dict(role=role, mode=context['experiment_mode']))
            save(output / 'roles.json', roles)
            body = dict(summary='Known synthetic regression fixture', evidence=['model.py'], uncertainties=[])
            body.update({
                'analysis': dict(missing=[]),
                'evaluation': dict(verdict='pass'),
                'planning': dict(hypothesis='Train-only linear regression should outperform a fitted mean on linear synthetic data'),
                'implementation': dict(changes=[] if context['experiment_mode'] == 'baseline' else [dict(
                    path='model.py', before_sha256=context['sources']['model.py']['sha256'], content=CANDIDATE)]),
                'review': dict(verdict='pass'),
                'interpretation': dict(decision='keep', reason='Measured fixed holdout MSE; demonstration only'),
                'memory': dict(next_action='stop', lesson='One fixed train/evaluation split completed',
                               limitation='Synthetic regression, no real model-provider validation or generalization claim'),
            }[role])
            if role == 'interpretation' and context['experiment_mode'] == 'candidate':
                improvement = context['comparison']['improvement']
                body['decision'] = 'keep' if improvement > 0 else 'discard'
                body['reason'] = f'Measured fixed holdout MSE improvement: {improvement}'
            # No fabricated usage: token counts remain unknown in research metrics.
            raw = json.dumps(dict(choices=[dict(message=dict(role='assistant', content=json.dumps(body)), finish_reason='stop')])).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    class Server(ThreadingHTTPServer):
        allow_reuse_address = True

    server = Server(('127.0.0.1', checkpoint['port'] if args.resume else 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def finish(session):
        sid = session['id']
        session = command('research', 'advance', sid, '--send')
        require(session['state'] == 'awaiting_decision', 'Expected decision boundary')
        session = command('research', 'decide', sid, '--token', session['approval_token'], '--select')
        require(session['state'] == 'remembering', 'Expected memory boundary')
        session = command('research', 'advance', sid, '--send')
        require(session['state'] == 'complete', 'Expected completed session')
        return session

    def check_protected():
        require(all(digest(project / path) == expected for path, expected in checkpoint['protected'].items()),
                'Protected evaluator or split changed')

    try:
        if not args.resume:
            command('init')
            (project / 'model.py').write_text(BASELINE, encoding='utf-8')
            (project / 'evaluate.py').write_text(EVALUATOR, encoding='utf-8')
            save(project / 'train.json', dataset(42, 96))
            save(project / 'holdout.json', dataset(2026, 64))
            checkpoint = dict(port=server.server_port, protected={p: digest(project / p) for p in ('evaluate.py', 'train.json', 'holdout.json')})
            settings = load(project / '.autoresearch/project.json')
            settings.update(name='synthetic-regression-loop', objective='Measure trained mean versus trained linear regression',
                comparison=dict(id='synthetic-regression-v1', dataset_ref='synthetic-linear-noise-v1', split_ref='train42-eval2026',
                                metric='mse', direction='minimize', evaluation_ref='fixed-mse-v1', min_delta=0),
                environment=dict(os='other', runtime='python', device='cpu'),
                commands=[dict(name='validate', argv=[sys.executable, '-B', 'evaluate.py'], cwd='.')],
                editable_paths=['model.py'], budget=dict(max_experiments=2, max_run_seconds=10))
            save(output / 'project-input.json', settings)
            command('project', 'set', '--file', str(output / 'project-input.json'))
            for mode_name in ('baseline', 'candidate'):
                session = command('research', 'start', '--base-url', f'http://127.0.0.1:{server.server_port}/v1',
                    '--model', 'mock-regression', '--api-key-env', 'ZAR_MOCK_API_KEY', '--goal', 'Fit and compare fixed synthetic regression',
                    '--read', 'model.py', '--read', 'evaluate.py', '--command', 'validate', '--metric-file', mode_name + '.json',
                    '--metric-key', 'mse', '--budget-ref', 'synthetic-regression-ten-seconds', '--seed', '42', '--mode', mode_name)
                sid = session['id']
                original = (project / 'model.py').read_bytes()
                session = command('research', 'advance', sid, '--send')
                require(session['state'] == 'awaiting_approval', 'Expected execution approval boundary')
                require((project / 'model.py').read_bytes() == original, 'Proposal applied before approval')
                require(not (project / (mode_name + '.json')).exists(), 'Experiment ran before approval')
                check_protected()
                # Explicit, scripted approval only for the known fixture proposal.
                changes = session['outputs']['implementation']['changes']
                require(changes == ([] if mode_name == 'baseline' else [dict(path='model.py', before_sha256=hashlib.sha256(original).hexdigest(), content=CANDIDATE)]), 'Unexpected proposal')
                command('research', 'approve', sid, '--token', session['approval_token'])
                session = command('research', 'run', sid)
                require(session['state'] == 'observed', 'Expected measured observation')
                check_protected()
                if mode_name == 'candidate':
                    require(0 <= load(project / 'candidate.json')['mse'] < load(project / 'baseline.json')['mse'],
                            'Candidate did not improve measured holdout MSE')
                checkpoint[mode_name + '_session_id'] = sid
                checkpoint[mode_name + '_experiment_id'] = session['experiment_id']
                if mode_name == 'baseline':
                    finish(session)
                    baseline_path = project / '.autoresearch/experiments' / (session['experiment_id'] + '.json')
                    require(load(baseline_path)['execution']['score'] == load(project / 'baseline.json')['mse'],
                            'Baseline recorded metric differs from evaluator')
                    checkpoint['baseline_record_sha256'] = digest(baseline_path)
            checkpoint.update(state='paused_after_observation', model_sha256=digest(project / 'model.py'),
                              execution_sha256=digest(project / 'executions.jsonl'))
            save(checkpoint_path, checkpoint)
            save(output / 'summary.json', dict(state=checkpoint['state'], execution_count=2,
                                             resume_command=[sys.executable, str(Path(__file__).resolve()), '--output', str(output), '--resume']))
        else:
            check_protected()
            require(digest(project / 'model.py') == checkpoint['model_sha256'], 'Model changed during pause')
            require(digest(project / 'executions.jsonl') == checkpoint['execution_sha256'], 'Executions changed during pause')
            session = command('research', 'status', checkpoint['candidate_session_id'])
            require(session['state'] == 'observed', 'Expected persisted observed state')
            session = finish(session)
            require(digest(project / 'executions.jsonl') == checkpoint['execution_sha256'], 'Resume executed experiment again')
            logs = [json.loads(line) for line in (project / 'executions.jsonl').read_text().splitlines()]
            require([row['metric_file'] for row in logs] == ['baseline.json', 'candidate.json'], 'Expected exactly one execution per model')
            baseline = load(project / 'baseline.json')['mse']
            candidate = load(project / 'candidate.json')['mse']
            require(0 <= candidate < baseline, 'Expected fitted linear model to improve holdout MSE')
            record = load(project / '.autoresearch/experiments' / (session['experiment_id'] + '.json'))
            baseline_path = project / '.autoresearch/experiments' / (checkpoint['baseline_experiment_id'] + '.json')
            require(digest(baseline_path) == checkpoint['baseline_record_sha256'], 'Completed baseline record changed')
            require(record['baseline_id'] == checkpoint['baseline_experiment_id'], 'Candidate lost baseline lineage')
            require(record['execution']['score'] == candidate, 'Recorded metric differs from evaluator')
            require(load(project / '.autoresearch/project.json')['selected_experiment_id'] == session['experiment_id'], 'Candidate not selected')
            comparison = command('experiment', 'compare', checkpoint['baseline_experiment_id'], session['experiment_id'])
            require(comparison['improvement'] == baseline - candidate, 'Public comparison disagrees with measured scores')
            check = command('check')
            status = command('status')
            require(not status['unfinished'], 'Unexpected unfinished experiment')
            metrics = {name: command('research', 'metrics', checkpoint[name + '_session_id']) for name in ('baseline', 'candidate')}
            check_protected()
            for path in output.rglob('*'):
                if path.is_file():
                    require(KEY.encode() not in path.read_bytes(), 'Unexpected persisted API key')
            summary = dict(state='complete', mock_llm=True, actual_training=True, synthetic_data=True,
                baseline_score=baseline, candidate_score=candidate, improvement=baseline-candidate,
                execution_count=len(logs), pause_state='observed', resumed_without_execution=True,
                baseline_experiment_id=checkpoint['baseline_experiment_id'], candidate_experiment_id=session['experiment_id'],
                comparison=comparison, check=check, status=status, metrics=metrics, events=str(output / 'events.json'))
            save(output / 'summary.json', summary)
            checkpoint['state'] = 'complete'
            save(checkpoint_path, checkpoint)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    if not args.resume and not args.pause:
        # Terminate the first provider before a new process reloads saved state.
        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--output', str(output), '--resume'], check=True)
    else:
        print(json.dumps(load(output / 'summary.json'), indent=2))


if __name__ == '__main__':
    main()
