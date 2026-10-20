#!/usr/bin/env python3
"""Fresh-process mocked research CLI scale benchmark, stopping at approval.

Record and completed-session axes vary independently. Fixture generation, copying,
resume preparation, and verification are outside timing. Wall time includes Python
startup/imports, instrumented load/start wrappers, CLI JSON serialization,
post-CLI persisted-session read and approval-token verification, metadata writing,
stdout/stderr capture and process exit. Parent artifact verification is excluded. Peak RSS is the
child's own high-water mark, including this wrapper; unsupported platforms report
null. One untimed warmup precedes measured repetitions. Warm filesystem caches are
expected. Completed-history documents are synthetic, including seven role outputs
and trace placeholders; they do not represent actual training. Frozen runtime copies exclude bytecode on both comparison sides.

No API, training, execution, decision, or recovery is measured. Resume means a new
process continuing two successfully persisted roles after a controlled mocked
provider interruption on the third attempt. The interruption consumes one call;
resume completes three remaining roles without repeating successful roles. This
is not a process-crash/recovery benchmark. Full execution/recovery is
covered by the functional test suite. No timing threshold determines correctness.
"""
import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import shutil
import statistics
import subprocess
import sys
import threading
import time

_helpers = runpy.run_path(str(Path(__file__).resolve().with_name('benchmark_records.py')))
generate, tree_digest, write_json = (_helpers[name] for name in ('generate', 'tree_digest', 'write_json'))

ROLES = ['analysis', 'evaluation', 'planning', 'implementation', 'review']


def body(role):
    result = dict(summary='Synthetic source inspected', evidence=['train.py'], uncertainties=[])
    result.update(dict(analysis=dict(missing=[]), evaluation=dict(verdict='pass'),
                       planning=dict(hypothesis='Synthetic unchanged candidate'),
                       implementation=dict(changes=[]), review=dict(verdict='pass'),
                       interpretation=dict(decision='hold', reason='Synthetic fixture'),
                       memory=dict(next_action='continue', lesson='Synthetic lesson', limitation='No training'))[role])
    return result


def worker(source, root, mode, metadata):
    sys.path.insert(0, str(source))
    from unittest.mock import patch
    from zar import cli, records, research
    calls = []
    counts = dict(record_loads=0, session_loads=0)
    original_records, original_sessions = records.load_records, research.load
    main_thread = threading.current_thread()
    started_ids = []
    original_start = research.start

    def capture_start(*args, **kwargs):
        result = original_start(*args, **kwargs)
        started_ids.append(result['id'])
        return result

    def counted_records(*args, **kwargs):
        if threading.current_thread() is main_thread:
            counts['record_loads'] += 1
        return original_records(*args, **kwargs)

    def counted_sessions(*args, **kwargs):
        if threading.current_thread() is main_thread:
            counts['session_loads'] += 1
        return original_sessions(*args, **kwargs)

    def respond(profile, messages):
        payload = json.loads(messages[-1]['content'])
        role = payload['role']
        if mode == 'prepare' and role == 'planning':
            raise KeyboardInterrupt('Controlled mock provider interruption')
        calls.append(dict(role=role, prompt_bytes=sum(len(m['content'].encode()) for m in messages),
                          prior_lessons=payload['prior_lessons']))
        return dict(content=json.dumps(body(role)), usage=None)

    prefix = ['--project', str(root), '--json', 'research']
    identifier = None
    code = 0
    with patch.object(records, 'load_records', side_effect=counted_records), \
            patch.object(cli, 'load_records', side_effect=counted_records), \
            patch.object(research, 'load', side_effect=counted_sessions), \
            patch.object(research, 'chat', side_effect=respond), \
            patch.object(research, 'start', side_effect=capture_start):
        if mode in ('plan', 'prepare', 'template'):
            code = cli.main(prefix + ['start', '--base-url', 'http://localhost:9999/v1', '--model', 'mock',
                '--api-key-env', 'ZAR_BENCHMARK_UNUSED', '--goal', 'Inspect synthetic candidate',
                '--read', 'train.py', '--command', 'train', '--metric-file', 'metric.json',
                '--metric-key', 'rmse', '--max-calls', '9',
                '--session-seconds', '86400', '--scope', 'full', '--seed', '42', '--budget-ref', 'synthetic'])
            if code:
                raise RuntimeError('CLI start failed')
            assert len(started_ids) == 1
            identifier = started_ids[0]
        else:
            identifier = (root / 'active-session.txt').read_text().strip()
        if mode != 'template':
            code = cli.main(prefix + (['status', identifier] if mode == 'status' else ['advance', identifier, '--send']))
    if mode in ('plan', 'status', 'resume'):
        saved = json.loads((root / '.autoresearch/sessions' / (identifier + '.json')).read_text())
        assert saved['approval_token'] == research.token(saved)
    rss = None
    if sys.platform == 'darwin' or sys.platform.startswith('linux'):
        import resource
        rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024))
    write_json(metadata, dict(peak_rss_bytes=rss, calls=calls, **counts, session_id=identifier, cli_exit_code=code))
    if mode == 'prepare':
        assert code != 0 and [c['role'] for c in calls] == ROLES[:2]
    elif code:
        raise RuntimeError('CLI operation failed')


