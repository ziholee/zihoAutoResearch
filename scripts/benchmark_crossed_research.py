#!/usr/bin/env python3
"""Crossed before/after mock CLI measurements, not actual provider performance.

Small (100 records, no history) and mixed (10,000 records, 2,500 completed
sessions with 16,000-character memories) use one common fixture per condition.
Every operation/arm runs in a fresh process from its own fixture copy. One warmup
pair precedes measured pairs; arm order alternates before/after and after/before.
Preparation, fixture copying and parent verification are outside wall timing.
The existing worker includes startup, CLI, output, persisted-token verification,
metadata and exit. RSS is child high-water mark (null on unsupported platforms).
Recent memories, CLI semantics, roles, budget, approvals and original files are
verified for every warmup and sample. Resume follows controlled mock interruption,
not OS crash. No API or training runs; no performance threshold decides validity.
Raw output stays private; public metadata contains numeric observations and hashes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import runpy
import shutil
import statistics

HERE = Path(__file__).resolve()
BOUNDARY = runpy.run_path(str(HERE.with_name('benchmark_session_boundaries.py')))
BASE = BOUNDARY['BASE']
FIELDS = ('wall_seconds', 'peak_rss_bytes', 'stdout_bytes', 'record_loads',
          'session_loads', 'model_calls', 'prompt_bytes')


def arm_order(repetition):
    # Repetition zero is warmup; measured pair one starts with before.
    return ['before', 'after'] if repetition % 2 else ['after', 'before']


def summarize(trials):
    return {field: (statistics.median(values) if all(v is not None for v in values) else None)
            for field in FIELDS for values in [[sample[field] for sample in trials]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--small-records', type=int, default=100)
    parser.add_argument('--mixed-records', type=int, default=10000)
    parser.add_argument('--mixed-sessions', type=int, default=2500)
    parser.add_argument('--memory-characters', type=int, default=16000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args()
    if (args.output.exists() or min(args.small_records, args.mixed_records, args.mixed_sessions,
                                    args.repeats) < 1 or args.timeout <= 0
            or not 1 <= args.memory_characters <= 20000):
        parser.error('New output and positive counts/repeats/timeout; memory characters 1..20000 required')
    output = args.output.resolve(); output.mkdir()
    private = output / 'private'; private.mkdir(mode=0o700)
    originals = dict(before=args.before.resolve(), after=args.after.resolve())
    sources, source_hashes = {}, {}
    for label, original in originals.items():
        source = private / label; source.mkdir()
        source_hashes[label] = BASE['tree_digest'](original / 'zar', '*.py')
        for name in ('zar', 'examples', 'skills'):
            shutil.copytree(original / name, source / name,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        shutil.copy2(original / 'pyproject.toml', source / 'pyproject.toml')
        assert BASE['tree_digest'](source / 'zar', '*.py') == source_hashes[label]
        sources[label] = source
    paths = [HERE] + [HERE.with_name(name) for name in (
        'benchmark_session_boundaries.py', 'benchmark_research_scale.py', 'benchmark_records.py')]
    def measurement_hash():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    measured = measurement_hash()
    report = dict(version=1, methodology=__doc__, python=platform.python_version(),
        platform=platform.system() + '-' + platform.machine(), source_digest=source_hashes,
        measurement_digest=measured, repeats=args.repeats, warmup_pairs=1, cases=[])
    definitions = [('small', args.small_records, 0, None),
                   ('mixed', args.mixed_records, args.mixed_sessions, args.memory_characters)]
    for key, count, sessions, memory in definitions:
        seed = private / (key + '-fixture')
        lessons = BASE['fixture'](sources['before'], seed, count, sessions, private, args.timeout)
        dimensions = BOUNDARY['resize_history'](seed, memory_characters=memory)
        for lesson in lessons:
            saved = json.loads((seed / '.autoresearch/sessions' / (lesson['session_id'] + '.json')).read_text(encoding='utf-8'))
            lesson['proposal'] = saved['outputs']['memory']
        for source in sources.values():
            BOUNDARY['validate_history'](source, seed, args.timeout)
        fixture_hash = BASE['tree_digest'](seed, '*')
        records_hash, history_hash = BASE['records_digest'](seed), BASE['history_digest'](seed)
        case = dict(key=key, records=count, dimensions=dimensions,
                    memory_characters=memory, fixture_digest=fixture_hash, operations={})
        for mode in ('plan', 'status', 'resume'):
            trials = dict(before=[], after=[])
            order, differences = [], []
            semantic = None
            for repetition in range(args.repeats + 1):
                labels = arm_order(repetition)
                pair = {}
                for label in labels:
                    name = f'{key}-{mode}-{repetition}-{label}'
                    root = private / name; shutil.copytree(seed, root)
                    BOUNDARY['prepare'](sources[label], root, mode, private / (name + '-prepare'), args.timeout)
                    sample = BASE['run'](sources[label], root, mode, private / (name + '-measured'), args.timeout)
                    BASE['verify'](root, sample, mode, lessons, records_hash, history_hash)
                    if semantic is None:
                        semantic = sample['semantic_sha256']
                    assert sample['semantic_sha256'] == semantic, 'Before/after CLI semantics changed'
                    pair[label] = sample
                    if repetition:
                        trials[label].append(sample)
                    shutil.rmtree(root)
                if repetition:
                    order.append(labels)
                    differences.append({field: (pair['after'][field] - pair['before'][field]
                        if pair['after'][field] is not None and pair['before'][field] is not None else None)
                        for field in FIELDS})
            summary = dict(order=order, trials=trials, after_minus_before=differences,
                medians={label: summarize(samples) for label, samples in trials.items()})
            case['operations'][mode] = summary
            print(f'{key} {mode}: before {summary["medians"]["before"]["wall_seconds"]:.4f}s; '
                  f'after {summary["medians"]["after"]["wall_seconds"]:.4f}s', flush=True)
        assert BASE['tree_digest'](seed, '*') == fixture_hash
        report['cases'].append(case)
        BASE['write_json'](output / (key + '.json'), case)
    assert measurement_hash() == measured, 'Measurement source changed'
    for label, source in sources.items():
        assert BASE['tree_digest'](source / 'zar', '*.py') == source_hashes[label]
        assert BASE['tree_digest'](originals[label] / 'zar', '*.py') == source_hashes[label]
    BASE['write_json'](output / 'summary.json', report)


if __name__ == '__main__':
    main()
