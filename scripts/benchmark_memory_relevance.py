#!/usr/bin/env python3
"""Mock selector benchmark; never calls an API or runs training.

In-process wall seconds include safe session reads, parsing/cache lookup, record
provenance checks and selection. Fixture creation and verification are excluded.
Timing runs without tracemalloc or mock instrumentation. A separate allocation
pass reports peak traced Python allocation, not RSS or total process memory.
Cold/warm refer only to the supplied parsing cache; OS caches are uncontrolled.
Synthetic records contain selector fields, not full validated CLI documents.
Use benchmark_research_scale.py for full CLI lifecycle measurements.

Example: python scripts/benchmark_memory_relevance.py --output /tmp/memory-scale
Smoke: add --records 100 --sessions 20 --skip-boundaries --repeats 1
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zar import research, session_memory as memory
from zar.codec import dumps

LIMIT = 8 * 1024 * 1024
BOUNDARIES = ((2047, None, 0), (2048, None, 0), (2049, None, 0),
              (128, LIMIT - 1, 0), (128, LIMIT, 0), (128, LIMIT + 1, 0),
              (16, 16 * 1024 * 1024, 0), (100, None, 16000))


def record(identifier, score=1, baseline='base'):
    return dict(id=identifier, revision=1, baseline_id=baseline, correction=None,
                comparison=dict(id='synthetic', dataset_ref='data', split_ref='test', metric='score',
                                direction='minimize', evaluation_ref='evaluation', min_delta=0),
                environment=dict(os='other', runtime='python', device='cpu'),
                run_context=dict(scope='full', seed=42, budget_ref='one'),
                execution=dict(status='succeeded', score=score), decision=None,
                code_ref='synthetic-code', config_ref='synthetic-config')


def identifier(index):
    return 'session-' + format(index, '032x')


def fixture(root, records=100, sessions=100, target_bytes=None, memory_characters=0,
            distribution='selective'):
    """Known construction: six oldest matches, then newer mismatches.

    The all-matched distribution instead makes every non-stale session match.
    A separate stale pair is mutated after assessment. Every mismatch shares one
    pair, exposing accidental per-session full-record scanning or rehashing.
    Expected IDs are construction constants, never computed by the selector.
    """
    if records < 8 or sessions < 10:
        raise ValueError('At least eight records and ten sessions required')
    if distribution not in ('selective', 'all-matched'):
        raise ValueError('Unknown fixture distribution')
    experiments = {'base': record('base', 2, None)}
    for name in ('matched', 'mismatch', 'stale'):
        experiments[name] = record(name)
    experiments['mismatch']['run_context']['scope'] = 'proxy'
    for index in range(records - len(experiments)):
        key = 'unused-' + str(index)
        experiments[key] = record(key)
    project = {key: deepcopy(experiments['base'][key]) for key in ('comparison', 'environment')}
    active = dict(id=identifier(sessions + 1), memory_selection_version=1,
                  run_context=deepcopy(experiments['base']['run_context']),
                  experiment_id=None, baseline_id='base', code_ref='synthetic-code',
                  config_ref='synthetic-config')
    directory = root / '.autoresearch/sessions'
    directory.mkdir(parents=True)
    documents = []
    for index in range(sessions):
        key = ('stale' if index == 6 else 'matched'
               if distribution == 'all-matched' or index < 6 else 'mismatch')
        session = dict(id=identifier(index), state='complete', experiment_id=key,
                       created_at=f'{index:012d}', outputs={}, memory_contract_version=1)
        evidence = memory.build_evidence(session, experiments, superseded=set())
        proposal = dict(summary='synthetic', evidence=[], uncertainties=[], next_action='stop',
                        lesson='m' * max(1, memory_characters), limitation='synthetic only',
                        contrast=dict(effect='helped', applicability='synthetic', evidence=list(evidence['handles'])))
        session['outputs']['memory'] = proposal
        session['memory_assessment'] = memory.assess(proposal, evidence)
        session['padding'] = ''
        documents.append(session)
    experiments['stale']['revision'] += 1
    sizes = [len(dumps(doc).encode()) for doc in documents]
    if target_bytes is not None:
        extra = target_bytes - sum(sizes)
        if extra < 0:
            raise ValueError('Requested bytes below fixture minimum')
        each, remainder = divmod(extra, sessions)
        for index, doc in enumerate(documents):
            doc['padding'] = 'x' * (each + (index < remainder))
    digest = hashlib.sha256()
    digest.update(dumps(dict(project=project, active=active, experiments=experiments)).encode())
    final_sizes = []
    for doc in documents:
        raw = dumps(doc).encode()
        if len(raw) > 2_000_000:
            raise ValueError('Session exceeds product file bound')
        (directory / (doc['id'] + '.json')).write_bytes(raw)
        digest.update(raw)
        final_sizes.append(len(raw))
    assert target_bytes is None or sum(final_sizes) == target_bytes
    expected_indices = (5, 4, 3, 2, 1) if distribution == 'selective' else [
        index for index in range(sessions - 1, -1, -1) if index != 6][:5]
    expected = [identifier(index) for index in expected_indices]
    return dict(project=project, active=active, experiments=experiments, expected=expected,
                sizes=final_sizes, fixture_sha256=digest.hexdigest(), distribution=distribution)


def select(root, data, cache):
    return research._prior_lessons(root.resolve(), data['active'], cache,
                                  project=data['project'], experiments=data['experiments'])


def verify(result, data):
    lessons, summary = result
    assert [item['session_id'] for item in lessons] == data['expected']
    assert all(item['assessment']['status'] == 'hold' for item in lessons)
    assert all(item['relevance'] == 'matched' for item in lessons)
    matched = 6 if data['distribution'] == 'selective' else len(data['sizes']) - 1
    assert summary['counts'] == dict(eligible=len(data['sizes']), matched=matched,
        unknown=0, mismatch=len(data['sizes']) - matched - 1, source_changed=1, limit=matched - 5)


def retained(sizes):
    count = total = 0
    for size in sizes:
        if count < research.HISTORY_CACHE_MAX_ENTRIES and total + size <= research.HISTORY_CACHE_MAX_BYTES:
            count += 1
            total += size
    return count, total


class CountingRecords(dict):
    values_calls = 0

    def values(self):
        self.values_calls += 1
        return super().values()


def measure(root, data, repeats):
    expected = select(root, data, None)
    verify(expected, data)
    cache = {}
    assert select(root, data, cache) == expected
    entries, byte_count = retained(data['sizes'])
    assert len(cache) == entries
    assert sum(value[2] for value in cache.values()) == byte_count
    timings = {'cold': [], 'warm': []}
    for _ in range(repeats):
        for mode in timings:
            supplied = {} if mode == 'cold' else cache
            started = time.perf_counter()
            actual = select(root, data, supplied)
            elapsed = time.perf_counter() - started
            assert actual == expected
            timings[mode].append(elapsed)
    allocation = {}
    for mode in timings:
        supplied = {} if mode == 'cold' else cache
        tracemalloc.start()
        actual = select(root, data, supplied)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert actual == expected
        allocation[mode] = peak
    # Instrumentation is a distinct untimed pass. Each shared pair is hashed
    # only a bounded number of times independent of sessions and unused records.
    counted = CountingRecords(data['experiments'])
    instrumented = dict(data, experiments=counted)
    with patch.object(memory, 'identity', wraps=memory.identity) as hashing:
        assert select(root, instrumented, cache) == expected
    assert hashing.call_count <= 4, hashing.call_count
    assert counted.values_calls <= 1, counted.values_calls
    return dict(records=len(data['experiments']), sessions=len(data['sizes']),
                normalized_utf8_bytes=sum(data['sizes']), retained_entries=entries,
                retained_input_bytes=byte_count, record_identity_calls=hashing.call_count,
                record_values_scans=counted.values_calls,
                selected_count=len(expected[0]), selection_counts=expected[1]['counts'],
                fixture_sha256=data['fixture_sha256'], equivalent=True,
                all_matched_distribution=data['distribution'] == 'all-matched',
                cold_wall_seconds=timings['cold'], warm_wall_seconds=timings['warm'],
                cold_median_seconds=statistics.median(timings['cold']),
                warm_median_seconds=statistics.median(timings['warm']),
                cold_peak_traced_bytes=allocation['cold'], warm_peak_traced_bytes=allocation['warm'])


def source_digest():
    digest = hashlib.sha256()
    for path in sorted((Path(__file__).resolve().parents[1] / 'zar').glob('*.py')):
        digest.update(path.name.encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--records', type=int, nargs='+', default=[100, 1000, 10000])
    parser.add_argument('--sessions', type=int, nargs='+', default=[100, 1000])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--skip-boundaries', action='store_true',
                        help='Skip cache boundaries and the large all-matched stress case')
    parser.add_argument('--distribution', choices=['selective', 'all-matched'], default='selective')
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 1 or min(args.records) < 8 or min(args.sessions) < 10:
        parser.error('New output directory, positive repeats, records >= 8 and sessions >= 10 required')
    args.output.mkdir(parents=True)
    private = args.output / 'private'
    private.mkdir(mode=0o700)
    definitions = [(count, args.sessions[0], None, 0, args.distribution) for count in args.records]
    definitions += [(args.records[0], count, None, 0, args.distribution) for count in args.sessions[1:]]
    if not args.skip_boundaries:
        definitions += [(args.records[0], count, size, memory_size, args.distribution)
                        for count, size, memory_size in BOUNDARIES]
        definitions.append((10000, 2500, None, 16000, 'all-matched'))
    before = source_digest()
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report = dict(version=1, source_sha256=before, measurement_sha256=script_hash,
                  repeats=args.repeats, warmups=1, api_calls=0, cases=[])
    for index, (count, sessions, size, memory_size, distribution) in enumerate(definitions):
        root = private / str(index)
        data = fixture(root, count, sessions, size, memory_size, distribution)
        case = measure(root, data, args.repeats)
        case['case_index'] = index
        case['memory_characters'] = memory_size
        report['cases'].append(case)
        print(json.dumps(dict(case_index=index, records=count, sessions=sessions,
                             cold_median_seconds=case['cold_median_seconds'])), flush=True)
    assert source_digest() == before, 'Source changed during benchmark'
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == script_hash
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
