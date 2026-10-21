#!/usr/bin/env python3
"""Development-only attribution of mocked research record processing.

The same fresh-process benchmark worker runs with and without category timers.
Its fixture preparation, interrupted-resume preparation and parent verification
are outside timing. Wall time includes process startup, imports, timer setup,
worker execution, output capture and exit. Timed worker execution includes the
benchmark's load counters, JSON output, persisted-session/token verification and
metadata write. The control disables these category timers, not the benchmark's
existing counters or verification; it is not a pure CLI timing.

Exclusive categories partition the profiled worker body on the main thread.
Read, parse and document-validation categories only apply inside load_records.
Serialization covers codec.dumps aliases in CLI, research and context modules.
SHA256 covers constructor, update and hexdigest calls; digest_other includes
UTF-8 conversion and other research.digest work, excluding nested serialization/
SHA256. Projection/identity categories exclude their nested serialization/hash.
Only per-trial category sums partition body time; component medians need not.
records_other includes enumeration, safety checks and remaining record loading.
Imports/setup/exit remain outside this partition. Instrumentation perturbs timings;
use paired control wall time for performance comparisons. No API or training runs.
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
import statistics
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
BENCH = runpy.run_path(str(HERE / 'benchmark_research_scale.py'))
CATEGORIES = ('records_read', 'records_parse', 'records_validate', 'records_other',
              'serialize', 'sha256', 'digest_other', 'projection_build',
              'snapshot_identity', 'worker_other')


class Timer:
    """Exclusive main-thread function wall time, including exceptional exits."""
    def __init__(self):
        self.owner = threading.get_ident()
        self.stack = []
        self.seconds = dict.fromkeys(CATEGORIES, 0.0)
        self.calls = dict.fromkeys(CATEGORIES, 0)
        self.outer_seconds = None

    def wrap(self, function, category):
        @functools.wraps(function)
        def measured(*args, **kwargs):
            if threading.get_ident() != self.owner:
                return function(*args, **kwargs)
            frame = [time.perf_counter(), 0.0]
            self.stack.append(frame)
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - frame[0]
                self.stack.pop()
                self.seconds[category] += elapsed - frame[1]
                self.calls[category] += 1
                if self.stack:
                    self.stack[-1][1] += elapsed
                else:
                    self.outer_seconds = elapsed
        return measured


def worker(source, root, operation, metadata, profiled):
    sys.path.insert(0, str(source))
    from unittest.mock import patch
    # Both arms import exactly these modules before entering the worker body.
    from zar import cli, codec, context, records, research, validation
    timer = Timer()
    depth = 0
    original_load = records.load_records
    original_read = Path.read_text
    original_validate = validation.validate_document
    measured_load = timer.wrap(original_load, 'records_other')
    measured_read = timer.wrap(original_read, 'records_read')
    measured_validate = timer.wrap(original_validate, 'records_validate')

    def record_load(*args, **kwargs):
        nonlocal depth
        if threading.get_ident() != timer.owner:
            return original_load(*args, **kwargs)
        depth += 1
        try:
            return measured_load(*args, **kwargs)
        finally:
            depth -= 1

    def record_read(*args, **kwargs):
        return (measured_read if depth else original_read)(*args, **kwargs)

    def record_validate(*args, **kwargs):
        return (measured_validate if depth else original_validate)(*args, **kwargs)

    class HashProxy:
        def __init__(self, value):
            self.value = value

        def update(self, value):
            return timer.wrap(self.value.update, 'sha256')(value)

        def hexdigest(self):
            return timer.wrap(self.value.hexdigest, 'sha256')()

    def sha256(*args, **kwargs):
        return HashProxy(timer.wrap(hashlib.sha256, 'sha256')(*args, **kwargs))

    with ExitStack() as patches:
        if profiled:
            for module in (records, cli):
                patches.enter_context(patch.object(module, 'load_records', record_load))
            patches.enter_context(patch.object(Path, 'read_text', record_read))
            patches.enter_context(patch.object(records, 'loads', timer.wrap(records.loads, 'records_parse')))
            patches.enter_context(patch.object(validation, 'validate_document', record_validate))
            serializer = timer.wrap(codec.dumps, 'serialize')
            for module in (codec, cli, research, context):
                patches.enter_context(patch.object(module, 'dumps', serializer))
            patches.enter_context(patch.object(research, 'digest', timer.wrap(research.digest, 'digest_other')))
            projection = timer.wrap(context.build_context, 'projection_build')
            for module in (context, cli):
                patches.enter_context(patch.object(module, 'build_context', projection))
            patches.enter_context(patch.object(context, 'snapshot_identity',
                                               timer.wrap(context.snapshot_identity, 'snapshot_identity')))
            # Replace selected module references, not process-wide hashlib.
            for module in (research, context):
                patches.enter_context(patch.object(module, 'hashlib', SimpleNamespace(sha256=sha256)))
            timer.wrap(BENCH['worker'], 'worker_other')(source, root, operation, metadata)
        else:
            BENCH['worker'](source, root, operation, metadata)
    result = json.loads(metadata.read_text(encoding='utf-8'))
    result['profile'] = (dict(body_seconds=timer.outer_seconds,
                              seconds=timer.seconds, calls=timer.calls) if profiled else None)
    if profiled:
        assert not timer.stack
        assert abs(sum(timer.seconds.values()) - timer.outer_seconds) < 1e-6
    metadata.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


def run(source, root, operation, output, timeout, profiled):
    metadata = output.with_suffix('.metrics.json')
    command = [sys.executable, str(Path(__file__).resolve()), '--source', str(source),
               '--worker', operation, '--root', str(root), '--metadata', str(metadata)]
    if profiled:
        command.append('--profiled')
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1')
    started = time.perf_counter()
    result = subprocess.run(command, cwd=source, env=env, capture_output=True, timeout=timeout)
    elapsed = time.perf_counter() - started
    output.with_suffix('.stdout').write_bytes(result.stdout)
    output.with_suffix('.stderr').write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError('Worker failed; inspect private output ' + output.name)
    sample = json.loads(metadata.read_text(encoding='utf-8'))
    sample.update(wall_seconds=elapsed, stdout_bytes=len(result.stdout), stderr_bytes=len(result.stderr))
    sample['cli_results'] = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert all(item['ok'] for item in sample['cli_results'])
    if profiled:
        sample['profile']['outside_body_seconds'] = elapsed - sample['profile']['body_seconds']
        assert sample['profile']['outside_body_seconds'] >= 0
    return sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE.parent)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--records', nargs='+', type=int, default=[1000, 10000])
    parser.add_argument('--operations', nargs='+', choices=['plan', 'resume'], default=['plan', 'resume'])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--label', default='working-tree')
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--worker', choices=['plan', 'resume'], help=argparse.SUPPRESS)
    parser.add_argument('--root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--metadata', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--profiled', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.source.resolve(), args.root, args.worker, args.metadata, args.profiled)
        return
    if not args.output or args.output.exists():
        parser.error('--output must be a new directory')
    if args.repeats < 1 or any(n < 1 for n in args.records):
        parser.error('Positive record counts and repeats required')
    if len(set(args.records)) != len(args.records) or len(set(args.operations)) != len(args.operations):
        parser.error('Record counts and operations must be unique')
    original = args.source.resolve()
    original_digest = BENCH['tree_digest'](original / 'zar', '*.py')
    measurement_paths = [HERE / name for name in (
        'profile_record_processing.py', 'benchmark_research_scale.py', 'benchmark_records.py')]
    measurement_digest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in measurement_paths}
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
                  source_digest=original_digest, measurement_digest=measurement_digest,
                  repeats=args.repeats, warmup_pairs=1, cases=[])
    previous = json.loads(args.compare.read_text()) if args.compare else None
    if previous:
        assert previous['measurement_digest'] == measurement_digest
        assert previous['python'] == report['python'] and previous['platform'] == report['platform']
    for count in args.records:
        seed = private / f'records-{count}-fixture'
        lessons = BENCH['fixture'](source, seed, count, 0, private, args.timeout)
        fixture_digest = BENCH['tree_digest'](seed, '*')
        records_before, history_before = BENCH['records_digest'](seed), BENCH['history_digest'](seed)
        case = dict(records=count, completed_sessions=0, fixture_digest=fixture_digest, operations={})
        prior = next(c for c in previous['cases'] if c['records'] == count) if previous else None
        if prior:
            assert prior['fixture_digest'] == fixture_digest
        for operation in args.operations:
            samples = dict(control=[], profiled=[])
            order = []
            for repetition in range(args.repeats + 1):
                arms = ['control', 'profiled'] if repetition % 2 else ['profiled', 'control']
                if repetition:
                    order.append(arms)
                for arm in arms:
                    name = f'records-{count}-{operation}-{repetition}-{arm}'
                    root = private / name
                    shutil.copytree(seed, root)
                    if operation == 'resume':
                        prepared = BENCH['run'](source, root, 'prepare', private / (name + '-prepare'), args.timeout)
                        (root / 'active-session.txt').write_text(prepared['session_id'])
                    sample = run(source, root, operation, private / (name + '-measured'), args.timeout, arm == 'profiled')
                    BENCH['verify'](root, sample, operation, lessons, records_before, history_before)
                    if repetition:
                        samples[arm].append(sample)
            semantics = {s['semantic_sha256'] for arm in samples.values() for s in arm}
            assert len(semantics) == 1, 'Profile/control semantics differ'
            if prior:
                assert semantics == {s['semantic_sha256'] for arm in prior['operations'][operation]['trials'].values() for s in arm}
            summary = dict(order=order, trials=samples, medians={})
            for arm, trials in samples.items():
                row = {}
                for field in ('wall_seconds', 'peak_rss_bytes', 'stdout_bytes', 'record_loads', 'session_loads', 'model_calls', 'prompt_bytes'):
                    values = [s[field] for s in trials]
                    row[field] = statistics.median(values) if all(v is not None for v in values) else None
                if arm == 'profiled':
                    row['profile'] = dict(
                        body_seconds=statistics.median(s['profile']['body_seconds'] for s in trials),
                        seconds={k: statistics.median(s['profile']['seconds'][k] for s in trials) for k in CATEGORIES},
                        calls={k: statistics.median(s['profile']['calls'][k] for s in trials) for k in CATEGORIES})
                summary['medians'][arm] = row
            case['operations'][operation] = summary
            print(f"records-{count} {operation}: control {summary['medians']['control']['wall_seconds']:.4f}s; profiled {summary['medians']['profiled']['wall_seconds']:.4f}s", flush=True)
        assert BENCH['tree_digest'](seed, '*') == fixture_digest
        report['cases'].append(case)
        BENCH['write_json'](output / f'records-{count}.json', case)
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in measurement_paths} == measurement_digest
    assert BENCH['tree_digest'](original / 'zar', '*.py') == original_digest
    assert BENCH['tree_digest'](source / 'zar', '*.py') == original_digest
    BENCH['write_json'](output / 'summary.json', report)


if __name__ == '__main__':
    main()
