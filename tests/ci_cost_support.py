"""Opt-in numeric CI diagnostics; never copy fixture artifacts or model content."""
import hashlib
import json
import math
import os
from pathlib import Path
import platform

ROOT = Path(__file__).resolve().parents[1]
KINDS = ('zar_cli', 'git', 'training', 'server_shutdown', 'provider', 'approval', 'git_commit')
PARTS = ('cli', 'external_git', 'server_shutdown', 'worker_other')
CLI_PARTS = ('records', 'validation', 'storage', 'git', 'other', 'startup', 'launcher_exit_residual')
STARTUP = ('parent_launch_to_entry', 'launcher_setup_and_imports')
NAMES = ('baseline', 'profiled', 'short_poll')


def numbers(value, names):
    return {key: value[key] for key in names if key in value
            and isinstance(value[key], (int, float)) and not isinstance(value[key], bool)
            and math.isfinite(value[key])}


def metadata():
    paths = [*sorted((ROOT / 'zar').glob('*.py')),
             ROOT / 'scripts/benchmark_workflow_utility.py',
             ROOT / 'scripts/benchmark_local_loop_costs.py',
             ROOT / 'scripts/profile_local_cli.py', ROOT / 'examples/ml-loop.py',
             Path(__file__).resolve(), ROOT / 'tests/test_workflow_utility.py',
             ROOT / 'tests/test_local_loop_costs.py']
    return dict(version=1, python=platform.python_version(), platform=platform.system(),
                source_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in paths})


def write(name, report):
    destination = Path(os.environ['ZAR_CI_COST_DIR'])
    destination.mkdir(parents=True, exist_ok=True)
    (destination / name).write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def utility_partition(events, total):
    totals = {kind: sum(e['seconds'] for e in events if e['kind'] == kind) for kind in KINDS}
    parts = {kind: totals[kind] for kind in ('zar_cli', 'git', 'training', 'server_shutdown')}
    parts['other'] = total - sum(parts.values())
    if parts['other'] < 0:
        raise ValueError('Negative workflow timing residual')
    # Provider request times and milestone times overlap subprocess intervals.
    return dict(partition_seconds=parts,
                event_seconds=totals,
                event_counts={kind: sum(e['kind'] == kind for e in events) for kind in KINDS})


def write_utility_costs(output, summary, test_elapsed_seconds):
    if not os.environ.get('ZAR_CI_COST_DIR'):
        return
    report = metadata()
    report['trials'] = []
    for trial in summary['trials']:
        number = trial['repeat']
        arms = {}
        for arm in ('direct', 'zar'):
            destination = output / ('trial-' + str(number)) / arm
            events = json.loads((destination / 'events.json').read_text(encoding='utf-8'))
            seconds = trial['arms'][arm]['seconds']
            row = utility_partition(events, seconds['total'])
            row['total_seconds'] = seconds['total']
            row['setup_other_seconds'] = seconds['setup'] - sum(
                e['seconds'] for e in events if e.get('phase') == 'setup'
                and e['kind'] in ('zar_cli', 'git', 'training'))
            if row['setup_other_seconds'] < 0:
                raise ValueError('Negative setup timing residual')
            row['phase_diagnostics_seconds'] = numbers(seconds, ('setup', 'baseline', 'candidate', 'pause', 'resume'))
            arms[arm] = row
        report['trials'].append(dict(repeat=number, arms=arms))
    report['test_elapsed_seconds'] = test_elapsed_seconds
    report['verification_and_test_overhead_seconds'] = test_elapsed_seconds - sum(
        row['total_seconds'] for trial in report['trials'] for row in trial['arms'].values())
    report['limitations'] = [
        'Existing test fixture only; no extra workflow execution or real API.',
        'Phases and setup_other_seconds overlap subprocess partitions and must not be added again.',
        'Setup other excludes measured child calls; includes server start, dataset/files preparation and bookkeeping.',
        'Provider and milestone event timings overlap subprocess intervals.',
        'Other includes worker startup, fixture preparation, persistence, and unclassified work.',
        'Post-workflow evidence verification is outside the reported worker total.',
        'Test overhead includes evidence verification, assertions, benchmark orchestration and setup; not pure verifier time.']
    write('workflow-utility.json', report)


def local_row(row):
    result = numbers(row, ('total_seconds',))
    for field, names in (('partition_seconds', PARTS), ('cli_partition_seconds', CLI_PARTS),
                         ('startup_diagnostics_seconds', STARTUP), ('cli_calls', CLI_PARTS),
                         ('counts', KINDS)):
        if field in row:
            result[field] = numbers(row[field], names)
    return result


def write_local_costs(summary, test_elapsed_seconds):
    if not os.environ.get('ZAR_CI_COST_DIR'):
        return
    report = metadata()
    report['configurations'] = {name: dict(
        profile_cli=bool(summary['configurations'][name]['profile_cli']),
        **numbers(summary['configurations'][name], ('poll_interval',))) for name in NAMES}
    report['trials'] = [dict(repeat=trial['repeat'],
        results={name: local_row(trial['results'][name]) for name in NAMES})
        for trial in summary['trials']]
    report['median'] = {name: local_row(summary['median'][name]) for name in NAMES}
    report['paired_deltas_seconds'] = [numbers(row, ('repeat', 'profiling', 'short_poll'))
                                      for row in summary['paired_deltas_seconds']]
    report['test_elapsed_seconds'] = test_elapsed_seconds
    report['verification_and_test_overhead_seconds'] = test_elapsed_seconds - sum(
        row['total_seconds'] for trial in report['trials'] for row in trial['results'].values())
    report['limitations'] = [
        'Existing test fixture only; no extra workflow execution or real API.',
        'CLI partition and startup diagnostics are nested; do not add them to workflow totals.',
        'Other includes worker startup, fixture preparation, persistence, and unclassified work.',
        'Medians of components need not sum to median total.',
        'Post-workflow evidence verification is outside the reported worker total.',
        'Test overhead includes evidence verification, assertions, benchmark orchestration and setup; not pure verifier time.']
    write('local-loop-costs.json', report)
