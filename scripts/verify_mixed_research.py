#!/usr/bin/env python3
"""Functional mixed-scale CLI verification with synthetic records and large history.

No timing claim, actual provider, training or OS-crash recovery is involved.
Each scenario starts in a new process; interrupted resume uses another process.
Expected recent memories come from six deliberately tied history identifiers,
not the product selector. Mutations are intentional and isolated per fixture.
Only numeric counts, flags, source/measurement hashes and aggregate dimensions
are public. Fixture contents and CLI output remain under private/.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve()
BOUNDARY = runpy.run_path(str(HERE.with_name('benchmark_session_boundaries.py')))
BASE = BOUNDARY['BASE']
SCENARIOS = ('record-edit', 'record-add', 'record-delete', 'record-correction',
             'between-roles', 'history-changes', 'resume', 'approval', 'stale-approval')


def expected(candidates):
    # Independent explicit timestamp + filename ordering, including ties.
    return sorted(candidates, key=lambda x: (x['created_at'], x['session_id']))[-5:]


def tied_history(root):
    candidates = []
    for index in range(6):
        path = root / '.autoresearch/sessions' / f'session-{index:032x}.json'
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc['created_at'] = '2099-01-01T00:00:00Z'
        path.write_bytes(BOUNDARY['compact'](doc))
        candidates.append(dict(session_id=doc['id'], experiment_id=doc['experiment_id'],
                               proposal=doc['outputs']['memory'], created_at=doc['created_at']))
    return candidates


def edit_record(root, kind):
    path = root / '.autoresearch/experiments/exp-000000.json'
    raw = path.read_bytes()
    doc = json.loads(raw)
    if kind == 'record-delete':
        path.unlink()
    elif kind in ('record-edit', 'between-roles'):
        stat = path.stat()
        old = doc['code_ref']
        new = old[:-1] + ('2' if old[-1] != '2' else '3')
        changed = raw.replace(json.dumps(old).encode(), json.dumps(new).encode(), 1)
        assert changed != raw and len(changed) == len(raw)
        path.write_bytes(changed)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert path.stat().st_size == stat.st_size and path.stat().st_mtime_ns == stat.st_mtime_ns
    else:
        assert kind in ('record-add', 'record-correction')
        doc['id'] = 'mixed-added'
        if kind == 'record-correction':
            doc['correction'] = dict(supersedes_id='exp-000000', reason='Synthetic correction',
                evidence=[dict(kind='user_report', ref='synthetic', locator=None, sha256=None)])
        (path.parent / 'mixed-added.json').write_bytes(BOUNDARY['compact'](doc))


def edit_memory(root, candidates):
    item = candidates[5]
    path = root / '.autoresearch/sessions' / (item['session_id'] + '.json')
    stat = path.stat()
    raw = path.read_bytes()
    old = item['proposal']['lesson']
    new = 'n' + old[1:]
    changed = raw.replace(json.dumps(old).encode(), json.dumps(new).encode(), 1)
    assert changed != raw and len(changed) == len(raw)
    path.write_bytes(changed)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size and path.stat().st_mtime_ns == stat.st_mtime_ns
    item['proposal']['lesson'] = new


def worker(source, root, scenario, metadata):
    sys.path.insert(0, str(source))
    from unittest.mock import patch
    from zar import cli, research
    candidates = json.loads((root / 'expected-memories.json').read_text(encoding='utf-8'))
    identifier = (root / 'active-session.txt').read_text(encoding='utf-8').strip()
    prefix = ['--project', str(root), '--json', 'research']
    initial = research.load(root, identifier)
    record_hash = BASE['records_digest'](root)
    history_hash = BASE['history_digest'](root)
    calls = []
    memory_mutations = 0
    original_save = research.save

    def answer(profile, messages):
        nonlocal memory_mutations
        payload = json.loads(messages[-1]['content'])
        assert payload['prior_lessons'] == expected(candidates), 'Recent/tied memory evidence changed'
        role = payload['role']
        if scenario == 'interrupt' and role == 'planning':
            raise KeyboardInterrupt('Controlled mixed-fixture interruption')
        calls.append(role)
        response = dict(content=json.dumps(BASE['body'](role)), usage=None)
        if scenario.startswith('record-') and len(calls) == 2:
            edit_record(root, scenario)
        if scenario == 'history-changes':
            if len(calls) == 1:
                edit_memory(root, candidates)
                memory_mutations += 1
            elif len(calls) == 2:
                path = root / '.autoresearch/sessions' / (candidates[5]['session_id'] + '.json')
                doc = json.loads(path.read_text(encoding='utf-8'))
                doc['id'] = 'session-' + format(100000, '032x')
                doc['outputs']['memory']['lesson'] = 'a' * len(doc['outputs']['memory']['lesson'])
                (path.parent / (doc['id'] + '.json')).write_bytes(BOUNDARY['compact'](doc))
                candidates.append(dict(session_id=doc['id'], experiment_id=doc['experiment_id'],
                    proposal=doc['outputs']['memory'], created_at=doc['created_at']))
                memory_mutations += 1
            elif len(calls) == 3:
                item = candidates.pop()
                (root / '.autoresearch/sessions' / (item['session_id'] + '.json')).unlink()
                memory_mutations += 1
        return response

    def save(project, session):
        original_save(project, session)
        if scenario == 'between-roles' and session['state'] == 'planning' and list(session['outputs']) == ['analysis']:
            edit_record(root, scenario)

    with patch.object(research, 'chat', side_effect=answer), patch.object(research, 'save', new=save):
        code = cli.main(prefix + ['advance', identifier, '--send'])
    saved = research.load(root, identifier)
    if scenario.startswith('record-'):
        assert code != 0 and calls == BASE['ROLES'][:2]
        assert saved['state'] == 'blocked' and saved['error'] == 'inputs_changed'
        assert saved['calls'] == 2 and list(saved['outputs']) == ['analysis']
        assert saved['outputs']['analysis'] == BASE['body']('analysis')
        assert [t['result'] for t in saved['trace']] == ['validated', 'inputs_changed']
    elif scenario == 'between-roles':
        assert code != 0 and calls == ['analysis']
        assert saved['calls'] == 1 and saved['state'] == 'planning'
        assert list(saved['outputs']) == ['analysis']
    elif scenario == 'interrupt':
        assert code != 0 and calls == BASE['ROLES'][:2]
        assert saved['state'] == 'planning' and saved['calls'] == 3 and saved['error']
        assert list(saved['outputs']) == BASE['ROLES'][:2]
        assert [t['result'] for t in saved['trace'][:2]] == ['validated', 'validated']
    else:
        assert code == 0 and saved['state'] == 'awaiting_approval'
        assert saved['approval_token'] == research.token(saved)
        assert saved['calls'] == (6 if scenario == 'resume' else 5)
        assert calls == (BASE['ROLES'][2:] if scenario == 'resume' else BASE['ROLES'])
        assert list(saved['outputs']) == BASE['ROLES']
        if scenario == 'resume':
            for role in BASE['ROLES'][:2]:
                assert saved['outputs'][role] == initial['outputs'][role] == BASE['body'](role)
        before_approval = copy.deepcopy(saved)
        assert cli.main(prefix + ['run', identifier]) != 0
        assert cli.main(prefix + ['approve', identifier, '--token', '0' * 64]) != 0
        assert research.load(root, identifier) == before_approval
        if scenario == 'approval':
            assert cli.main(prefix + ['approve', identifier, '--token', saved['approval_token']]) == 0
            assert research.load(root, identifier)['state'] == 'approved'
        elif scenario == 'stale-approval':
            edit_record(root, 'record-edit')
            assert cli.main(prefix + ['approve', identifier, '--token', saved['approval_token']]) != 0
            assert research.load(root, identifier) == before_approval
    record_changed = scenario.startswith('record-') or scenario in ('between-roles', 'stale-approval')
    assert (BASE['records_digest'](root) != record_hash) == record_changed
    assert (BASE['history_digest'](root) != history_hash) == (scenario == 'history-changes')
    assert not (root / 'metric.json').exists()
    assert (root / 'train.py').read_text(encoding='utf-8') == '# Synthetic source; benchmark never executes this.\n'
    BASE['write_json'](metadata, dict(validated=True, model_calls=len(calls), stored_call_attempts=saved['calls'],
        preserved_successful_roles=len(saved['outputs']), memory_mutations=memory_mutations,
        expected_failure=scenario.startswith('record-') or scenario in ('between-roles', 'interrupt'),
        execution_absent=True, approval_checked=scenario in ('approval', 'history-changes', 'resume', 'stale-approval'),
        stale_approval_refused=scenario == 'stale-approval'))


def run_worker(source, root, scenario, output, timeout):
    metadata = output.with_suffix('.json')
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, str(HERE), '--source', str(source), '--worker', scenario,
        '--root', str(root), '--metadata', str(metadata)], cwd=source, env=env,
        capture_output=True, timeout=timeout)
    output.with_suffix('.stdout').write_bytes(result.stdout)
    output.with_suffix('.stderr').write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError('Mixed verification failed; inspect private output ' + output.name)
    report = json.loads(metadata.read_text(encoding='utf-8'))
    report['stderr_bytes'] = len(result.stderr)
    assert report['stderr_bytes'] == 0
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE.parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--records', type=int, default=10000)
    parser.add_argument('--sessions', type=int, default=2500)
    parser.add_argument('--memory-characters', type=int, default=16000)
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--worker', choices=SCENARIOS + ('interrupt',), help=argparse.SUPPRESS)
    parser.add_argument('--root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--metadata', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.source.resolve(), args.root, args.worker, args.metadata)
        return
    if not args.output or args.output.exists() or args.records < 1 or args.sessions < 6 or not 2 <= args.memory_characters <= 20000:
        parser.error('New output, positive records, at least six sessions and 2..20000 memory characters required')
    original = args.source.resolve()
    source_hash = BASE['tree_digest'](original / 'zar', '*.py')
    measured_paths = [HERE, HERE.with_name('benchmark_session_boundaries.py'),
                      HERE.with_name('benchmark_research_scale.py'), HERE.with_name('benchmark_records.py')]
    def measurement_hash():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in measured_paths}
    measured_hash = measurement_hash()
    output = args.output.resolve(); output.mkdir()
    private = output / 'private'; private.mkdir(mode=0o700)
    source = private / 'source'; source.mkdir()
    for name in ('zar', 'examples', 'skills'):
        shutil.copytree(original / name, source / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    shutil.copy2(original / 'pyproject.toml', source / 'pyproject.toml')
    seed = private / 'fixture'
    BASE['fixture'](source, seed, args.records, args.sessions, private, args.timeout)
    dimensions = BOUNDARY['resize_history'](seed, memory_characters=args.memory_characters)
    candidates = tied_history(seed)
    BOUNDARY['validate_history'](source, seed, args.timeout)
    BASE['write_json'](seed / 'expected-memories.json', candidates)
    seed_hash = BASE['tree_digest'](seed, '*')
    results = {}
    for scenario in SCENARIOS:
        root = private / scenario; shutil.copytree(seed, root)
        prepared = BASE['run'](source, root, 'template', private / (scenario + '-start'), args.timeout)
        (root / 'active-session.txt').write_text(prepared['session_id'], encoding='utf-8')
        if scenario == 'resume':
            interruption = run_worker(source, root, 'interrupt', private / 'resume-interruption', args.timeout)
            updated = copy.deepcopy(candidates)
            edit_memory(root, updated)
            (root / 'expected-memories.json').write_text(json.dumps(updated), encoding='utf-8')
            result = run_worker(source, root, scenario, private / (scenario + '-result'), args.timeout)
            result['interruption'] = interruption
            result['new_process_memory_update_verified'] = True
        else:
            result = run_worker(source, root, scenario, private / (scenario + '-result'), args.timeout)
        results[scenario] = result
        shutil.rmtree(root)
        print(scenario + ': verified', flush=True)
    assert BASE['tree_digest'](seed, '*') == seed_hash
    assert BASE['tree_digest'](source / 'zar', '*.py') == source_hash == BASE['tree_digest'](original / 'zar', '*.py')
    assert measurement_hash() == measured_hash
    report = dict(version=1, methodology=__doc__, python=platform.python_version(),
        platform=platform.system() + '-' + platform.machine(), records=args.records,
        dimensions=dimensions, memory_characters=args.memory_characters, source_digest=source_hash,
        measurement_digest=measured_hash, fixture_digest=seed_hash, scenarios=results)
    BASE['write_json'](output / 'summary.json', report)


if __name__ == '__main__':
    main()
