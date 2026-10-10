#!/usr/bin/env python3
"""Documentation-led public CLI check. Run with released venv Python -I.
No implementation imports except the documented exact-decimal JSON codec.
Each CLI call is a fresh process; resume is a separate harness invocation.
"""
import argparse
import hashlib
import pathlib
import subprocess
import sys
from decimal import Decimal

from zar.codec import dumps, loads

PYTHON = pathlib.Path(sys.executable)
TRANSCRIPT = None


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    return loads(p.read_text(encoding='utf-8'))


def write(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(dumps(v) + '\n', encoding='utf-8')


def canonical(p):
    records = p / '.autoresearch'
    return {
        str(f.relative_to(p)): sha(f)
        for f in records.rglob('*.json')
        if f.relative_to(records).parts[0] != 'drafts'
    }


def cli(p, *args, expected=0, preserve=False):
    before = canonical(p) if preserve else None
    cmd = [str(PYTHON), '-I', '-m', 'zar', *args, '--project', str(p), '--json']
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        cwd=p.parent,
        timeout=30
    )
    event = {'command': cmd, 'exit': cp.returncode, 'stdout': cp.stdout, 'stderr': cp.stderr}
    with TRANSCRIPT.open('a', encoding='utf-8') as f:
        f.write(dumps(event).rstrip('\n') + '\n')
    print(' '.join(args), 'exit', cp.returncode, flush=True)
    assert cp.returncode == expected, event
    if preserve:
        assert canonical(p) == before, 'Read/rejected command mutated canonical records'
    return loads(cp.stdout)


def draft(p, name, obj):
    f = p / '.autoresearch/drafts' / name
    write(f, obj)
    return str(f)


def project(p, **changes):
    d = read(p / '.autoresearch/project.json')
    d.update(changes)
    return cli(p, 'project', 'set', '--file', draft(p, 'project.json', d))


def exp(p, id):
    return read(p / '.autoresearch/experiments' / f'{id}.json')


def update(p, id, **changes):
    d = exp(p, id)
    d['execution'].update(changes)
    return cli(p, 'experiment', 'update', id, '--file', draft(p, id + '-update.json', d))


def evidence(p, name, text):
    f = p / 'logs' / name
    f.parent.mkdir(exist_ok=True)
    f.write_text(text, encoding='utf-8')
    return {
        'kind': 'fixture',
        'ref': 'logs/' + name,
        'locator': 'all lines, synthetic observation',
        'sha256': sha(f)
    }


def plan(p, id, scope, baseline=None):
    return {
        'id': id,
        'kind': 'performance' if baseline else 'baseline',
        'hypothesis': 'Clip outlier demand counts to reduce synthetic MAE' if baseline else 'Establish synthetic demand reference',
        'parent_id': baseline,
        'baseline_id': baseline,
        'code_ref': 'manual-synthetic-clip-v2' if baseline else 'manual-synthetic-raw-v1',
        'config_ref': 'synthetic-demand-config-v1',
        'command': {'name': 'train', 'argv': ['python', 'train.py'], 'cwd': '.'},
        'review_ids': [],
        'run_context': {'scope': scope, 'seed': 23, 'budget_ref': 'synthetic-60-seconds'}
    }


def decide(p, id, status, validity, ev, reason):
    d = {
        'revision': exp(p, id)['revision'],
        'decision': {
            'status': status,
            'validity': validity,
            'reason': reason,
            'evidence': ev,
            'next_action': 'Stop at two-record budget; obtain separately authorized valid full evidence before adoption'
        }
    }
    return cli(p, 'experiment', 'decide', id, '--file', draft(p, id + '-decision.json', d))


