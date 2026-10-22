#!/usr/bin/env python3
"""Isolated record-identity serialization diagnostics, not CLI latency.

Both frozen sources load the same validated synthetic records outside timing.
Control times codec.dumps, UTF-8 encoding and SHA256 separately. Scalar-profile
wraps JSONEncoder.encode inside the actual serializer: its elapsed time and call
count diagnose scalar quoting, while the remaining dumps time combines dispatch,
validation, recursive traversal, separators and joining. There is no independent
normalization pass in the current codec, so the remainder is not a normalization
measurement. Wrapper overhead perturbs that diagnostic; control is the comparison.
Allocation runs use tracemalloc separately, starting after records are loaded.
They measure temporary traced allocations, not RSS or the complete live record
snapshot. Text and UTF-8 output coexist during conversion, then text is released
before hashing, matching the digest expression's lifetime. Preparation, loading,
validation, output writing and process startup are excluded from phase timings.
Each mode/source/repetition uses a fresh process; source order alternates.
One warmup per mode/source precedes measured repetitions. Output bytes are compared
directly across every worker; public reports contain only numbers and hashes.
No API, training or mutation is performed. No speed threshold determines validity.
"""
import argparse
from contextlib import nullcontext
import gc
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
import time

HERE = Path(__file__).resolve()
BASE = runpy.run_path(str(HERE.with_name('benchmark_research_scale.py')))
MODES = ('control', 'scalar-profile', 'allocation')


def worker(source, root, mode, metadata):
    sys.path.insert(0, str(source))
    from unittest.mock import patch
    from zar import codec, records, research
    snap = records.load_records(root, research.get_project(root))
    assert not snap.diagnostics, 'Synthetic records must validate without diagnostics'
    gc.collect()
    scalar = dict(seconds=0.0, calls=0)
    original = json.JSONEncoder.encode

    def scalar_encode(self, item):
        started = time.perf_counter()
        try:
            return original(self, item)
        finally:
            scalar['seconds'] += time.perf_counter() - started
            scalar['calls'] += 1

    events = []
    if mode == 'allocation':
        import tracemalloc
        tracemalloc.start()

    def event(phase):
        if mode == 'allocation':
            current, peak = tracemalloc.get_traced_memory()
            events.append(dict(phase=phase, current_traced_bytes=current,
                               cumulative_peak_traced_bytes=peak))

    event('begin')
    # Both control and profile use the product serializer; no replacement codec.
    with (patch.object(json.JSONEncoder, 'encode', scalar_encode) if mode == 'scalar-profile' else nullcontext()):
        started = time.perf_counter()
        text = codec.dumps(snap.records)
        serialized = time.perf_counter() - started
    event('serialized')
    text_bytes = sys.getsizeof(text)
    started = time.perf_counter()
    raw = text.encode('utf-8')
    encoded = time.perf_counter() - started
    event('utf8_encoded')
    del text
    event('text_released')
    started = time.perf_counter()
    identity = hashlib.sha256(raw).hexdigest()
    hashed = time.perf_counter() - started
    event('hashed')
    peak = None
    if mode == 'allocation':
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    # Keep canonical bytes private; parent compares bytes, not only the hash.
    metadata.with_suffix('.canonical').write_bytes(raw)
    result = dict(validated=True, serialized_bytes=len(raw), sha256=identity,
        experiment_count=len(snap.records['experiment']), text_object_bytes=text_bytes,
        utf8_object_bytes=sys.getsizeof(raw), seconds=dict(serialize=serialized,
        utf8=encoded, sha256=hashed, total=serialized + encoded + hashed),
        scalar_profile=(dict(scalar, traversal_validation_assembly_seconds=serialized - scalar['seconds'])
                        if mode == 'scalar-profile' else None),
        allocation=(dict(events=events, peak_traced_bytes=peak) if mode == 'allocation' else None))
    BASE['write_json'](metadata, result)


def run(source, root, mode, output, timeout):
    metadata = output.with_suffix('.json')
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(HERE),
        '--source', str(source), '--worker', mode, '--root', str(root),
        '--metadata', str(metadata)], cwd=source, env=env,
        capture_output=True, timeout=timeout)
    output.with_suffix('.stdout').write_bytes(result.stdout)
    output.with_suffix('.stderr').write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError('Serialization worker failed; inspect private output ' + output.name)
    assert not result.stdout and not result.stderr
    return json.loads(metadata.read_text(encoding='utf-8'))


