#!/usr/bin/env python3
"""Separate allocation diagnostics for fresh-process mocked record research loops.

This diagnostic is deliberately separate from profile_record_processing.py's
control/time-profile arms. tracemalloc perturbs allocation, runtime and RSS; use
that existing tool's control arm for performance comparisons. Start tracing just
before the benchmark CLI worker and sample current traced bytes and cumulative
peak at record-load, freshness-check, context and provider-call boundaries.
These overlapping observations are not additive or exclusive phase allocation.
They cannot identify which phase allocated a transient object between samples.
Weak references count live snapshots and their documents without extending their
lifetimes; no garbage collection is forced. Read/parse/validate counts apply to
record loading on the main thread. Snapshot references and tracing machinery add
overhead. No filenames, document contents, credentials or tracebacks are exported.

Fixture creation/copying, interrupted-resume preparation and parent verification
are outside tracing. The worker includes CLI startup within already imported
modules, JSON output, persisted-session/token verification and metadata writing. Allocation-report assembly/write after tracing is excluded.
Resume continues two persisted roles after controlled mock interruption; it is
not an OS-crash benchmark. No real API or training is performed. The CLI semantics,
latest memory, role/budget/approval and input-preservation checks are reused from
the research-scale benchmark. Allocation counts and peaks are diagnostic evidence,
not a process RSS limit or a statistical performance claim.
"""
import argparse
from contextlib import ExitStack
import functools
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import shutil
import subprocess
import sys
import threading
import time
import tracemalloc
import weakref

HERE = Path(__file__).resolve()
BENCH = runpy.run_path(str(HERE.with_name('benchmark_research_scale.py')))


class MemoryTrace:
    """Numeric phase observations; weak references do not keep records alive."""
    def __init__(self):
        self.owner = threading.get_ident()
        self.snapshots = []
        self.events = []
        self.counts = dict(record_loads=0, records_read=0, records_parse=0, records_validate=0)
        self.load_depth = 0

    def observe(self, phase):
        if threading.get_ident() != self.owner:
            return
        live = [reference for reference in self.snapshots if reference() is not None]
        self.snapshots = live
        documents = sum(sum(len(group) for group in reference().records.values()) for reference in live)
        current, peak = tracemalloc.get_traced_memory()
        self.events.append(dict(phase=phase, current_traced_bytes=current,
                                cumulative_peak_traced_bytes=peak,
                                live_snapshots=len(live), live_record_documents=documents))

    def wrap(self, function, phase, *, record_load=False):
        @functools.wraps(function)
        def measured(*args, **kwargs):
            if threading.get_ident() != self.owner:
                return function(*args, **kwargs)
            self.observe(phase + '_begin')
            if record_load:
                self.counts['record_loads'] += 1
                self.load_depth += 1
            try:
                result = function(*args, **kwargs)
                if record_load:
                    self.snapshots.append(weakref.ref(result))
                return result
            finally:
                if record_load:
                    self.load_depth -= 1
                self.observe(phase + '_end')
        return measured

    def count(self, function, category):
        @functools.wraps(function)
        def counted(*args, **kwargs):
            if threading.get_ident() == self.owner and self.load_depth:
                self.counts[category] += 1
            return function(*args, **kwargs)
        return counted


def worker(source, root, operation, metadata):
    sys.path.insert(0, str(source))
    from unittest.mock import patch
    from zar import cli, records, research, validation
    trace = MemoryTrace()
    with ExitStack() as patches:
        loader = trace.wrap(records.load_records, 'load', record_load=True)
        for module in (records, cli):
            patches.enter_context(patch.object(module, 'load_records', loader))
        patches.enter_context(patch.object(Path, 'read_text', trace.count(Path.read_text, 'records_read')))
        patches.enter_context(patch.object(records, 'loads', trace.count(records.loads, 'records_parse')))
        patches.enter_context(patch.object(validation, 'validate_document',
                                           trace.count(validation.validate_document, 'records_validate')))
        for name, phase in (('assert_fresh', 'freshness'), ('context', 'context'), ('call_api', 'provider')):
            patches.enter_context(patch.object(research, name, trace.wrap(getattr(research, name), phase)))
        tracemalloc.start()
        try:
            trace.observe('worker_begin')
            BENCH['worker'](source, root, operation, metadata)
            trace.observe('worker_end')
        finally:
            tracemalloc.stop()
    result = json.loads(metadata.read_text(encoding='utf-8'))
    result['allocation_trace'] = dict(events=trace.events, counts=trace.counts,
                                     max_live_snapshots=max(e['live_snapshots'] for e in trace.events),
                                     peak_traced_bytes=max(e['cumulative_peak_traced_bytes'] for e in trace.events))
    metadata.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