def prepare(p, scope):
    # Reject all output collisions before creating the project or sidecars.
    outputs = [p] + [p.parent / (p.name + suffix) for suffix in (
        '-checkpoint.json',
        '-result.json',
        '-transcript.jsonl'
    )]
    for output in outputs:
        if output.exists() or output.is_symlink():
            raise FileExistsError(f'Refusing existing output: {output}')
    p.mkdir(parents=True)
    (p / 'train.py').write_text(
        "from pathlib import Path\nPath(__file__).with_name('TRAINING_WAS_INVOKED').write_text('unexpected execution', encoding='utf-8')\nraise RuntimeError('SYNTHETIC TEST: training must never execute')\n",
        encoding='utf-8'
    )
    (p / 'program.md').write_text('Existing user notes: preserve this file.\n', encoding='utf-8')
    original = {f.name: sha(f) for f in [p / 'train.py', p / 'program.md']}
    cli(p, '--help')
    cli(p, 'init')
    cli(p, 'status')
    project(
        p,
        objective='Synthetic demand forecasting onboarding; no training authorized',
        comparison={
            'id': 'demand-protocol-v1',
            'dataset_ref': 'synthetic-demand-v1',
            'split_ref': 'last-two-days-v1',
            'metric': 'mae',
            'direction': 'minimize',
            'evaluation_ref': 'absolute-error-v1',
            'min_delta': Decimal('0.1')
        },
        environment={
            'os': 'other',
            'runtime': 'Python 3.11+ mock observations only',
            'device': 'cpu not executed'
        },
        commands=[{'name': 'train', 'argv': ['python', 'train.py'], 'cwd': '.'}],
        budget={'max_experiments': 2, 'max_run_seconds': 60},
        editable_paths=['train.py'],
        next_action='Register synthetic baseline; never execute train.py'
    )
    cli(p, 'check')
    cli(
        p,
        'experiment',
        'create',
        '--file',
        draft(p, 'baseline-plan.json', plan(p, 'demand-base', 'full'))
    )
    ev = evidence(p, 'baseline.log', 'SYNTHETIC, not actual ML. scope=full; MAE=2.7; exit=0\n')
    update(
        p,
        'demand-base',
        status='succeeded',
        started_at='2026-10-10T00:00:00Z',
        finished_at='2026-10-10T00:00:20Z',
        exit_code=0,
        score=Decimal('2.7'),
        evidence=[ev],
        note='Synthetic supplied observation, no command executed; 20 modeled seconds'
    )
    cli(
        p,
        'evidence',
        'read',
        '--kind',
        'experiment',
        '--id',
        'demand-base',
        '--pointer',
        '/execution/evidence/0',
        preserve=True
    )
    decide(
        p,
        'demand-base',
        'keep',
        'valid',
        [ev],
        'Reference accepted only within this synthetic exercise, not validated ML'
    )
    project(
        p,
        selected_experiment_id='demand-base',
        next_action='Plan one bounded synthetic candidate'
    )
    baseline_bytes = (p / '.autoresearch/experiments/demand-base.json').read_text(encoding='utf-8')
    cli(
        p,
        'experiment',
        'create',
        '--file',
        draft(p, 'candidate-plan.json', plan(p, 'demand-clip', scope, 'demand-base'))
    )
    started = evidence(
        p,
        'started.log',
        'SYNTHETIC launch receipt: demand-clip started 00:01:00Z\n'
    )
    update(
        p,
        'demand-clip',
        status='running',
        started_at='2026-10-10T00:01:00Z',
        evidence=[started],
        note='Synthetic running receipt, no real process'
    )
    lost = evidence(
        p,
        'disconnected.log',
        'SYNTHETIC supervisor lost connection; outcome not yet observed\n'
    )
    update(
        p,
        'demand-clip',
        status='unknown',
        evidence=[started, lost],
        note='Synthetic interruption; do not create duplicate run'
    )
    state = {
        'original': original,
        'baseline_bytes': baseline_bytes,
        'scope': scope,
        'candidate_revision': exp(p, 'demand-clip')['revision']
    }
    write(p.parent / (p.name + '-checkpoint.json'), state)
    cli(p, 'status', preserve=True)
    cli(p, 'context', '--experiment', 'demand-clip', preserve=True)
    print('EXIT PHASE: all in-memory experiment/project objects discarded', flush=True)