def run(source, root, mode, output, timeout):
    metadata = output.with_suffix('.metrics.json')
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1')
    command = [sys.executable, str(Path(__file__).resolve()), '--source', str(source),
               '--worker', mode, '--root', str(root), '--metadata', str(metadata)]
    started = time.perf_counter()
    result = subprocess.run(command, cwd=source, env=env, capture_output=True, timeout=timeout)
    elapsed = time.perf_counter() - started
    output.with_suffix('.stdout').write_bytes(result.stdout)
    output.with_suffix('.stderr').write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError(f'Worker failed; inspect private output {output.name}')
    metrics = json.loads(metadata.read_text())
    metrics.update(wall_seconds=elapsed, stdout_bytes=len(result.stdout), stderr_bytes=len(result.stderr))
    if mode in ('plan', 'status', 'resume'):
        envelopes = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        assert all(item['ok'] for item in envelopes)
        metrics['cli_results'] = envelopes
    return metrics


def records_digest(root):
    return tree_digest(root / '.autoresearch/experiments', '*.json')


def history_digest(root):
    return tree_digest(root / '.autoresearch/sessions', 'session-000000000000000000000000*.json')


def normalize_cli_results(envelopes, identifier):
    """Keep all CLI fields except explicitly nondeterministic session metadata.

    Active IDs are replaced wherever embedded in strings (including suggested
    commands). Only root session timestamps/tokens, trace input hashes (which
    contain the random ID), and measured call durations are normalized. Historical
    timestamps, all byte counts, outputs, budgets, diagnostics and actions remain.
    """
    def replace_id(value):
        if isinstance(value, str):
            return value.replace(identifier, '<active-session>')
        if isinstance(value, list):
            return [replace_id(item) for item in value]
        if isinstance(value, dict):
            return {key: replace_id(item) for key, item in value.items()}
        return value

    normalized = replace_id(envelopes)
    for envelope in normalized:
        session = envelope['data']
        for field in ('created_at', 'deadline', 'approval_token'):
            if field in session and session[field] is not None:
                session[field] = '<' + field + '>'
        for item in session.get('trace', []):
            if 'input_hash' in item:
                item['input_hash'] = '<input_hash>'
            measurement = item.get('measurement', {})
            if measurement.get('call_seconds') is not None:
                measurement['call_seconds'] = '<call_seconds>'
    return normalized