def run(source, root, operation, output, timeout):
    metadata = output.with_suffix('.metrics.json')
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1')
    started = time.perf_counter()
    result = subprocess.run([sys.executable, str(HERE), '--source', str(source), '--worker', operation,
                             '--root', str(root), '--metadata', str(metadata)], cwd=source, env=env,
                            capture_output=True, timeout=timeout)
    elapsed = time.perf_counter() - started
    output.with_suffix('.stdout').write_bytes(result.stdout)
    output.with_suffix('.stderr').write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError('Allocation worker failed; inspect private output ' + output.name)
    sample = json.loads(metadata.read_text(encoding='utf-8'))
    sample.update(wall_seconds=elapsed, stdout_bytes=len(result.stdout), stderr_bytes=len(result.stderr))
    sample['cli_results'] = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert all(item['ok'] for item in sample['cli_results'])
    return sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE.parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--records', type=int, nargs='+', default=[10000])
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--label', default='working-tree')
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--worker', choices=['plan', 'resume'], help=argparse.SUPPRESS)
    parser.add_argument('--root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--metadata', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.source.resolve(), args.root, args.worker, args.metadata)
        return
    if not args.output or args.output.exists() or args.repeats < 1 or any(n < 1 for n in args.records):
        parser.error('New output directory and positive records/repeats required')
    if len(set(args.records)) != len(args.records):
        parser.error('Record counts must be unique')
    original = args.source.resolve()
    digest = BENCH['tree_digest'](original / 'zar', '*.py')
    measurement_paths = [HERE, HERE.with_name('benchmark_research_scale.py'), HERE.with_name('benchmark_records.py')]
    def measurement_digest():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in measurement_paths}
    measurement = measurement_digest()
    output = args.output.resolve()
    output.mkdir()
    private = output / 'private'
    private.mkdir(mode=0o700)
    source = private / 'source'
    source.mkdir()
    for directory in ('zar', 'examples', 'skills'):
        shutil.copytree(original / directory, source / directory,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    shutil.copy2(original / 'pyproject.toml', source / 'pyproject.toml')
    report = dict(measurement_version=1, label=args.label, methodology=__doc__,
                  python=platform.python_version(), platform=platform.system() + '-' + platform.machine(),
                  source_digest=digest, measurement_digest=measurement,
                  repeats=args.repeats, warmups=0, cases=[])
    previous = json.loads(args.compare.read_text()) if args.compare else None
    if previous:
        for key in ('measurement_version', 'measurement_digest', 'python', 'platform', 'repeats', 'warmups'):
            assert previous[key] == report[key], 'Comparison differs: ' + key
        assert [c['records'] for c in previous['cases']] == args.records
    for count in args.records:
        seed = private / f'records-{count}-fixture'
        lessons = BENCH['fixture'](source, seed, count, 0, private, args.timeout)
        fixture_digest = BENCH['tree_digest'](seed, '*')
        records, history = BENCH['records_digest'](seed), BENCH['history_digest'](seed)
        prior = next((c for c in previous['cases'] if c['records'] == count), None) if previous else None
        if prior:
            assert prior['fixture_digest'] == fixture_digest
        case = dict(records=count, completed_sessions=0, fixture_digest=fixture_digest, operations={})
        for operation in ('plan', 'resume'):
            samples = []
            for repeat in range(args.repeats):
                name = f'records-{count}-{operation}-{repeat}'
                root = private / name
                shutil.copytree(seed, root)
                if operation == 'resume':
                    prepared = BENCH['run'](source, root, 'prepare', private / (name + '-prepare'), args.timeout)
                    (root / 'active-session.txt').write_text(prepared['session_id'], encoding='utf-8')
                sample = run(source, root, operation, private / (name + '-measured'), args.timeout)
                BENCH['verify'](root, sample, operation, lessons, records, history)
                samples.append(sample)
                shutil.rmtree(root)
            assert len({s['semantic_sha256'] for s in samples}) == 1
            if prior:
                assert samples[0]['semantic_sha256'] == prior['operations'][operation]['trials'][0]['semantic_sha256']
            case['operations'][operation] = dict(trials=samples)
            print(f'records-{count} {operation}: allocation trace validated', flush=True)
        assert BENCH['tree_digest'](seed, '*') == fixture_digest
        report['cases'].append(case)
        BENCH['write_json'](output / f'records-{count}.json', case)
    assert measurement_digest() == measurement
    assert BENCH['tree_digest'](source / 'zar', '*.py') == digest
    assert BENCH['tree_digest'](original / 'zar', '*.py') == digest
    BENCH['write_json'](output / 'summary.json', report)


if __name__ == '__main__':
    main()