def resume(p):
    assert canonical(p), 'Canonical preservation check must cover stored records'
    checkpoint = read(p.parent / (p.name + '-checkpoint.json'))
    cli(p, 'context', '--experiment', 'demand-clip', preserve=True)
    status = cli(p, 'status', preserve=True)
    assert {'id': 'demand-clip', 'status': 'unknown'} in status['data']['unfinished']
    assert exp(p, 'demand-clip')['execution']['status'] == 'unknown'
    assert len(list((p / '.autoresearch/experiments').glob('*.json'))) == 2
    old = exp(p, 'demand-clip')
    prefix = old['execution']['evidence']
    bad = read(p / '.autoresearch/experiments/demand-clip.json')
    bad['execution'].update(
        status='succeeded',
        finished_at='2026-10-10T00:01:30Z',
        exit_code=0,
        score=Decimal('2.5'),
        note='Synthetic completion without new evidence must be rejected'
    )
    cli(
        p,
        'experiment',
        'update',
        'demand-clip',
        '--file',
        draft(p, 'bad-resolve.json', bad),
        expected=3,
        preserve=True
    )
    done = evidence(
        p,
        'completion.log',
        'SYNTHETIC new supervisor record: demand-clip finished; exit=0; MAE=2.5\n'
    )
    update(
        p,
        'demand-clip',
        status='succeeded',
        finished_at='2026-10-10T00:01:30Z',
        exit_code=0,
        score=Decimal('2.5'),
        evidence=prefix + [done],
        note='Resolved same synthetic execution with new receipt; 30 modeled seconds, no actual training'
    )
    assert exp(p, 'demand-clip')['execution']['evidence'][:len(prefix)] == prefix
    comparison = cli(p, 'experiment', 'compare', 'demand-base', 'demand-clip', preserve=True)
    if checkpoint['scope'] == 'full':
        assert comparison['data']['comparable'] is True
        assert comparison['data']['improvement'] == Decimal('0.2')
        assert comparison['data']['meets_min_delta'] is True
    else:
        assert comparison['data']['comparable'] is False
        assert comparison['data']['improvement'] is None
        assert 'scope_mismatch' in comparison['data']['reasons']
    cli(
        p,
        'evidence',
        'read',
        '--kind',
        'experiment',
        '--id',
        'demand-clip',
        '--pointer',
        '/execution/evidence/2',
        preserve=True
    )
    log = p / 'logs/completion.log'
    original = log.read_bytes()
    log.write_text('TAMPERED synthetic log: MAE=0.01\n', encoding='utf-8')
    mismatch = cli(
        p,
        'evidence',
        'read',
        '--kind',
        'experiment',
        '--id',
        'demand-clip',
        '--pointer',
        '/execution/evidence/2',
        expected=3,
        preserve=True
    )
    assert mismatch['data'] is None
    assert any((d['code'] == 'evidence_changed' for d in mismatch['diagnostics']))
    changed_compare = cli(p, 'experiment', 'compare', 'demand-base', 'demand-clip', preserve=True)
    assert any((d['code'] == 'evidence_changed' for d in changed_compare['diagnostics']))
    changed_check = cli(p, 'check', preserve=True)
    assert any((d['code'] == 'evidence_changed' and d['severity'] == 'warning' for d in changed_check['diagnostics']))
    decide(
        p,
        'demand-clip',
        'hold',
        'not_comparable',
        [],
        'Cannot adopt: current completion evidence hash differs' + ('; proxy and full scopes also differ' if checkpoint['scope'] == 'proxy' else ' despite numeric metadata improvement')
    )
    assert exp(p, 'demand-clip')['decision']['status'] == 'hold'
    assert read(p / '.autoresearch/project.json')['selected_experiment_id'] == 'demand-base'
    # Restore exact fixture bytes after holding; the CLI does not restore evidence.
    log.write_bytes(original)
    project(
        p,
        next_action='STOP: two-record budget exhausted. Candidate held; inspect authorized comparable evidence before any further run.'
    )
    cli(
        p,
        'experiment',
        'create',
        '--file',
        draft(p, 'over-budget.json', plan(p, 'demand-third', 'full', 'demand-base')),
        expected=3,
        preserve=True
    )
    before = canonical(p)
    cli(p, 'report', '--output', 'summary.md', preserve=True)
    cli(p, 'check', preserve=True)
    final_status = cli(p, 'status', preserve=True)
    assert final_status['data']['budget_used'] == 2
    assert final_status['data']['unfinished'] == []
    assert final_status['data']['selected_experiment_id'] == 'demand-base'
    cli(p, 'context', '--experiment', 'demand-clip', preserve=True)
    assert canonical(p) == before
    assert (p / '.autoresearch/experiments/demand-base.json').read_text(encoding='utf-8') == checkpoint['baseline_bytes']
    assert len(list((p / '.autoresearch/experiments').glob('*.json'))) == 2
    assert all((sha(p / name) == value for name, value in checkpoint['original'].items()))
    assert not (p / 'TRAINING_WAS_INVOKED').exists()
    write(
        p.parent / (p.name + '-result.json'),
        {
            'comparison': comparison,
            'changed_evidence_comparison': changed_compare,
            'mismatch': mismatch,
            'final_status': final_status,
            'baseline_preserved': True,
            'read_and_report_canonical_preserved': True,
            'unknown_same_id_resolved': True,
            'evidence_prefix_preserved': True,
            'training_invoked': (p / 'TRAINING_WAS_INVOKED').exists(),
            'workspace_files_preserved': True,
            'synthetic_total_seconds': 50,
            'actual_training_seconds': 0
        }
    )
if __name__ == '__main__':
    a = argparse.ArgumentParser()
    a.add_argument('phase', choices=['prepare', 'resume'])
    a.add_argument('--root', type=pathlib.Path, required=True)
    a.add_argument('--scope', choices=['full', 'proxy'], default='full')
    a.add_argument('--python', type=pathlib.Path, default=PYTHON)
    args = a.parse_args()
    # Preserve virtualenv symlinks: resolving them selects the base interpreter.
    PYTHON = args.python.absolute()
    args.root = args.root.resolve()
    TRANSCRIPT = args.root.parent / (args.root.name + '-transcript.jsonl')
    if args.phase == 'prepare':
        prepare(args.root, args.scope)
    else:
        resume(args.root)
