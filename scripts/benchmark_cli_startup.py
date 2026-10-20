#!/usr/bin/env python3
"""Fresh-process CLI startup attribution and real python -m zar controls.

python scripts/benchmark_cli_startup.py --source . --output NEW_FILE --repeats 7
No model connection or experiment execution is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = Path(__file__).resolve().with_name('profile_cli_startup.py')
CASES = {
    'top_help': ['--help'],
    'status': ['status', '--json'],
    'research_help': ['research', '--help'],
    'research_status_missing': ['research', 'status', 'session-' + '0' * 32, '--json'],
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_hashes(source):
    return {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((source / 'zar').glob('*.py'))}


def profile_partition(profile, elapsed):
    parts = dict(profile['partition_seconds'])
    parts['exit_residual'] = elapsed - sum(parts.values())
    require(all(value >= 0 for value in parts.values()), 'Negative timing partition')
    return parts


def benchmark(source, output, repeats, bytecode='warm'):
    source, output = source.resolve(), output.absolute()
    require(repeats >= 1, 'Repeats must be positive')
    require(not output.exists(), 'Output must be a new file')
    require((source / 'zar' / '__main__.py').is_file(), 'Source must contain the zar package')
    hashes = source_hashes(source)
    trials = []
    with tempfile.TemporaryDirectory(prefix='zar-startup-') as temporary:
        directory = Path(temporary)
        # Archive checkouts often have no bytecode, while a working checkout does.
        # Match both sources by importing identical source content from a fresh
        # copy without bytecode. OS source-file caching is still uncontrolled.
        runtime = directory / 'runtime'
        shutil.copytree(source / 'zar', runtime / 'zar',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        env = dict(os.environ, PYTHONPATH=str(runtime), PYTHONHASHSEED='0', PYTHONUTF8='1')
        env.pop('PYTHONPYCACHEPREFIX', None)
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        if bytecode == 'disabled':
            env['PYTHONDONTWRITEBYTECODE'] = '1'
        project = directory / 'project'
        project.mkdir()
        init = subprocess.run(
            [sys.executable, '-m', 'zar', 'init', '--project', str(project), '--json'],
            cwd=runtime, env=env, capture_output=True, text=True, timeout=30)
        require(init.returncode == 0, 'Fixture initialization failed: ' + init.stderr)
        if bytecode == 'warm':
            for name, arguments in CASES.items():
                warmup = subprocess.run(
                    [sys.executable, '-m', 'zar', *arguments, '--project', str(project)],
                    cwd=runtime, env=env, capture_output=True, timeout=30)
                require(warmup.returncode == (3 if name == 'research_status_missing' else 0),
                        'Bytecode warmup failed')
        for index in range(repeats):
            names = list(CASES)
            names = names[index % len(names):] + names[:index % len(names)]
            rows = {}
            for name in names:
                order = ['control', 'profiled'] if index % 2 == 0 else ['profiled', 'control']
                results, streams = {}, {}
                for mode in order:
                    arguments = [*CASES[name], '--project', str(project)]
                    child_env = dict(env)
                    profile_path = directory / 'profile.json'
                    if mode == 'control':
                        argv = [sys.executable, '-m', 'zar', *arguments]
                    else:
                        bootstrap = (
                            'import time; entry=time.perf_counter(); import runpy; '
                            'runpy.run_path(' + repr(str(LAUNCHER)) + ', run_name="__main__", '
                            'init_globals={"BENCH_ENTRY":entry})')
                        argv = [sys.executable, '-c', bootstrap, *arguments]
                        child_env['ZAR_STARTUP_PROFILE'] = str(profile_path)
                    started = time.perf_counter()
                    if mode == 'profiled':
                        child_env['ZAR_STARTUP_LAUNCH'] = str(started)
                    proc = subprocess.run(argv, cwd=runtime, env=child_env,
                                          capture_output=True, timeout=30)
                    elapsed = time.perf_counter() - started
                    expected_code = 3 if name == 'research_status_missing' else 0
                    require(proc.returncode == expected_code,
                            f'{name}/{mode} unexpected exit: ' + proc.stderr.decode(errors='replace'))
                    streams[mode] = (proc.stdout, proc.stderr, proc.returncode)
                    result = {'total_seconds': elapsed, 'returncode': proc.returncode}
                    if mode == 'profiled':
                        profile = json.loads(profile_path.read_text(encoding='utf-8'))
                        result.update(profile)
                        result['partition_seconds'] = profile_partition(profile, elapsed)
                    results[mode] = result
                require(streams['control'] == streams['profiled'], 'Profiling changed CLI output')
                rows[name] = {
                    'order': order, 'results': results, 'outputs_equal': True,
                    'stdout_bytes': len(streams['control'][0]),
                    'profiled_minus_control_seconds': results['profiled']['total_seconds'] - results['control']['total_seconds'],
                }
            trials.append({'repeat': index + 1, 'case_order': names, 'cases': rows})
    require(source_hashes(source) == hashes, 'Runtime sources changed during measurement')
    median = {}
    for name in CASES:
        rows = [t['cases'][name] for t in trials]
        median[name] = {
            'control_seconds': statistics.median(r['results']['control']['total_seconds'] for r in rows),
            'profiled_seconds': statistics.median(r['results']['profiled']['total_seconds'] for r in rows),
            'paired_delta_seconds': statistics.median(r['profiled_minus_control_seconds'] for r in rows),
            'partition_seconds': {
                key: statistics.median(r['results']['profiled']['partition_seconds'][key] for r in rows)
                for key in rows[0]['results']['profiled']['partition_seconds']},
        }
    report = {
        'version': 1, 'python': platform.python_version(), 'platform': platform.system(),
        'repeats': repeats, 'bytecode': bytecode, 'source_sha256': hashes,
        'measurement_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__).resolve(), LAUNCHER)},
        'trials': trials, 'median': median,
        'limitations': [
            'Source starts without pyc. Warm mode runs each control case once before timing; disabled mode forbids bytecode writes. OS caches are not cold or cleared.',
            'Python-to-entry includes parent subprocess launch, interpreter startup and importing time; not pure interpreter CPU time.',
            'Instrumentation prepare includes runpy and profiler loading/setup; import-hook bookkeeping remains inside measured phases.',
            'CLI import is inclusive; command/body import are outermost __import__ calls, including cached lookups.',
            'Command initialization is cli.parse wall time minus its imports, including argument parsing and help printing.',
            'Root import diagnostics are nested within their phase, never extra partition terms.',
            'Profiled-minus-control includes launch/import-order differences and timing noise, not isolated profiling overhead.',
            'Each sample partitions profiled wall time; independently computed medians need not sum.',
            'Fixture initialization is excluded. Output equality checks run after timing.',
            'No model calls, learning, approval changes or recovery test; full workflow regressions are separate.',
            'Missing-session research status exercises dispatch imports and expected exit 3; it does not benchmark a valid session.',
            'Source content is copied from the selected checkout, not the installed distribution; no speed superiority gate.',
        ],
    }
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--bytecode', choices=('warm', 'disabled'), default='warm')
    args = parser.parse_args()
    benchmark(args.source, args.output, args.repeats, args.bytecode)


if __name__ == '__main__':
    main()