def summarize(trials, mode):
    summary = dict(seconds={key: statistics.median(t['seconds'][key] for t in trials)
                            for key in ('serialize', 'utf8', 'sha256', 'total')})
    if mode == 'scalar-profile':
        summary['scalar_profile'] = {key: statistics.median(t['scalar_profile'][key] for t in trials)
                                     for key in ('seconds', 'calls', 'traversal_validation_assembly_seconds')}
    if mode == 'allocation':
        summary['peak_traced_bytes'] = statistics.median(t['allocation']['peak_traced_bytes'] for t in trials)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--after', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--records', nargs='+', type=int, default=[100, 10000])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--source', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--worker', choices=MODES, help=argparse.SUPPRESS)
    parser.add_argument('--root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--metadata', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.source.resolve(), args.root, args.worker, args.metadata)
        return
    if (not args.before or not args.after or not args.output or args.output.exists()
            or args.repeats < 1 or args.timeout <= 0 or any(n < 1 for n in args.records)
            or len(set(args.records)) != len(args.records)):
        parser.error('Two sources, new output, unique positive record counts/repeats/timeout required')
    output = args.output.resolve(); output.mkdir()
    private = output / 'private'; private.mkdir(mode=0o700)
    originals = dict(before=args.before.resolve(), after=args.after.resolve())
    sources, source_hashes = {}, {}
    for label, original in originals.items():
        source = private / label; source.mkdir()
        for name in ('zar', 'examples', 'skills'):
            shutil.copytree(original / name, source / name,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
        shutil.copy2(original / 'pyproject.toml', source / 'pyproject.toml')
        sources[label] = source
        source_hashes[label] = BASE['tree_digest'](original / 'zar', '*.py')
        assert BASE['tree_digest'](source / 'zar', '*.py') == source_hashes[label]
    measured = [HERE, HERE.with_name('benchmark_research_scale.py'), HERE.with_name('benchmark_records.py')]
    def measurement_hash():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in measured}
    measured_hash = measurement_hash()
    report = dict(version=1, methodology=__doc__, python=platform.python_version(),
        platform=platform.system() + '-' + platform.machine(), source_digest=source_hashes,
        measurement_digest=measured_hash, repeats=args.repeats, warmups=1, cases=[])
    for count in args.records:
        root = private / f'records-{count}'
        BASE['fixture'](sources['before'], root, count, 0, private, args.timeout)
        fixture_hash = BASE['tree_digest'](root, '*')
        case = dict(records=count, fixture_digest=fixture_hash, modes={})
        expected = None
        for mode in MODES:
            trials = dict(before=[], after=[])
            order = []
            for repetition in range(args.repeats + 1):
                labels = ['before', 'after'] if repetition % 2 else ['after', 'before']
                if repetition:
                    order.append(labels)
                for label in labels:
                    name = private / f'{count}-{mode}-{repetition}-{label}'
                    result = run(sources[label], root, mode, name, args.timeout)
                    raw = name.with_suffix('.canonical').read_bytes()
                    if expected is None:
                        expected = raw
                    assert raw == expected, 'Canonical serialization bytes changed'
                    assert result['sha256'] == hashlib.sha256(expected).hexdigest()
                    assert result['experiment_count'] == count
                    if repetition:
                        trials[label].append(result)
            case['modes'][mode] = dict(order=order, trials=trials,
                medians={label: summarize(items, mode) for label, items in trials.items()})
        case['byte_equality_verified'] = True
        case['sha256'] = hashlib.sha256(expected).hexdigest()
        case['serialized_bytes'] = len(expected)
        assert BASE['tree_digest'](root, '*') == fixture_hash
        report['cases'].append(case)
        print(f'records-{count}: byte equality verified', flush=True)
    assert measurement_hash() == measured_hash
    for label, source in sources.items():
        assert BASE['tree_digest'](source / 'zar', '*.py') == source_hashes[label]
        assert BASE['tree_digest'](originals[label] / 'zar', '*.py') == source_hashes[label]
    BASE['write_json'](output / 'summary.json', report)


if __name__ == '__main__':
    main()
