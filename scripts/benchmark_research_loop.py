#!/usr/bin/env python3
"""Measure local five-role planning overhead with deterministic mocked model responses.

Each scale uses one warmup and three fresh worker processes/projects. Fixture
creation and imports are excluded; start and advance are timed separately. The
model returns immediately, so measurements do not predict API latency or model
quality. Call count, total UTF-8 message-content bytes (system + user), and record
snapshot load counts accompany timings. No experiment command is executed.
Compare frozen source trees with the same interpreter on an otherwise idle host.
"""
import argparse
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


def digest_tree(source):
    h = hashlib.sha256()
    for path in sorted((source / 'zar').rglob('*.py')):
        h.update(path.relative_to(source).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def worker(source, count):
    sys.path.insert(0, str(source))
    from unittest.mock import patch
    from benchmark_records import generate
    from zar import cli, records, research
    from zar.codec import dumps, loads
    with tempfile.TemporaryDirectory(prefix='zar-loop-fixture-') as temporary:
        root = Path(temporary).resolve() / 'project'
        generate(root, count, Path(__file__).resolve().parents[1] / 'examples' / 'contract-v1')
        store = root / '.autoresearch'
        project = loads((store / 'project.json').read_text())
        project['budget']['max_experiments'] = count + 10
        (store / 'project.json').write_text(dumps(project), encoding='utf-8')
        baseline_path = store / 'experiments' / 'exp-000000.json'
        baseline = loads(baseline_path.read_text())
        baseline['run_context'] = dict(scope='full', seed=42, budget_ref='synthetic')
        baseline_path.write_text(dumps(baseline), encoding='utf-8')
        (root / 'train.py').write_text('# Synthetic source; benchmark never executes this.\n', encoding='utf-8')
        calls = []
        loads_count = 0
        original_load = records.load_records

        def counted_load(*args, **kwargs):
            nonlocal loads_count
            loads_count += 1
            return original_load(*args, **kwargs)

        def respond(profile, messages):
            role = json.loads(messages[-1]['content'])['role']
            calls.append(dict(role=role, prompt_bytes=sum(len(m['content'].encode('utf-8')) for m in messages)))
            body = dict(summary='Synthetic source inspected', evidence=['train.py'], uncertainties=[])
            body.update(dict(analysis=dict(missing=[]), evaluation=dict(verdict='pass'),
                             planning=dict(hypothesis='Synthetic unchanged candidate'),
                             implementation=dict(changes=[]), review=dict(verdict='pass'))[role])
            return dict(content=dumps(body), usage=None)

        with patch.object(records, 'load_records', side_effect=counted_load), \
                patch.object(cli, 'load_records', side_effect=counted_load), \
                patch.object(research, 'chat', side_effect=respond):
            started = time.perf_counter()
            session = research.start(root, profile=dict(base_url='http://localhost:9999/v1',
                model='mock', api_key_env='ZAR_BENCHMARK_UNUSED'), goal='Inspect synthetic candidate',
                read_paths=['train.py'], command='train', metric_file='metric.json', metric_key='rmse',
                max_calls=9, session_seconds=1800, scope='full', seed=42, budget_ref='synthetic')
            start_seconds = time.perf_counter() - started
            start_loads = loads_count
            started = time.perf_counter()
            session = research.advance(root, session['id'], send=True)
            advance_seconds = time.perf_counter() - started
        assert session['state'] == 'awaiting_approval', session['state']
        assert [item['role'] for item in calls] == list(research.PRE)
        assert not (root / 'metric.json').exists()
        return dict(start_seconds=start_seconds, advance_seconds=advance_seconds,
                    total_seconds=start_seconds + advance_seconds,
                    start_record_loads=start_loads, advance_record_loads=loads_count-start_loads,
                    model_calls=len(calls), prompt_bytes=sum(item['prompt_bytes'] for item in calls),
                    roles=calls)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--scales', type=int, nargs='+', default=[100, 1000])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--label', default='working-tree')
    parser.add_argument('--worker', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    source = args.source.resolve()
    if args.worker is not None:
        print(json.dumps(worker(source, args.worker)))
        return
    if not args.output or args.output.exists():
        parser.error('--output must name a new file')
    if any(n < 1 for n in args.scales) or len(args.scales) != len(set(args.scales)):
        parser.error('--scales must contain unique positive integers')
    runtime_digest = digest_tree(source)
    report = dict(measurement_version=1, label=args.label, python=platform.python_version(),
                  platform=platform.system() + '-' + platform.machine(), runtime_sha256=runtime_digest,
                  methodology=__doc__, warmups=1, measured_trials=3, cases=[])
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONHASHSEED='0')
    for count in args.scales:
        samples = []
        for trial in range(4):
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--source', str(source),
                                     '--worker', str(count)], cwd=source, env=env,
                                    capture_output=True, text=True, timeout=300, check=True)
            sample = json.loads(result.stdout)
            if trial:
                samples.append(sample)
        case = dict(count=count, trials=samples)
        for key in ('start_seconds', 'advance_seconds', 'total_seconds'):
            case['median_' + key] = statistics.median(s[key] for s in samples)
        for key in ('model_calls', 'prompt_bytes', 'start_record_loads', 'advance_record_loads'):
            assert len({s[key] for s in samples}) == 1, f'Non-deterministic {key}'
            case[key] = samples[0][key]
        report['cases'].append(case)
        print(f"{count}: {case['median_total_seconds']:.3f}s, {case['model_calls']} calls, "
              f"{case['prompt_bytes']} prompt bytes, {case['advance_record_loads']} planning record loads", flush=True)
    assert runtime_digest == digest_tree(source), 'Source changed during benchmark'
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
