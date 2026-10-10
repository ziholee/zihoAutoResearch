#!/usr/bin/env python3
"""Exercise failure-memory registration/recall/retirement with synthetic data only."""
import argparse
from pathlib import Path
import runpy

from zar.codec import dumps


def demonstrate(output):
    MockCycle = runpy.run_path(str(Path(__file__).with_name('mock-cycle.py')))['MockCycle']
    cycle = MockCycle(output, 'failure-memory')
    cycle.configure()
    failure = cycle.observe('rejected-approach', '2', 'full')
    cycle.decide('rejected-approach', 'discard', 'valid', 'Synthetic rejected approach', failure)
    resolution = cycle.observe('recorded-repair', '1', 'full')
    before = {p: p.read_bytes() for p in cycle.store.rglob('*.json') if 'drafts' not in p.parts}
    body = dict(id='memory-1', supersedes_id=None, status='active', cause='Synthetic rejected approach',
                remedy='Synthetic repair observation', limitation='No real execution or causal confirmation',
                failure_experiment_id='rejected-approach', resolution_experiment_id='recorded-repair',
                evidence=[failure, resolution])
    cycle.cli('memory', 'add', '--file', cycle.draft('memory.json', body))
    original = (cycle.store / 'memories/memory-1.json').read_bytes()
    context = cycle.cli('context', '--memories', '--experiment', 'rejected-approach')
    card = context['cards'][0]
    if card['applicability'] != 'matched' or card['resolution_state'] != 'recorded' or card['evidence_checked']:
        raise RuntimeError('Expected recorded, scoped memory with unchecked evidence')
    page = cycle.cli('evidence', 'read', '--kind', 'memory', '--id', 'memory-1',
                     '--pointer', '/evidence/1', '--revision', '1')
    if page['source']['hash_state'] != 'matched':
        raise RuntimeError('Expected original resolution evidence hash')
    body.update(id='memory-2', supersedes_id='memory-1', cause='Corrected synthetic explanation')
    cycle.cli('memory', 'add', '--file', cycle.draft('corrected-memory.json', body))
    body.update(id='memory-3', supersedes_id='memory-2', status='retired', limitation='Retired synthetic explanation')
    cycle.cli('memory', 'add', '--file', cycle.draft('retired-memory.json', body))
    recalled = cycle.cli('context', '--memories', '--experiment', 'rejected-approach')
    if recalled['cards'] or recalled['memory_counts']['retired'] != 1:
        raise RuntimeError('Retired memory must not be recalled as active')
    cycle.cli('report', '--output', 'memory.md')
    cycle.cli('check')
    if any(p.read_bytes() != value for p, value in before.items()):
        raise RuntimeError('Original project/experiment/review bytes changed')
    if (cycle.store / 'memories/memory-1.json').read_bytes() != original:
        raise RuntimeError('Original memory changed')
    if list(output.rglob('TRAINING_WAS_EXECUTED')):
        raise RuntimeError('Synthetic training sentinel was executed')
    return dict(simulated=True, memory_counts=recalled['memory_counts'], originals_preserved=True,
                evidence_hash_matched=True, budget_used=recalled['budget_used'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(dumps(demonstrate(args.output.resolve()), ensure_ascii=True), end='')


if __name__ == '__main__':
    main()
