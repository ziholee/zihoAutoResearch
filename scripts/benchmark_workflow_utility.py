#!/usr/bin/env python3
"""Paired, scripted direct+Git versus zar+Git workflow fixture (no real LLM).

Run from an installed environment or checkout:
  python scripts/benchmark_workflow_utility.py --output NEW_DIRECTORY --repeats 3

The direct arm is a purpose-written JSON ledger, not a general-purpose product.
Both arms use 14 deterministic HTTP role replies, two actual training executions,
explicit scripted approvals, source/evidence commits, and a fresh-process resume
at the observed boundary. This measures local machinery, not human productivity,
real model quality, crash recovery, network performance, or token cost.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import platform
import runpy
from socketserver import TCPServer
import statistics
import subprocess
import sys
import threading
import time
from urllib.request import Request, urlopen

FIXTURE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'examples' / 'ml-loop.py'))
BASELINE, CANDIDATE, EVALUATOR = (FIXTURE[k] for k in ('BASELINE', 'CANDIDATE', 'EVALUATOR'))
DATASET = FIXTURE['dataset']
KEY = 'local-utility-fixture-token'
ROLES = ('analysis', 'evaluation', 'planning', 'implementation', 'review', 'interpretation', 'memory')
PROTECTED = ('evaluate.py', 'train.json', 'holdout.json')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class LoopbackServer(ThreadingHTTPServer):
    """The benchmark uses a numeric loopback address, never reverse DNS."""
    allow_reuse_address = True

    def server_bind(self):
        require(self.server_address[0] == '127.0.0.1',
                'Benchmark server must bind to 127.0.0.1')
        TCPServer.server_bind(self)
        self.server_name = 'localhost'
        self.server_port = self.server_address[1]


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8', newline='\n')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def response(context):
    role, mode = context['role'], context['experiment_mode']
    body = dict(summary='Known synthetic regression fixture', evidence=['model.py'], uncertainties=[])
    body.update({
        'analysis': dict(missing=[]), 'evaluation': dict(verdict='pass'),
        'planning': dict(hypothesis='Train-only linear regression should outperform a fitted mean on linear synthetic data'),
        'implementation': dict(changes=[] if mode == 'baseline' else [dict(path='model.py', before_sha256=context['sources']['model.py']['sha256'], content=CANDIDATE)]),
        'review': dict(verdict='pass'),
        'interpretation': dict(decision='keep', reason='Measured fixed holdout MSE; demonstration only'),
        'memory': dict(next_action='stop', lesson='One fixed train/evaluation split completed', limitation='Synthetic data and deterministic mock; no model quality claim'),
    }[role])
    if role == 'interpretation' and mode == 'candidate':
        improvement = context['comparison']['improvement']
        body.update(decision='keep' if improvement > 0 else 'discard', reason=f'Measured fixed holdout MSE improvement: {improvement}')
    return body


def verify_arm(output, arm):
    """Independent post-timing checks; recompute scores without fixture model code."""
    output = Path(output)
    project = output / 'project'
    checkpoint = load(output / 'checkpoint.json')
    require(checkpoint['state'] == 'complete', 'Incomplete checkpoint')
    require(all(digest(project / p) == h for p, h in checkpoint['protected'].items()), 'Protected data/evaluator changed')
    require(load(project / 'train.json') == DATASET(42, 96), 'Training data differs from fixed fixture')
    require(load(project / 'holdout.json') == DATASET(2026, 64), 'Holdout differs from fixed fixture')
    require((project / 'evaluate.py').read_text() == EVALUATOR, 'Evaluator differs from fixture')
    require(digest(project / 'executions.jsonl') == checkpoint['execution_sha256'], 'Resume changed execution ledger')
    require((output / 'paused-executions.jsonl').read_bytes() == (project / 'executions.jsonl').read_bytes(), 'Execution evidence changed across resume')
    train, holdout = load(project / 'train.json'), load(project / 'holdout.json')
    mx = sum(x for x, y in train) / len(train)
    my = sum(y for x, y in train) / len(train)
    slope = sum((x-mx)*(y-my) for x, y in train) / sum((x-mx)**2 for x, y in train)
    expected = {'baseline': sum((my-y)**2 for x, y in holdout) / len(holdout),
                'candidate': sum((my + slope*(x-mx)-y)**2 for x, y in holdout) / len(holdout)}
    rows = [json.loads(line) for line in (project / 'executions.jsonl').read_text().splitlines()]
    require([r['metric_file'] for r in rows] == ['baseline.json', 'candidate.json'], 'Expected exactly two ordered executions')
    evidence = load(output / 'evidence.json')
    require([r['mode'] for r in evidence] == ['baseline', 'candidate'], 'Missing normalized evidence')
    for index, mode in enumerate(('baseline', 'candidate')):
        entry = evidence[index]
        record_path = project / checkpoint[mode + '_record']
        record = load(record_path)
        if mode == 'baseline':
            require(record_path.read_bytes() == (output / 'paused-baseline-record.json').read_bytes(), 'Baseline record mutated across resume')
        score = record['execution']['score'] if arm == 'zar' else record['score']
        decision = record['decision']['status'] if arm == 'zar' else record['decision']
        require(record['id'] == entry['id'], 'Record identity differs')
        require(record['baseline_id'] == (None if mode == 'baseline' else evidence[0]['id']), 'Broken baseline lineage')
        require(decision == entry['decision'] == 'keep', 'Missing keep decision')
        require(math.isclose(score, expected[mode], rel_tol=1e-12, abs_tol=1e-12), 'Score does not match independent computation')
        require(score == entry['score'] == load(project / (mode + '.json'))['mse'] == rows[index]['score'], 'Score evidence differs')
        source = BASELINE if mode == 'baseline' else CANDIDATE
        require(entry['model_sha256'] == hashlib.sha256(source.encode()).hexdigest(), 'Model source hash differs')
        require((project / 'evidence' / (mode + '-model.py')).read_text() == source, 'Source snapshot differs')
        git_env = isolated_git_env(output)
        committed = subprocess.run(['git', 'show', entry['source_commit'] + ':model.py'], cwd=project, env=git_env, capture_output=True, check=True).stdout
        require(committed == source.encode(), 'Git source commit differs')
        if arm == 'direct':
            require(record['model_sha256'] == entry['model_sha256'], 'Direct source provenance differs')
            for name, value in record['evidence'].items():
                require(digest(project / name) == value, 'Direct record evidence differs')
            require(record['approved'] is True and record['plan']['mode'] == mode, 'Missing direct plan/approval')
        else:
            source_snapshot = {name: {'sha256': hashlib.sha256(content.encode()).hexdigest(), 'content': content}
                               for name, content in (('model.py', source), ('evaluate.py', EVALUATOR))}
            source_digest = hashlib.sha256((json.dumps(source_snapshot, ensure_ascii=False) + '\n').encode()).hexdigest()
            require(record['code_ref'] == 'source-sha256:' + source_digest, 'zar source provenance differs')
            require(record['execution']['status'] == 'succeeded', 'zar execution unsuccessful')
            for item in record['execution']['evidence']:
                # This fixture emits local file references only.
                require(digest(project / item['ref']) == item['sha256'], 'zar record evidence differs')
    selected = load(project / ('.autoresearch/project.json' if arm == 'zar' else 'direct-project.json'))['selected_experiment_id']
    require(selected == evidence[1]['id'] == load(project / 'evidence/selected.json')['selected_experiment_id'], 'Candidate not selected')
    require((project / 'model.py').read_text() == CANDIDATE, 'Final model differs')
    require(evidence[1]['score'] < evidence[0]['score'], 'Known candidate did not improve')
    history = subprocess.run(['git', 'rev-list', '--count', 'HEAD'], cwd=project, env=isolated_git_env(output), capture_output=True, check=True, text=True).stdout.strip()
    require(history == '4', 'Git history does not contain four milestones')
    # Both modes may reference the same committed evidence. Check each path
    # once in this invocation; never reuse blobs across verification calls.
    paths = []
    for mode in ('baseline', 'candidate'):
        record = load(project / checkpoint[mode + '_record'])
        paths += ['evidence/selected.json', checkpoint[mode + '_record'], 'evidence/' + mode + '-record.json', 'evidence/' + mode + '-model.py']
        paths += [item['ref'] for item in record['execution']['evidence']] if arm == 'zar' else list(record['evidence'])
    for name in dict.fromkeys(paths):
        blob = subprocess.run(['git', 'show', 'HEAD:' + name], cwd=project, env=isolated_git_env(output), capture_output=True, check=True).stdout
        require(blob == (project / name).read_bytes(), 'Git does not retain current record evidence')
    events = load(output / 'events.json')
    requests = [e for e in events if e['kind'] == 'provider']
    require([(e['mode'], e['role']) for e in requests] == [(m, r) for m in ('baseline', 'candidate') for r in ROLES], 'Unexpected provider role sequence')
    require(sum(e['kind'] == 'approval' for e in events) == 4, 'Missing scripted approvals')
    require(sum(e['kind'] == 'git_commit' for e in events) == 4, 'Missing matching Git milestones')
    return {'verified': True, 'baseline_score': evidence[0]['score'], 'candidate_score': evidence[1]['score'],
            'improvement': evidence[0]['score']-evidence[1]['score'], 'execution_count': len(rows), 'resumed_without_execution': True}


def isolated_git_env(output):
    env = dict(os.environ)
    for key in list(env):
        if key.startswith('GIT_'):
            env.pop(key)
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME='Workflow fixture', GIT_COMMITTER_NAME='Workflow fixture',
               GIT_AUTHOR_EMAIL='email@example.invalid', GIT_COMMITTER_EMAIL='email@example.invalid',
               GIT_TERMINAL_PROMPT='0')
    return env


def worker(output, arm, resume, *, profile_cli=False, poll_interval=0.01):
    output = output.resolve()
    project = output / 'project'
    if not resume:
        output.mkdir()
        project.mkdir()
    events = load(output / 'events.json') if resume else []
    checkpoint = load(output / 'checkpoint.json') if resume else {}
    evidence = load(output / 'evidence.json') if resume else []
    seconds = load(output / 'seconds.json') if resume else {}
    phase_start = time.perf_counter()
    env = dict(os.environ, ZAR_MOCK_API_KEY=KEY, NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
    phase = 'resume' if resume else 'setup'

    def event(kind, started=None, **kwargs):
        events.append(dict(kind=kind, phase=phase, seconds=0.0 if started is None else time.perf_counter()-started, **kwargs))

    def run(argv, kind='command', command_env=None, cwd=None):
        started = time.perf_counter()
        process_env = command_env or env
        profile_path = None
        if kind == 'zar_cli' and profile_cli:
            profile_path = output / ('cli-profile-' + str(len(events)) + '.json')
            launcher = str(Path(__file__).with_name('profile_local_cli.py'))
            argv = [sys.executable, '-c', 'import runpy; runpy.run_path(' + repr(launcher) + ', run_name="__main__")', *argv[3:]]
            process_env = dict(process_env, ZAR_BENCH_PROFILE=str(profile_path), ZAR_BENCH_LAUNCH=str(started))
        proc = subprocess.run(argv, cwd=cwd or project, env=process_env, capture_output=True, text=True, timeout=60)
        event(kind, started, argv=argv, returncode=proc.returncode)
        if profile_path is not None and profile_path.exists():
            events[-1]['profile'] = load(profile_path)
        require(proc.returncode == 0, f'{argv} failed: {proc.stdout} {proc.stderr}')
        return proc.stdout

    def cli(*argv):
        result = json.loads(run([sys.executable, '-m', 'zar', *argv, '--project', str(project), '--json'], 'zar_cli', cwd=Path.cwd()))
        require(result['ok'] and not any(d['severity'] == 'error' for d in result['diagnostics']), 'zar diagnostics failed')
        return result['data']

    def git(*argv):
        return run(['git', '-c', 'core.hooksPath=' + str(output / 'no-hooks'), '-c', 'commit.gpgsign=false', *argv], 'git', isolated_git_env(output)).strip()

    def commit(label, paths):
        git('add', '--', *paths)
        git('commit', '-m', label)
        sha = git('rev-parse', 'HEAD')
        event('git_commit', label=label, sha=sha)
        return sha

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            started = time.perf_counter()
            if self.path != '/v1/chat/completions' or self.headers.get('Authorization') != 'Bearer ' + KEY:
                self.send_error(400)
                return
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            context = json.loads(payload['messages'][-1]['content'])
            body = response(context)
            raw = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': json.dumps(body)}, 'finish_reason': 'stop'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            event('provider', started, role=context['role'], mode=context['experiment_mode'],
                  input_message_bytes=sum(len(m['content'].encode()) for m in payload['messages']),
                  output_text_bytes=len(json.dumps(body).encode()), response=body)

    server = LoopbackServer(('127.0.0.1', checkpoint['port'] if resume else 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': poll_interval}, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/v1'

    def direct_role(role, mode):
        context = dict(role=role, experiment_mode=mode, sources={'model.py': {'sha256': digest(project / 'model.py')}})
        if role == 'interpretation' and mode == 'candidate':
            context['comparison'] = {'improvement': load(project / 'baseline.json')['mse']-load(project / 'candidate.json')['mse']}
        payload = {'model': 'mock-regression', 'messages': [{'role': 'system', 'content': 'Known regression fixture; propose only declared changes.'}, {'role': 'user', 'content': json.dumps(context)}]}
        req = Request(url + '/chat/completions', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + KEY})
        started = time.perf_counter()
        with urlopen(req, timeout=30) as result:
            body = json.loads(json.load(result)['choices'][0]['message']['content'])
        event('direct_role', started, role=role, mode=mode)
        return body

    def record_path(mode):
        return project / checkpoint[mode + '_record']

    def finish(mode):
        if arm == 'zar':
            sid = checkpoint[mode + '_session_id']
            session = cli('research', 'advance', sid, '--send')
            require(session['state'] == 'awaiting_decision', 'Expected decision approval')
            require(session['outputs']['interpretation']['decision'] == 'keep', 'Unexpected fixture decision')
            event('approval', mode=mode, action='select')
            session = cli('research', 'decide', sid, '--token', session['approval_token'], '--select')
            session = cli('research', 'advance', sid, '--send')
            require(session['state'] == 'complete', 'Expected completion')
            record = load(record_path(mode))
            decision = record['decision']['status']
        else:
            record = load(record_path(mode))
            require(record['state'] == 'observed', 'Direct ledger not observed')
            interpretation = direct_role('interpretation', mode)
            require(interpretation['decision'] == 'keep', 'Unexpected fixture decision')
            event('approval', mode=mode, action='select')
            record.update(decision=interpretation['decision'], state='complete', interpretation=interpretation)
            record['memory'] = direct_role('memory', mode)
            save(record_path(mode), record)
            decision = record['decision']
        entry = next(row for row in evidence if row['mode'] == mode)
        entry['decision'] = decision
        selection = {'selected_experiment_id': entry['id']}
        if arm == 'direct':
            save(project / 'direct-project.json', selection)
        save(project / 'evidence' / 'selected.json', selection)
        save(project / 'evidence' / (mode + '-manifest.json'), entry)
        # Both histories retain the essential final record and evidence at equal milestones.
        (project / 'evidence' / (mode + '-record.json')).write_bytes(record_path(mode).read_bytes())
        record_evidence = [item['ref'] for item in record['execution']['evidence']] if arm == 'zar' else list(record['evidence'])
        commit(mode + ' evidence and decision', ['evidence', mode + '.json', 'executions.jsonl', checkpoint[mode + '_record'], *record_evidence, *(['direct-project.json'] if arm == 'direct' else [])])

    try:
        if not resume:
            git('init', '--template=')
            if arm == 'zar':
                cli('init')
            (project / 'evidence').mkdir()
            (project / 'model.py').write_text(BASELINE, encoding='utf-8', newline='\n')
            (project / 'evaluate.py').write_text(EVALUATOR, encoding='utf-8', newline='\n')
            save(project / 'train.json', DATASET(42, 96))
            save(project / 'holdout.json', DATASET(2026, 64))
            checkpoint = dict(port=server.server_port, protected={p: digest(project / p) for p in PROTECTED})
            if arm == 'zar':
                settings = load(project / '.autoresearch/project.json')
                settings.update(name='workflow-utility-fixture', objective='Compare trained mean and linear regression',
                    comparison=dict(id='synthetic-regression-v1', dataset_ref='synthetic-linear-noise-v1', split_ref='train42-eval2026', metric='mse', direction='minimize', evaluation_ref='fixed-mse-v1', min_delta=0),
                    environment=dict(os='other', runtime='python', device='cpu'),
                    commands=[dict(name='validate', argv=[sys.executable, '-B', 'evaluate.py'], cwd='.')],
                    editable_paths=['model.py'], budget=dict(max_experiments=2, max_run_seconds=10))
                save(output / 'project-input.json', settings)
                cli('project', 'set', '--file', str(output / 'project-input.json'))
            else:
                (project / 'direct-records').mkdir()
            seconds['setup'] = time.perf_counter()-phase_start
            for mode in ('baseline', 'candidate'):
                phase = mode
                phase_start = time.perf_counter()
                original = (project / 'model.py').read_bytes()
                expected_changes = [] if mode == 'baseline' else [dict(path='model.py', before_sha256=hashlib.sha256(original).hexdigest(), content=CANDIDATE)]
                if arm == 'zar':
                    session = cli('research', 'start', '--base-url', url, '--model', 'mock-regression', '--api-key-env', 'ZAR_MOCK_API_KEY', '--goal', 'Fit and compare fixed synthetic regression', '--read', 'model.py', '--read', 'evaluate.py', '--command', 'validate', '--metric-file', mode + '.json', '--metric-key', 'mse', '--budget-ref', 'synthetic-regression-ten-seconds', '--seed', '42', '--mode', mode)
                    sid = session['id']
                    session = cli('research', 'advance', sid, '--send')
                    require(session['state'] == 'awaiting_approval', 'Expected execution approval')
                    require(session['outputs']['implementation']['changes'] == expected_changes, 'Unexpected proposal')
                    require((project / 'model.py').read_bytes() == original and not (project / (mode + '.json')).exists(), 'Ran before approval')
                    event('approval', mode=mode, action='execute')
                    cli('research', 'approve', sid, '--token', session['approval_token'])
                    session = cli('research', 'run', sid)
                    require(session['state'] == 'observed', 'Expected observation')
                    checkpoint[mode + '_session_id'] = sid
                    checkpoint[mode + '_record'] = '.autoresearch/experiments/' + session['experiment_id'] + '.json'
                    identifier = session['experiment_id']
                else:
                    outputs = {role: direct_role(role, mode) for role in ROLES[:5]}
                    require(outputs['implementation']['changes'] == expected_changes, 'Unexpected direct proposal')
                    require((project / 'model.py').read_bytes() == original and not (project / (mode + '.json')).exists(), 'Direct ran before approval')
                    identifier = mode
                    checkpoint[mode + '_record'] = 'direct-records/' + mode + '.json'
                    record = dict(id=identifier, baseline_id=None if mode == 'baseline' else 'baseline', state='planned', plan=dict(mode=mode, seed=42, split='train42-eval2026', metric='mse', direction='minimize', command=[sys.executable, '-B', 'evaluate.py']), outputs=outputs, approved=False, decision=None)
                    save(record_path(mode), record)
                    event('approval', mode=mode, action='execute')
                    record.update(approved=True, state='approved')
                    save(record_path(mode), record)
                    if mode == 'candidate':
                        (project / 'model.py').write_text(CANDIDATE, encoding='utf-8', newline='\n')
                    record.update(state='unknown', model_sha256=digest(project / 'model.py'))
                    save(record_path(mode), record)
                    train_env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'SYSTEMROOT', 'SystemRoot', 'TMP', 'TEMP', 'TMPDIR')}
                    run([sys.executable, '-B', 'evaluate.py'], 'training', train_env)
                    record.update(state='observed', score=load(project / (mode + '.json'))['mse'], evidence={mode + '.json': digest(project / (mode + '.json')), **checkpoint['protected']})
                    save(record_path(mode), record)
                require(all(digest(project / p) == h for p, h in checkpoint['protected'].items()), 'Protected fixture changed')
                source_commit = commit(mode + ' measured source snapshot', ['model.py', *PROTECTED])
                (project / 'evidence' / (mode + '-model.py')).write_bytes((project / 'model.py').read_bytes())
                evidence.append(dict(mode=mode, id=identifier, baseline_id=None if mode == 'baseline' else evidence[0]['id'], score=load(project / (mode + '.json'))['mse'], model_sha256=digest(project / 'model.py'), source_commit=source_commit, decision=None))
                if mode == 'baseline':
                    finish(mode)
                seconds[mode] = time.perf_counter()-phase_start
            phase = 'pause'
            phase_start = time.perf_counter()
            checkpoint.update(state='paused_after_observation', execution_sha256=digest(project / 'executions.jsonl'), model_sha256=digest(project / 'model.py'))
            (output / 'paused-executions.jsonl').write_bytes((project / 'executions.jsonl').read_bytes())
            (output / 'paused-baseline-record.json').write_bytes(record_path('baseline').read_bytes())
            seconds['pause'] = time.perf_counter()-phase_start
        else:
            require(checkpoint['state'] == 'paused_after_observation', 'Only observed checkpoint may resume')
            require(digest(project / 'executions.jsonl') == checkpoint['execution_sha256'], 'Changed execution ledger')
            require(digest(project / 'model.py') == checkpoint['model_sha256'], 'Changed source during pause')
            if arm == 'zar':
                require(cli('research', 'status', checkpoint['candidate_session_id'])['state'] == 'observed', 'Expected persisted observation')
            finish('candidate')
            if arm == 'zar':
                cli('experiment', 'compare', evidence[0]['id'], evidence[1]['id'])
                cli('check')
                require(not cli('status')['unfinished'], 'Unfinished zar experiment')
            else:
                require(all(load(record_path(m))['state'] == 'complete' for m in ('baseline', 'candidate')), 'Unfinished direct experiment')
            require(digest(project / 'executions.jsonl') == checkpoint['execution_sha256'], 'Resume reran training')
            checkpoint['state'] = 'complete'
            seconds['resume'] = time.perf_counter()-phase_start
    finally:
        shutdown_started = time.perf_counter()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        require(not thread.is_alive(), 'Mock server did not stop')
        event('server_shutdown', shutdown_started)
    save(output / 'events.json', events)
    save(output / 'checkpoint.json', checkpoint)
    save(output / 'evidence.json', evidence)
    save(output / 'seconds.json', seconds)


def benchmark(output, repeats):
    require(repeats >= 1, 'Repeats must be positive')
    output = output.absolute()
    output.mkdir(parents=False, exist_ok=False)
    trials = []
    for index in range(repeats):
        trial = output / f'trial-{index + 1}'
        trial.mkdir()
        order = ['direct', 'zar'] if index % 2 == 0 else ['zar', 'direct']
        results = {}
        for arm in order:
            destination = trial / arm
            started = time.perf_counter()
            for resume in (False, True):
                argv = [sys.executable, str(Path(__file__).resolve()), '--output', str(destination), '--worker', arm]
                if resume:
                    argv.append('--resume')
                subprocess.run(argv, check=True, timeout=180)
            elapsed = time.perf_counter()-started
            seconds = load(destination / 'seconds.json')
            seconds['total'] = elapsed
            verified = verify_arm(destination, arm)
            events = load(destination / 'events.json')
            counts = dict(provider_requests=sum(e['kind'] == 'provider' for e in events), training=verified['execution_count'],
                          git_commits=sum(e['kind'] == 'git_commit' for e in events), scripted_approvals=sum(e['kind'] == 'approval' for e in events),
                          zar_cli=sum(e['kind'] == 'zar_cli' for e in events), git=sum(e['kind'] == 'git' for e in events))
            result = dict(**verified, seconds=seconds, counts=counts,
                          input_message_bytes=sum(e['input_message_bytes'] for e in events if e['kind'] == 'provider'),
                          output_text_bytes=sum(e['output_text_bytes'] for e in events if e['kind'] == 'provider'))
            save(destination / 'result.json', result)
            results[arm] = result
        for field in ('baseline_score', 'candidate_score', 'improvement', 'execution_count'):
            require(results['direct'][field] == results['zar'][field], f'Arm mismatch: {field}')
        direct_responses = [e['response'] for e in load(trial / 'direct/events.json') if e['kind'] == 'provider']
        zar_responses = [e['response'] for e in load(trial / 'zar/events.json') if e['kind'] == 'provider']
        require(direct_responses == zar_responses, 'Role outputs differ across arms')
        trials.append(dict(repeat=index + 1, order=order, arms=results))
    median = {arm: {key: statistics.median(t['arms'][arm]['seconds'][key] for t in trials) for key in trials[0]['arms'][arm]['seconds']} for arm in ('direct', 'zar')}
    summary = dict(version=1, python=platform.python_version(), platform=platform.system(), repeats=repeats, trials=trials, median=median,
        limitations=['Scripted local fixture, not measured human time or real LLM performance.',
                     'Direct JSON ledger is bespoke benchmark code; engineering/maintenance effort is excluded.',
                     'Identical role outputs, but direct lean prompts and zar managed contexts differ; no token or quality claim.',
                     'Safe observed-boundary resume in a new process; not crash recovery.',
                     'Total includes worker startup, persistence and provider teardown; phase times exclude interprocess gaps and final teardown.',
                     'Independent artifact verification runs after measured total; no timing superiority gate.',
                     'No actual API, paid provider, or model authentication was used.'])
    save(output / 'summary.json', summary)
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--worker', choices=('direct', 'zar'), help=argparse.SUPPRESS)
    parser.add_argument('--resume', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--profile-cli', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--poll-interval', type=float, default=0.01, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        require(args.poll_interval > 0, 'Poll interval must be positive')
        worker(args.output, args.worker, args.resume, profile_cli=args.profile_cli, poll_interval=args.poll_interval)
    else:
        require(not args.resume, '--resume is internal worker-only')
        benchmark(args.output, args.repeats)


if __name__ == '__main__':
    main()
