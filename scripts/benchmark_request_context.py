#!/usr/bin/env python3
"""Measure prepared request content for the mock baseline/candidate ML loop.

Run with an installed zar package or PYTHONPATH pointing at the checkout:
  python scripts/benchmark_request_context.py --output NEW_DIRECTORY

The workflow retains local execution evidence. Its summary.json contains only
byte counts, synthetic scores and source hashes, without prompts or local paths.
These are message-content bytes, not network traffic, tokens or model quality.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ROLES = ('analysis', 'evaluation', 'planning', 'implementation', 'review',
         'interpretation', 'memory')
COMPONENTS = ('instructions', 'sources', 'records', 'outputs', 'other', 'framing')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def count(value):
    require(type(value) is int and value >= 0, 'Expected an observed nonnegative integer')
    return value


def observed(counter):
    require(isinstance(counter, dict) and type(counter.get('observations')) is int
            and counter['observations'] == 1,
            'Expected exactly one measured request per role')
    return count(counter.get('value'))


def build_report(workflow):
    """Extract only validated numeric observations, never fill legacy gaps."""
    summary = read(Path(workflow) / 'summary.json')
    require(summary.get('state') == 'complete', 'ML workflow is incomplete')
    require(summary.get('execution_count') == 2
            and summary.get('resumed_without_execution') is True,
            'Expected exactly two executions with no execution on resume')
    require(all(summary.get(key) is True for key in
                ('mock_llm', 'actual_training', 'synthetic_data')),
            'Expected the actual-training, synthetic-data, mock-provider fixture')
    sessions = {}
    total = dict.fromkeys(COMPONENTS, 0)
    for mode in ('baseline', 'candidate'):
        metrics = summary['metrics'][mode]
        require(metrics['total']['attempts'] == 7
                and set(metrics['roles']) == set(ROLES),
                'Unexpected role attempts')
        rows = []
        for role in ROLES:
            bucket = metrics['roles'][role]
            require(type(bucket['attempts']) is int and bucket['attempts'] == 1,
                    'Unexpected retry or missing role')
            size = observed(bucket['input_message_bytes'])
            components = bucket.get('input_components_bytes')
            require(isinstance(components, dict) and set(components) == set(COMPONENTS),
                    'Missing input component measurements')
            values = {name: observed(components[name]) for name in COMPONENTS}
            require(sum(values.values()) == size, 'Component partition differs from message size')
            rows.append(dict(role=role, input_message_bytes=size,
                             input_components_bytes=values))
            for name, value in values.items():
                total[name] += value
        sessions[mode] = rows
    scores = {}
    for mode in ('baseline', 'candidate'):
        value = summary[mode + '_score']
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                'Invalid observed synthetic score')
        scores[mode] = value
    return dict(version=1, requests=14, execution_count=2,
                resumed_without_execution=True, scores=scores, sessions=sessions,
                total_input_message_bytes=sum(total.values()),
                total_input_components_bytes=total)


def benchmark(output):
    output = Path(output).absolute()
    output.mkdir(parents=False, exist_ok=False)
    workflow = output / 'workflow'
    example = ROOT / 'examples' / 'ml-loop.py'
    for action in ('--pause', '--resume'):
        completed = subprocess.run(
            [sys.executable, str(example), '--output', str(workflow), action],
            capture_output=True, text=True, timeout=300)
        require(completed.returncode == 0,
                f'Mock workflow {action} failed: {completed.stdout}\n{completed.stderr}')
    report = build_report(workflow)
    report['environment'] = dict(python=platform.python_version(), platform=platform.system())
    report['source_sha256'] = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ('examples/ml-loop.py', 'zar/research.py', 'zar/roles.py',
                     'zar/call_metrics.py', 'scripts/benchmark_request_context.py')
    }
    report['limitations'] = [
        'Prepared UTF-8 message content, not network bytes, tokens or monetary cost.',
        'Deterministic mock responses do not validate real-model judgment quality.',
        'Synthetic fixed workflow; no human effort or performance superiority claim.',
        'Local workflow files retain evidence; this report contains no prompts or local paths.',
    ]
    encoded = json.dumps(report, indent=2) + '\n'
    (output / 'summary.json').write_text(encoded, encoding='utf-8')
    print(encoded, end='')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    benchmark(parser.parse_args().output)


if __name__ == '__main__':
    main()