def verify(root, sample, mode, expected_lessons, records_before, history_before):
    session = json.loads((root / '.autoresearch/sessions' / (sample['session_id'] + '.json')).read_text())
    assert session['state'] == 'awaiting_approval'
    cli_results = sample.pop('cli_results')
    cli_result = cli_results[-1]['data']
    for field in ('id', 'state', 'calls', 'outputs', 'approval_token'):
        assert cli_result[field] == session[field], 'CLI result differs from persisted session'
    assert session['calls'] == (6 if mode == 'resume' else 5) and list(session['outputs']) == ROLES
    assert [item['role'] for item in session['trace'] if item['result'] == 'validated'] == ROLES
    if mode == 'resume':
        assert session['outputs']['analysis'] == body('analysis')
        assert session['outputs']['evaluation'] == body('evaluation')
        assert len(session['trace']) == 6
    assert isinstance(session['approval_token'], str) and len(session['approval_token']) == 64
    expected_roles = [] if mode == 'status' else ROLES[2:] if mode == 'resume' else ROLES
    assert [call['role'] for call in sample['calls']] == expected_roles
    for call in sample['calls']:
        assert call['prior_lessons'] == expected_lessons, 'Latest five memory selection/order changed'
    assert records_digest(root) == records_before
    assert history_digest(root) == history_before
    assert not (root / 'metric.json').exists()
    assert (root / 'train.py').read_text() == '# Synthetic source; benchmark never executes this.\n'
    sample['model_calls'] = len(sample['calls'])
    sample['prompt_bytes'] = sum(c['prompt_bytes'] for c in sample['calls'])
    # Raw per-call details and identifiers stay private; summary contains no paths.
    for field in ('calls', 'session_id'):
        del sample[field]
    semantic = {field: session.get(field) for field in ('state', 'calls', 'outputs', 'diff', 'run_context', 'experiment_mode', 'baseline_id', 'experiment_id')}
    semantic.update(expected_roles=expected_roles, expected_lessons=expected_lessons,
                    cli_results=normalize_cli_results(cli_results, session['id']))
    sample['semantic_sha256'] = hashlib.sha256(json.dumps(semantic, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    sample['validated'] = True


def fixture(source, root, records, sessions, private, timeout):
    generate(root, records, source / 'examples/contract-v1')
    store = root / '.autoresearch'
    path = store / 'project.json'
    project = json.loads(path.read_text())
    project['budget']['max_experiments'] = records + 10
    path.write_text(json.dumps(project))
    path = store / 'experiments/exp-000000.json'
    baseline = json.loads(path.read_text())
    baseline['run_context'] = dict(scope='full', seed=42, budget_ref='synthetic')
    path.write_text(json.dumps(baseline))
    (root / 'train.py').write_text('# Synthetic source; benchmark never executes this.\n')
    template_result = run(source, root, 'template', private / (root.name + '-template'), timeout)
    path = store / 'sessions' / (template_result['session_id'] + '.json')
    template = json.loads(path.read_text())
    path.unlink()
    lessons = []
    for index in range(sessions):
        old = copy.deepcopy(template)
        # Deliberately reverse chronological ordering relative to file names.
        identifier = 'session-' + format(index, '032x')
        stamp = (datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(days=sessions-index)).isoformat().replace('+00:00', 'Z')
        old.update(id=identifier, state='complete', created_at=stamp, deadline=0,
                   calls=7, outputs={role: body(role) for role in ROLES + ['interpretation', 'memory']},
                   trace=[dict(role=role, version='2', result='validated', usage=None) for role in ROLES + ['interpretation', 'memory']],
                   experiment_id='exp-000000', approval_token=None)
        write_json(store / 'sessions' / (identifier + '.json'), old)
        lessons.append(dict(session_id=identifier, experiment_id=old['experiment_id'], proposal=old['outputs']['memory'], created_at=stamp))
    return sorted(lessons, key=lambda item: item['created_at'])[-5:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--records', type=int, nargs='+', default=[100, 1000, 10000])
    parser.add_argument('--sessions', type=int, nargs='+', default=[0, 100, 1000])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--label', default='working-tree')
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--worker', choices=['template', 'prepare', 'plan', 'status', 'resume'], help=argparse.SUPPRESS)
    parser.add_argument('--root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--metadata', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.source.resolve(), args.root, args.worker, args.metadata)
        return
    if not args.output or args.output.exists():
        parser.error('--output must be a new directory')
    if args.repeats < 1 or any(n < 1 for n in args.records) or any(n < 0 for n in args.sessions):
        parser.error('Positive records/repeats and nonnegative sessions required')
    if len(set(args.records)) != len(args.records) or len(set(args.sessions)) != len(args.sessions):
        parser.error('Scale lists must contain unique values')
    original = args.source.resolve()
    original_digest = tree_digest(original / 'zar', '*.py')
    measurement_paths = [Path(__file__).resolve(), Path(__file__).resolve().with_name('benchmark_records.py')]
    measurement_digest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in measurement_paths}
    output = args.output.resolve()
    output.mkdir()
    private = output / 'private'
    private.mkdir(mode=0o700)
    source = private / 'source'
    source.mkdir()
    for directory in ('zar', 'examples', 'skills'):
        if (original / directory).exists():
            shutil.copytree(original / directory, source / directory, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    shutil.copy2(original / 'pyproject.toml', source / 'pyproject.toml')
    report = dict(measurement_version=1, label=args.label, methodology=__doc__,
                  python=platform.python_version(), platform=platform.system() + '-' + platform.machine(),
                  source_digest=original_digest, measurement_digest=measurement_digest, warmups=1, repeats=args.repeats, cases=[])
    previous = json.loads(args.compare.read_text()) if args.compare else None
    if previous:
        assert previous['measurement_digest'] == measurement_digest, 'Measurement code changed'
        assert previous['python'] == report['python'] and previous['platform'] == report['platform'], 'Comparison host/interpreter differs'
    for axis, count, session_count in [('records', n, 0) for n in args.records] + [('sessions', 100, n) for n in args.sessions]:
        key = f'{axis}-{count}-{session_count}'
        seed = private / (key + '-fixture')
        lessons = fixture(source, seed, count, session_count, private, args.timeout)
        seed_digest = tree_digest(seed, '*')
        before_records, before_history = records_digest(seed), history_digest(seed)
        if previous:
            prior = next(c for c in previous['cases'] if c['key'] == key)
            assert prior['fixture_digest'] == seed_digest, 'Comparison fixture differs'
        case = dict(key=key, axis=axis, records=count, completed_sessions=session_count, fixture_digest=seed_digest, operations={})
        for mode in ('plan', 'status', 'resume'):
            samples = []
            for repeat in range(args.repeats + 1):
                name = f'{key}-{mode}-{repeat}'
                root = private / name
                shutil.copytree(seed, root)
                if mode in ('status', 'resume'):
                    prepared = run(source, root, 'plan' if mode == 'status' else 'prepare', private / (name + '-prepare'), args.timeout)
                    identifier = prepared['session_id']
                    (root / 'active-session.txt').write_text(identifier)
                    if mode == 'resume':
                        path = root / '.autoresearch/sessions' / (identifier + '.json')
                        session = json.loads(path.read_text())
                        assert session['state'] == 'planning' and session['calls'] == 3
                        assert list(session['outputs']) == ROLES[:2]
                        assert session['max_calls'] == 9 and session['error']
                sample = run(source, root, mode, private / (name + '-measured'), args.timeout)
                verify(root, sample, mode, lessons, before_records, before_history)
                if repeat:
                    samples.append(sample)
            assert len({s['semantic_sha256'] for s in samples}) == 1, 'Nondeterministic semantic result'
            if previous:
                assert samples[0]['semantic_sha256'] == prior['operations'][mode]['trials'][0]['semantic_sha256'], 'Comparison semantics changed'
            summary = dict(trials=samples)
            for field in ('wall_seconds', 'peak_rss_bytes', 'stdout_bytes', 'record_loads', 'session_loads', 'model_calls', 'prompt_bytes'):
                values = [s[field] for s in samples]
                summary['median_' + field] = statistics.median(values) if all(v is not None for v in values) else None
            case['operations'][mode] = summary
            print(f'{key} {mode}: {summary["median_wall_seconds"]:.4f}s', flush=True)
        assert tree_digest(seed, '*') == seed_digest
        report['cases'].append(case)
        write_json(output / (key + '.json'), case)
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in measurement_paths} == measurement_digest, 'Measurement code changed during benchmark'
    assert tree_digest(original / 'zar', '*.py') == original_digest, 'Source changed during benchmark'
    assert tree_digest(source / 'zar', '*.py') == original_digest
    write_json(output / 'summary.json', report)


if __name__ == '__main__':
    main()
