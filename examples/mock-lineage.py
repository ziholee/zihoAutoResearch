#!/usr/bin/env python3
"""Synthetic experiment branches over real linear Git history; Git is required.

Only a newly created --output directory is used. Creates three local commits,
records supplied observations, and never runs training or accesses a remote.
"""
import argparse
from copy import deepcopy
from decimal import Decimal
import os
from pathlib import Path
import runpy
import shutil
import subprocess

from zar.codec import dumps


def demonstrate(output):
    if shutil.which('git') is None:
        raise RuntimeError('This example requires Git on PATH.')
    MockCycle = runpy.run_path(str(Path(__file__).with_name('mock-cycle.py')))['MockCycle']
    cycle = MockCycle(output, 'experiment-lineage')
    cycle.configure()
    project = cycle.read('project.json')
    project['budget']['max_experiments'] = 3
    cycle.cli('project', 'set', '--file', cycle.draft('lineage-budget.json', project))
    empty = output / 'empty-git-config'
    empty.mkdir()
    env = {key:value for key,value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        result = subprocess.run(['git', '-c', 'core.hooksPath=' + str(empty),
                                 '-c', 'commit.gpgsign=false', '-c', 'core.fsmonitor=false',
                                 '-C', str(cycle.project), *args], env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        if result.returncode:
            raise RuntimeError(f'Local Git command failed: {args!r}: {result.stderr}')
        return result.stdout.strip()

    git('init', '--template=' + str(empty), '--initial-branch=main')
    git('config', '--local', 'user.name', 'Synthetic lineage example')
    git('config', '--local', 'user.email', 'synthetic@example.invalid')
    git('config', '--local', 'core.hooksPath', str(empty))
    git('config', '--local', 'commit.gpgsign', 'false')
    commits = {}
    evidence = dict(kind='user_report', ref='SIMULATED observations; no training executed',
                    locator=None, sha256=None)
    for identifier, status in [('a','succeeded'), ('b','failed'), ('c','cancelled')]:
        (cycle.project / 'train.py').write_text(
            f'# Synthetic code version {identifier}\n'
            'from pathlib import Path\n'
            'Path("TRAINING_WAS_EXECUTED").write_text("unexpected execution")\n'
            'raise RuntimeError("This sentinel must never execute")\n', encoding='utf-8')
        git('add', '--', 'train.py')
        git('commit', '-m', 'Synthetic code version ' + identifier)
        commits[identifier] = git('rev-parse', 'HEAD')
        parent = None if identifier == 'a' else 'a'
        plan = dict(id=identifier, kind='baseline' if parent is None else 'performance',
                    hypothesis='Synthetic lineage demonstration ' + identifier,
                    parent_id=parent, baseline_id=parent, code_ref='replaced-by-git-head',
                    config_ref='synthetic-config-v1', command=project['commands'][0], review_ids=[],
                    run_context=dict(scope='full', seed=42, budget_ref='mock-60-seconds-v1'))
        cycle.cli('experiment', 'create', '--file', cycle.draft(identifier + '-plan.json', plan), '--git-head')
        record = cycle.read(f'experiments/{identifier}.json')
        if record['code_ref'] != 'git:' + commits[identifier]:
            raise RuntimeError('Experiment did not retain its recorded Git HEAD')
        record['execution'].update(status=status, note='SIMULATED only; no execution occurred.')
        if status != 'cancelled':
            record['execution'].update(started_at='2026-01-01T00:00:00Z',
                finished_at='2026-01-01T00:01:00Z', exit_code=0 if status == 'succeeded' else 1,
                score=Decimal('1.2') if status == 'succeeded' else None, evidence=[evidence])
        cycle.cli('experiment', 'update', identifier, '--file', cycle.draft(identifier + '-result.json', record))
    # Correct an observation without rewriting either child reference or code.
    original = cycle.read('experiments/a.json')
    corrected = deepcopy(original['execution'])
    corrected['score'] = Decimal('1.1')
    correction = dict(id='a-corrected', revision=original['revision'], execution=corrected,
                      reason='Correct supplied synthetic score; same execution identity', evidence=[evidence])
    cycle.cli('experiment', 'correct', 'a', '--file', cycle.draft('correction.json', correction))
    cycle.decide('a-corrected', 'keep', 'valid', 'Accept corrected synthetic reference only', evidence)
    cycle.select('a-corrected', 'Read recorded ancestry without changing code or original references')
    before = {path:path.read_bytes() for path in cycle.store.rglob('*.json')}
    head = git('rev-parse', 'HEAD')
    history = git('rev-list', '--reverse', 'HEAD').splitlines()
    if history != [commits[key] for key in ('a','b','c')]:
        raise RuntimeError('Expected three linear Git commits')
    value = cycle.cli('lineage')
    mermaid = cycle.cli('lineage', '--format', 'mermaid')['mermaid']
    (output / 'lineage.json').write_text(dumps(value), encoding='utf-8')
    (output / 'lineage.mmd').write_text(mermaid, encoding='utf-8')
    parents = {(edge['source'],edge['target']) for edge in value['edges'] if edge['type']=='parent'}
    stale = [edge for edge in value['edges'] if edge['type'] in ('parent','baseline') and edge['source_superseded']]
    nodes = {node['id']:node for node in value['nodes']}
    if (any(nodes[key]['code_ref'] != 'git:' + commit for key,commit in commits.items())
            or nodes['a-corrected']['code_ref'] != 'git:' + commits['a']):
        raise RuntimeError('Lineage must retain recorded Git IDs independently of experiment ancestry')
    if parents != {('a','b'),('a','c')} or len(stale) != 4:
        raise RuntimeError('Expected sibling experiments retaining the superseded original baseline')
    if value['counts']['record_count'] != 4 or value['counts']['execution_count'] != 3:
        raise RuntimeError('Correction must not create another execution identity')
    if nodes['b']['execution_status'] != 'failed' or nodes['c']['execution_status'] != 'cancelled':
        raise RuntimeError('Failed and cancelled states must remain in lineage')
    if not mermaid.startswith('flowchart TD\n') or any(f'|{kind}|' not in mermaid for kind in ('parent','baseline','correction')):
        raise RuntimeError('Mermaid must distinguish the three relationship types')
    cycle.cli('check')
    state = cycle.cli('status')
    if any(path.read_bytes() != content for path,content in before.items()) or git('rev-parse','HEAD') != head:
        raise RuntimeError('Read-only lineage changed canonical records or Git HEAD')
    if list(output.rglob('TRAINING_WAS_EXECUTED')):
        raise RuntimeError('Training sentinel executed unexpectedly')
    if state['budget_used'] != 2:
        raise RuntimeError('Corrections and cancellation must not consume additional experiment budget')
    summary = dict(simulated=True, git_linear=True, experiment_siblings=True, record_count=4,
                   execution_count=3, correction_count=1, failed_count=1, cancelled_count=1,
                   stale_reference_count=4, originals_preserved=True, git_head_preserved=True,
                   training_executed=False, budget_used=2)
    (output / 'summary.json').write_text(dumps(summary), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory under an existing parent')
    args = parser.parse_args()
    print(dumps(demonstrate(args.output.resolve()), ensure_ascii=True), end='')


if __name__ == '__main__':
    main()
