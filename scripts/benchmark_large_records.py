#!/usr/bin/env python3
"""Large-record batch boundaries with crossed source order; synthetic data only.

Cases 63/64/65 keep large hypotheses at indices 0,31,62 so crossing a batch
boundary never adds another large record. Mixed uses 10,000 records plus 2,500
completed sessions with 16,000-character memories. Each large hypothesis has
262,144 characters by default: ASCII, Korean and emoji respectively, so UTF-8
sizes differ. These are character counts, not a promised byte limit.

Actual record digest control/allocation workers and CLI plan/status/resume
workers are reused. Fresh processes, one warmup pair then alternating AB/BA
pairs; digest allocations exclude input loading and are separate from control.
Digest bytes are captured only after measurement and compared directly. CLI wall
includes startup/output/persisted-token checks/metadata/exit; preparation and
parent verification are excluded. RSS is the child high-water mark, not traced
allocation. Source/input/tool hashes, latest memories, roles, budget, approvals,
CLI semantics and original files are checked. Resume is mock interruption, not
OS crash. Public data contains numeric metadata and hashes, private holds raw
outputs. No API, training or performance threshold decides validity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import runpy
import shutil

HERE = Path(__file__).resolve()
CROSSED = runpy.run_path(str(HERE.with_name('benchmark_crossed_research.py')))
BOUNDARY, BASE = CROSSED['BOUNDARY'], CROSSED['BASE']
DIGEST = runpy.run_path(str(HERE.with_name('profile_record_digest.py')))
LARGE_INDICES = (0, 31, 62)


def resize_records(root, characters):
    """Keep exactly three fixed-position large records, including across 63/64/65."""
    paths = [root / '.autoresearch/experiments' / f'exp-{index:06d}.json'
             for index in LARGE_INDICES]
    if characters < 1 or not all(path.is_file() for path in paths):
        raise ValueError('Positive characters and fixed record indices 0,31,62 required')
    large = []
    for index, scalar in zip(LARGE_INDICES, ('x', '한', '😀')):
        path = root / '.autoresearch/experiments' / f'exp-{index:06d}.json'
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc['hypothesis'] = scalar * characters
        path.write_bytes(BOUNDARY['compact'](doc))
        large.append(dict(index=index, characters=characters,
                          hypothesis_utf8_bytes=len(doc['hypothesis'].encode('utf-8')),
                          file_bytes=path.stat().st_size))
    sizes = [p.stat().st_size for p in sorted((root / '.autoresearch/experiments').glob('*.json'))]
    return dict(records=len(sizes), total_file_bytes=sum(sizes), min_file_bytes=min(sizes),
                max_file_bytes=max(sizes), large_records=large)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--after', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=['63', '64', '65', 'mixed'],
                        default=['63', '64', '65', 'mixed'])
    parser.add_argument('--large-characters', type=int, default=262144)
    parser.add_argument('--mixed-records', type=int, default=10000)
    parser.add_argument('--mixed-sessions', type=int, default=2500)
    parser.add_argument('--memory-characters', type=int, default=16000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    if (args.output.exists() or args.large_characters < 1 or args.mixed_records < 63
            or args.mixed_sessions < 1 or args.repeats < 1 or args.timeout <= 0
            or not 1 <= args.memory_characters <= 20000 or len(set(args.cases)) != len(args.cases)):
        parser.error('New output, unique cases, positive sizes/repeats/timeout, mixed records >=63 required')
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
        'benchmark_crossed_research.py', 'profile_record_digest.py',
        'benchmark_session_boundaries.py', 'benchmark_research_scale.py', 'benchmark_records.py')]
    def measurement_hash():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    measured = measurement_hash()
    report = dict(version=1, methodology=__doc__, python=platform.python_version(),
        platform=platform.system() + '-' + platform.machine(), source_digest=source_hashes,
        measurement_digest=measured, repeats=args.repeats, warmup_pairs=1, cases=[])
    for key in args.cases:
        count = args.mixed_records if key == 'mixed' else int(key)
        sessions = args.mixed_sessions if key == 'mixed' else 0
        memory = args.memory_characters if sessions else None
        seed = private / (key + '-fixture')
        lessons = BASE['fixture'](sources['before'], seed, count, sessions, private, args.timeout)
        records_dimensions = resize_records(seed, args.large_characters)
        history_dimensions = BOUNDARY['resize_history'](seed, memory_characters=memory)
        for lesson in lessons:
            saved = json.loads((seed / '.autoresearch/sessions' / (lesson['session_id'] + '.json')).read_text(encoding='utf-8'))
            lesson['proposal'] = saved['outputs']['memory']
        for source in sources.values():
            BOUNDARY['validate_history'](source, seed, args.timeout)
        fixture_hash = BASE['tree_digest'](seed, '*')
        records_hash, history_hash = BASE['records_digest'](seed), BASE['history_digest'](seed)
        case = dict(key=key, records=records_dimensions, history=history_dimensions,
                    memory_characters=memory, fixture_digest=fixture_hash, digest={}, operations={})
        expected = None
        for mode in DIGEST['MODES']:
            trials = dict(before=[], after=[]); order = []
            for repetition in range(args.repeats + 1):
                labels = CROSSED['arm_order'](repetition)
                if repetition:
                    order.append(labels)
                for label in labels:
                    name = private / f'{key}-digest-{mode}-{repetition}-{label}'
                    sample = DIGEST['run'](sources[label], seed, mode, name, args.timeout)
                    raw = name.with_suffix('.canonical').read_bytes()
                    if expected is None:
                        expected = raw
                    assert raw == expected, 'Canonical digest input bytes changed'
                    assert sample['sha256'] == hashlib.sha256(expected).hexdigest()
                    assert sample['experiment_count'] == count
                    if repetition:
                        trials[label].append(sample)
            case['digest'][mode] = dict(order=order, trials=trials,
                medians={label: DIGEST['summarize'](samples, mode) for label, samples in trials.items()})
        case['digest_byte_equality_verified'] = True
        case['digest_input_bytes'] = len(expected)
        case['digest_sha256'] = hashlib.sha256(expected).hexdigest()
        del expected
        print(key + ' digest: byte equality verified', flush=True)
        for mode in ('plan', 'status', 'resume'):
            trials = dict(before=[], after=[]); order, differences = [], []
            semantic = None
            for repetition in range(args.repeats + 1):
                labels = CROSSED['arm_order'](repetition); pair = {}
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
                        for field in CROSSED['FIELDS']})
            summary = dict(order=order, trials=trials, after_minus_before=differences,
                medians={label: CROSSED['summarize'](samples) for label, samples in trials.items()})
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
