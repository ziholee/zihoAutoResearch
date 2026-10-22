#!/usr/bin/env python3
"""Record-digest temporary allocation and time, separate from CLI latency.

Each frozen source loads the same validated records outside measurement. The
actual research.records_digest helper is used when present, otherwise the original
research.digest. Control measures only that digest call. A separate allocation
mode traces the same call after input loading and garbage collection; it measures
temporary Python allocations, not RSS or the existing record snapshot. Fresh
processes isolate every mode/source/repetition; one warmup precedes measured pairs
and before/after execution order alternates.

After timing/tracing has stopped, a second call writes every SHA256 constructor
and update input to a private file in order. That instrumentation retains no chunk
list and never runs during measurement. The parent directly compares these bytes
across sources/modes/repetitions, also checking hashes and immutable fixtures.
Only numeric summaries and hashes are public. Loading, validation, instrumentation,
output writing and process startup are outside timing. No API or training runs.
"""
import argparse
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
from types import SimpleNamespace

HERE = Path(__file__).resolve()
BASE = runpy.run_path(str(HERE.with_name('benchmark_research_scale.py')))
MODES = ('control', 'allocation')


def worker(source, root, mode, metadata):
    sys.path.insert(0, str(source))
    from unittest.mock import patch
    from zar import records, research
    snap = records.load_records(root, research.get_project(root))
    assert not snap.diagnostics, 'Synthetic records must validate without diagnostics'
    function = getattr(research, 'records_digest', research.digest)
    gc.collect()
    if mode == 'allocation':
        import tracemalloc
        tracemalloc.start()
    started = time.perf_counter()
    identity = function(snap.records)
    elapsed = time.perf_counter() - started
    allocation = None
    if mode == 'allocation':
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        allocation = dict(current_traced_bytes=current, peak_traced_bytes=peak)

    # Separate untimed verification: do not keep the chunks in a Python list.
    counters = dict(serialized_bytes=0, chunks=0, max_chunk_bytes=0)
    with metadata.with_suffix('.canonical').open('xb') as stream:
        def capture(data):
            stream.write(data)
            if data:
                counters['chunks'] += 1
                counters['serialized_bytes'] += len(data)
                counters['max_chunk_bytes'] = max(counters['max_chunk_bytes'], len(data))

        class HashProxy:
            def __init__(self, data=b'', **kwargs):
                capture(data)
                self.value = hashlib.sha256(data, **kwargs)

            def update(self, data):
                capture(data)
                self.value.update(data)

            def hexdigest(self):
                return self.value.hexdigest()

        with patch.object(research, 'hashlib', SimpleNamespace(sha256=HashProxy)):
            captured_identity = function(snap.records)
    assert captured_identity == identity
    assert counters['serialized_bytes'] > 0, 'Digest input capture was bypassed'
    BASE['write_json'](metadata, dict(validated=True, **counters, sha256=identity,
        experiment_count=len(snap.records['experiment']), seconds=elapsed,
        allocation=allocation))


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
        raise RuntimeError('Digest worker failed; inspect private output ' + output.name)
    assert not result.stdout and not result.stderr
    return json.loads(metadata.read_text(encoding='utf-8'))


def summarize(trials, mode):
    summary = dict(seconds=statistics.median(t['seconds'] for t in trials))
    if mode == 'allocation':
        summary['peak_traced_bytes'] = statistics.median(t['allocation']['peak_traced_bytes'] for t in trials)
        summary['current_traced_bytes'] = statistics.median(t['allocation']['current_traced_bytes'] for t in trials)
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
                    assert raw == expected, 'Canonical digest input bytes changed'
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
