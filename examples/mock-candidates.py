#!/usr/bin/env python3
"""Synthetic candidate forecast, selected intention, observation and deferral."""
import argparse
from pathlib import Path
import runpy
from zar.codec import dumps


def demonstrate(output):
    MockCycle = runpy.run_path(str(Path(__file__).with_name('mock-cycle.py')))['MockCycle']
    cycle = MockCycle(output, 'candidate-rationale')
    cycle.configure()
    baseline_evidence = cycle.observe('reference', '1.2', 'full')
    cycle.decide('reference', 'keep', 'valid', 'Synthetic valid reference', baseline_evidence)
    cycle.select('reference', 'Evaluate one declared candidate within the unchanged mock budget')
    candidate = dict(id='proposal-1', supersedes_id=None, status='selected',
        hypothesis='Synthetic candidate observation', parent_id='reference',
        analysis='Supplied synthetic baseline motivates trying a supplied alternative', evidence=[baseline_evidence],
        exploratory_reason=None, expected_effect='Expect 0.1 improvement; an author forecast only',
        expected_cost=dict(run_seconds=30, note='Author estimate; actual resource use unmeasured'),
        uncertainty='No real data, execution or causal inference',
        decision_reason='Choose this mock candidate for the one remaining trial',
        reconsideration=dict(trigger='initial', reason='No previous trial of this candidate'), memory_ids=[])
    cycle.cli('candidate', 'add', '--file', cycle.draft('candidate.json', candidate))
    source = cycle.store / 'candidates/proposal-1.json'
    forecast_bytes = source.read_bytes()
    evidence = cycle.observe('trial', '1.2', 'full', 'reference', candidate_id='proposal-1')
    cycle.decide('trial', 'hold', 'valid', 'Supplied mock observation did not improve', evidence,
                 'Defer candidate and record reconsideration before any new trial')
    before = {p: p.read_bytes() for p in cycle.store.rglob('*.json') if 'drafts' not in p.parts}
    candidate.update(id='proposal-2', supersedes_id='proposal-1', status='deferred',
        decision_reason='No observed improvement; no further mock budget',
        reconsideration=dict(trigger='stagnation', reason='One non-improving mock result; no general plateau claim'))
    cycle.cli('candidate', 'add', '--file', cycle.draft('deferred.json', candidate))
    context = cycle.cli('context', '--candidates')
    card = context['cards'][0]
    if card['status'] != 'deferred' or card['signals']['non_improving'] != 1:
        raise RuntimeError('Expected deferred candidate with a factual non-improving signal')
    outcome = card['outcomes'][0]
    if outcome['candidate_id'] != 'proposal-1' or outcome['actual_cost_state'] != 'unknown':
        raise RuntimeError('Outcome must retain original forecast version and unmeasured cost')
    page = cycle.cli('evidence', 'read', '--kind', 'candidate', '--id', 'proposal-1', '--pointer', '/evidence/0')
    if page['source']['hash_state'] != 'matched':
        raise RuntimeError('Expected preserved analysis evidence')
    cycle.cli('report', '--output', 'candidates.md')
    cycle.cli('check')
    if source.read_bytes() != forecast_bytes or any(p.read_bytes() != data for p, data in before.items()):
        raise RuntimeError('Candidate transition changed original forecast, experiment or project')
    if list(output.rglob('TRAINING_WAS_EXECUTED')):
        raise RuntimeError('Synthetic training sentinel was executed')
    if context['budget_used'] != 2 or context['selected_experiment_id'] != 'reference':
        raise RuntimeError('Candidate transition must preserve budget and selected result')
    return dict(simulated=True, deferred=1, non_improving=1, forecasts_preserved=True,
                actual_cost_state='unknown', budget_used=2, selected_experiment_id='reference')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(dumps(demonstrate(args.output.resolve()), ensure_ascii=True), end='')


if __name__ == '__main__':
    main()
