#!/usr/bin/env python3
"""Reproducible synthetic record benchmark; never executes training commands.

Uses schema-v1 examples/contract-v1 documents. One baseline is selected and kept;
all subsequent records form a deep parent chain with the same baseline. Candidate
execution statuses rotate succeeded/planned/failed/cancelled. Succeeded candidates
alternate hold/discard, with one shared tiny hashed fixture evidence file. No
corrections, reviews, submissions, memories or candidate-rationale records exist.

Each command has one untimed warmup then three independent fresh CLI processes.
Wall time includes interpreter/import/startup, CLI serialization, stdout/stderr capture
and exit (saving captured output files is excluded); fixture generation is excluded. RSS is each child's own RUSAGE_SELF
high-water mark (bytes on macOS, KiB on Linux), including the small wrapper.
No RUSAGE_CHILDREN accumulation, tracemalloc, training or Git operations are used.
Warm OS caches are expected; this is a synthetic deep-history case, not ML speed.
For matched startup costs, compare frozen source copies without __pycache__ files.
PYTHONDONTWRITEBYTECODE prevents new caches but does not disable existing caches.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time

COMMANDS = ('status', 'context', 'check', 'lineage')
WRAPPER = '''import json, resource, sys
from zar.cli import main
try:
    code = main(sys.argv[2:])
finally:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with open(sys.argv[1], 'x') as stream:
        json.dump({'peak_rss_bytes': int(rss if sys.platform == 'darwin' else rss * 1024)}, stream)
raise SystemExit(code)
'''


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, indent=2)
        stream.write('\n')


def generate(root, count, templates):
    root.mkdir()  # Refuse to replace any existing project.
    store = root / '.autoresearch'
    store.mkdir()
    for group in ('experiments', 'reviews', 'submissions', 'reports', 'memories', 'candidates'):
        (store / group).mkdir()
    (store / 'program.md').write_text('Synthetic metadata scale benchmark; no training.\n')
    evidence = b'Synthetic benchmark evidence; no training was run.\n'
    (root / 'fixture.txt').write_bytes(evidence)
    ref = dict(kind='fixture', ref='fixture.txt', locator=None, sha256=hashlib.sha256(evidence).hexdigest())
    project = json.loads((templates / 'project.json').read_text())
    project.update(id='project-scale', selected_experiment_id='exp-000000', next_action='Inspect synthetic records.')
    project['budget']['max_experiments'] = count
    write_json(store / 'project.json', project)
    baseline = json.loads((templates / 'baseline.json').read_text())
    for index in range(count):
        doc = copy.deepcopy(baseline)
        doc.update(id=f'exp-{index:06d}', review_ids=[], kind='baseline' if index == 0 else 'performance',
                   parent_id=f'exp-{index-1:06d}' if index else None,
                   baseline_id='exp-000000' if index else None)
        execution = doc['execution']
        execution.update(evidence=[ref], artifacts=[], score=1.2 - (index % 50) / 1000)
        status = 'succeeded' if index == 0 else ('succeeded', 'planned', 'failed', 'cancelled')[index % 4]
        execution['status'] = status
        decision = doc['decision']
        decision['evidence'] = [ref]
        if index:
            decision.update(status='hold' if index % 8 == 0 else 'discard', next_action='Review synthetic result.')
        if status != 'succeeded':
            doc['decision'] = None
            execution.update(score=None, evidence=[], exit_code=None, note='Synthetic ' + status)
            if status in ('planned', 'cancelled'):
                execution.update(started_at=None, finished_at=None)
            if status == 'planned':
                execution['note'] = None
            if status == 'failed':
                execution['exit_code'] = 1
        doc['decision_history'] = [dict(decided_at=doc['updated_at'], decision=copy.deepcopy(doc['decision']))] if doc['decision'] else []
        write_json(store / 'experiments' / (doc['id'] + '.json'), doc)


def signature(path, semantic=False):
    raw = path.read_bytes()
    if semantic:
        raw = json.dumps(json.loads(raw), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def trial(source, root, command, output_dir, name, timeout):
    stdout, stderr, rss = [output_dir / (name + suffix) for suffix in ('.stdout', '.stderr', '.rss.json')]
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1')
    args = [sys.executable, '-c', WRAPPER, str(rss), '--project', str(root), '--json', command]
    start = time.perf_counter()
    result = subprocess.run(args, cwd=source, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    elapsed = time.perf_counter() - start
    for path, content in ((stdout, result.stdout), (stderr, result.stderr)):
        with path.open('xb') as stream:
            stream.write(content)
    if result.returncode:
        raise RuntimeError(f'Invalid benchmark fixture / CLI failure: {stdout.read_text()[:2000]} {stderr.read_text()[:1000]}')
    metrics = dict(wall_seconds=elapsed, **json.loads(rss.read_text()), exit_code=result.returncode,
                   stdout_bytes=stdout.stat().st_size, stderr_bytes=stderr.stat().st_size,
                   stdout_sha256=signature(stdout), stderr_sha256=signature(stderr),
                   semantic_sha256=signature(stdout, True), stdout_path=str(stdout), stderr_path=str(stderr))
    return metrics


def tree_digest(root, pattern):
    manifest = {str(path.relative_to(root)): signature(path) for path in sorted(root.rglob(pattern)) if path.is_file()}
    return dict(files=len(manifest), sha256=hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--fixtures', type=Path, help='Reuse fixtures from a previous results JSON via its fixture_directory.')
    parser.add_argument('--scales', type=int, nargs='+', default=[100, 1000, 10000])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--label', default='working-tree')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--compare', type=Path, help='Earlier JSON; require identical fixture paths and semantic/output hashes.')
    args = parser.parse_args()
    if sys.platform != 'darwin' and not sys.platform.startswith('linux'):
        parser.error('Peak RSS measurement supports macOS and Linux only (resource units differ elsewhere).')
    if any(count < 1 for count in args.scales) or len(set(args.scales)) != len(args.scales):
        parser.error('--scales must contain unique positive integers')
    if args.output.exists():
        parser.error('--output already exists; choose a new file')
    source = args.source.resolve()
    fixtures = args.fixtures.resolve() if args.fixtures else Path(tempfile.mkdtemp(prefix='zar-scale-fixtures-'))
    outputs = Path(tempfile.mkdtemp(prefix='zar-scale-output-'))
    report = dict(measurement_version=2, label=args.label, source=str(source), python=sys.version, platform=platform.platform(),
                  fixture_directory=str(fixtures), output_directory=str(outputs), methodology=__doc__,
                  warmups=1, measured_trials=3, runtime_digest=tree_digest(source / 'zar', '*.py'), fixtures={}, cases=[])
    previous = json.loads(args.compare.read_text()) if args.compare else None
    for count in args.scales:
        root = fixtures / str(count)
        if not args.fixtures:
            generate(root, count, Path(__file__).resolve().parents[1] / 'examples' / 'contract-v1')
        records = list((root / '.autoresearch' / 'experiments').glob('*.json'))
        if len(records) != count:
            raise ValueError(f'Expected {count} records, found {len(records)} in {root}')
        fixture_before = tree_digest(root, '*')
        report['fixtures'][str(count)] = fixture_before
        if previous and 'fixtures' in previous:
            assert previous['fixtures'][str(count)] == fixture_before, 'Fixture content changed since previous run'
        for command in COMMANDS:
            prefix = f'{count}-{command}'
            warmup = trial(source, root, command, outputs, prefix + '-warmup', args.timeout)
            samples = [trial(source, root, command, outputs, prefix + f'-{i}', args.timeout) for i in range(3)]
            for sample in samples:
                assert sample['stdout_sha256'] == warmup['stdout_sha256'], 'Nondeterministic output'
                assert sample['stderr_sha256'] == warmup['stderr_sha256'], 'Nondeterministic stderr'
            case = dict(count=count, command=command, project=str(root), warmup=warmup, trials=samples,
                        median_wall_seconds=statistics.median(s['wall_seconds'] for s in samples),
                        median_peak_rss_bytes=statistics.median(s['peak_rss_bytes'] for s in samples),
                        stdout_bytes=samples[0]['stdout_bytes'], stderr_bytes=samples[0]['stderr_bytes'])
            if previous:
                before = next(c for c in previous['cases'] if (c['count'], c['command']) == (count, command))
                assert before['project'] == str(root), 'Comparison requires identical project paths'
                case['identical_stdout'] = before['trials'][0]['stdout_sha256'] == samples[0]['stdout_sha256']
                case['identical_stderr'] = before['trials'][0]['stderr_sha256'] == samples[0]['stderr_sha256']
                case['semantically_equal'] = before['trials'][0]['semantic_sha256'] == samples[0]['semantic_sha256']
                assert all(case[key] for key in ('identical_stdout', 'identical_stderr', 'semantically_equal')), 'Output changed'
            report['cases'].append(case)
            print(f"{count:5d} {command:7s}: {case['median_wall_seconds']:.3f}s {case['median_peak_rss_bytes']/1048576:.1f}MiB {case['stdout_bytes']}+{case['stderr_bytes']} bytes", flush=True)
        assert tree_digest(root, '*') == fixture_before, 'Read-only CLI altered fixture files'
    assert tree_digest(source / 'zar', '*.py') == report['runtime_digest'], 'Runtime changed during measurement'
    write_json(args.output, report)
    print(args.output)


if __name__ == '__main__':
    main()
