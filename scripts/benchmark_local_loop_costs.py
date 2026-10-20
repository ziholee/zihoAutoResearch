#!/usr/bin/env python3
"""Decompose a scripted zar ML loop; no real API or human-time measurement.

python scripts/benchmark_local_loop_costs.py --output NEW_DIRECTORY --repeats 3
All timings are observations, never pass/fail speed thresholds.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import runpy
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
UTILITY = ROOT / 'scripts' / 'benchmark_workflow_utility.py'
FIXTURE = runpy.run_path(str(UTILITY))
CATEGORIES = ('records', 'validation', 'storage', 'git', 'other')
CONFIGURATIONS = {'baseline': (False, 0.5), 'profiled': (True, 0.5), 'short_poll': (False, 0.01)}


def source_hashes():
    paths = [*sorted((ROOT / 'zar').glob('*.py')), UTILITY,
             Path(__file__).resolve(), ROOT / 'scripts' / 'profile_local_cli.py', ROOT / 'examples' / 'ml-loop.py']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def summarize(events, elapsed):
    cli = [e for e in events if e['kind'] == 'zar_cli']
    profiles = [e['profile'] for e in cli if 'profile' in e]
    parts = dict(cli=sum(e['seconds'] for e in cli),
                 external_git=sum(e['seconds'] for e in events if e['kind'] == 'git'),
                 server_shutdown=sum(e['seconds'] for e in events if e['kind'] == 'server_shutdown'))
    parts['worker_other'] = elapsed - sum(parts.values())
    result = dict(total_seconds=elapsed, partition_seconds=parts,
                  counts={kind: sum(e['kind'] == kind for e in events)
                          for kind in ('zar_cli', 'git', 'git_commit', 'approval', 'provider', 'server_shutdown')})
    if profiles:
        FIXTURE['require'](len(profiles) == len(cli), 'Partial CLI profiling')
        seconds = {key: sum(p['seconds'].get(key, 0.0) for p in profiles) for key in CATEGORIES}
        seconds['startup'] = sum(p['startup_seconds'] for p in profiles)
        # Includes wrapper profiling output, process exit, parent subprocess handling,
        # and timer bookkeeping outside wrapped calls. No claim of pure OS startup.
        seconds['launcher_exit_residual'] = parts['cli'] - sum(seconds.values())
        FIXTURE['require'](seconds['launcher_exit_residual'] >= 0, 'Negative CLI residual')
        result['cli_partition_seconds'] = seconds
        result['cli_calls'] = {key: sum(p['calls'].get(key, 0) for p in profiles) for key in CATEGORIES}
        result['startup_diagnostics_seconds'] = {
            'parent_launch_to_entry': sum(p['entry_seconds'] for p in profiles),
            'launcher_setup_and_imports': sum(p['launcher_setup_seconds'] for p in profiles)}
    FIXTURE['require'](parts['worker_other'] >= 0, 'Negative worker residual')
    return result


def benchmark(output, repeats):
    FIXTURE['require'](repeats >= 1, 'Repeats must be positive')
    output = output.absolute()
    output.mkdir(parents=False, exist_ok=False)
    hashes = source_hashes()
    trials = []
    names = list(CONFIGURATIONS)
    for index in range(repeats):
        order = names[index % len(names):] + names[:index % len(names)]
        results = {}
        for name in order:
            profile, poll = CONFIGURATIONS[name]
            destination = output / f'{index + 1}-{name}'
            started = time.perf_counter()
            for resume in (False, True):
                argv = [sys.executable, str(UTILITY), '--output', str(destination), '--worker', 'zar', '--poll-interval', str(poll)]
                if profile:
                    argv.append('--profile-cli')
                if resume:
                    argv.append('--resume')
                subprocess.run(argv, check=True, capture_output=True, text=True, timeout=180)
            elapsed = time.perf_counter() - started
            # Verification and reading raw evidence are outside measured total.
            verified = FIXTURE['verify_arm'](destination, 'zar')
            result = summarize(FIXTURE['load'](destination / 'events.json'), elapsed)
            result['verified'] = verified
            results[name] = result
        for name in names[1:]:
            FIXTURE['require'](results[name]['verified'] == results[names[0]]['verified'], 'Changed experiment result')
            FIXTURE['require'](results[name]['counts'] == results[names[0]]['counts'], 'Changed workflow counts')
        trials.append(dict(repeat=index + 1, order=order, results=results))
    FIXTURE['require'](source_hashes() == hashes, 'Source changed during measurement')
    medians = {}
    for name in names:
        rows = [t['results'][name] for t in trials]
        entry = {'total_seconds': statistics.median(r['total_seconds'] for r in rows)}
        for key in ('partition_seconds', 'cli_partition_seconds', 'startup_diagnostics_seconds'):
            if key in rows[0]:
                entry[key] = {k: statistics.median(r[key][k] for r in rows) for k in rows[0][key]}
        medians[name] = entry
    summary = dict(version=1, python=platform.python_version(), platform=platform.system(), repeats=repeats,
                   source_sha256=hashes, configurations={k: dict(profile_cli=v[0], poll_interval=v[1]) for k, v in CONFIGURATIONS.items()},
                   trials=trials, median=medians,
                   paired_deltas_seconds=[dict(repeat=t['repeat'],
                     profiling=t['results']['profiled']['total_seconds']-t['results']['baseline']['total_seconds'],
                     short_poll=t['results']['short_poll']['total_seconds']-t['results']['baseline']['total_seconds']) for t in trials],
                   limitations=[
                     'Local scripted fixture; no real LLM/API, token, quality or human-time claim.',
                     'CLI startup includes launcher imports/setup; eager instrumentation imports differ from python -m zar.',
                     'Profiled-minus-baseline includes instrumentation, launch differences and ordinary timing noise.',
                     'Record, validation, storage and internal Git times are exclusive; nested validation is removed from record loading.',
                     'Validation instruments validate_document, inspect_project, validate_response and validate_profile only; other checks remain other.',
                     'Only launcher/main-thread calls are timed; background work is included in other through waiting.',
                     'Storage measures atomic_write including fsync; locks, session reads and other work remain other.',
                     'CLI partition is nested inside workflow cli; startup diagnostics are nested inside startup. Do not add them again.',
                     'Per-sample partitions sum to total; independently computed medians need not sum.',
                     'Short poll changes mock server waiting only, not product or API latency; more wakeups may cost CPU.',
                     'Three configurations rotate order; no warmup, cache control or statistical significance claim.',
                     'Observed-boundary process restart is verified; abrupt-crash behavior is covered separately by recovery tests.'])
    FIXTURE['save'](output / 'summary.json', summary)
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    benchmark(args.output, args.repeats)


if __name__ == '__main__':
    main()
