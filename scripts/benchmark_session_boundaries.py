#!/usr/bin/env python3
"""Fresh-process mocked CLI benchmark for completed-history cache boundaries.

Entry count and normalized UTF-8 input byte axes vary independently. Large response bodies vary independently in historical non-memory outputs and
remembered proposals. The large-memory condition uses 16,000-character lessons;
other conditions retain small remembered proposals. Reuses the research-scale CLI worker and its evidence verifier. Timing
includes process startup, CLI work/output, persisted-token verification, metadata,
output capture and exit; fixture generation/copying, resume preparation and parent
verification are excluded. RSS is the child's high-water mark, not cache size.
One warmup precedes measured repetitions. No real API or training is performed.
Resume continues two persisted roles after controlled mock interruption, not an
OS crash. Functional crash recovery remains covered by the existing test suite.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import runpy
import shutil
import statistics
import subprocess
import sys

HERE = Path(__file__).resolve()
BASE = runpy.run_path(str(HERE.with_name('benchmark_research_scale.py')))
LIMIT = 8 * 1024 * 1024
CASES = {
    'entries-below': dict(sessions=2047, target_bytes=None),
    'entries-at': dict(sessions=2048, target_bytes=None),
    'entries-above': dict(sessions=2049, target_bytes=None),
    'bytes-below': dict(sessions=128, target_bytes=LIMIT - 1),
    'bytes-at': dict(sessions=128, target_bytes=LIMIT),
    'bytes-above': dict(sessions=128, target_bytes=LIMIT + 1),
    'large-responses': dict(sessions=16, target_bytes=16 * 1024 * 1024),
    'large-memory': dict(sessions=2500, target_bytes=None, memory_characters=16_000),
}


def compact(document):
    return json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def resize_history(root, target_bytes=None, memory_characters=None):
    """Distribute exact padding across bounded non-memory uncertainty fields."""
    paths = sorted((root / '.autoresearch/sessions').glob('*.json'))
    documents = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
    if memory_characters is not None:
        if not 1 <= memory_characters <= 20_000:
            raise ValueError('Memory exceeds role text contract')
        for doc in documents:
            doc['outputs']['memory']['lesson'] = 'm' * memory_characters
    if target_bytes is not None:
        for doc in documents:
            for role in BASE['ROLES'] + ['interpretation']:
                doc['outputs'][role]['uncertainties'] = ['x'] * 10
    total = sum(len(compact(doc)) for doc in documents)
    if target_bytes is not None and target_bytes < total:
        raise ValueError('Target bytes smaller than unpadded history')
    padding = (target_bytes - total) if target_bytes is not None else 0
    each, remainder = divmod(padding, len(paths)) if paths else (0, 0)
    sizes = []
    for index, (path, doc) in enumerate(zip(paths, documents)):
        remaining = each + (index < remainder)
        # Six roles, ten fields each; at most 20,000 characters per field.
        slots = [(role, slot) for role in BASE['ROLES'] + ['interpretation'] for slot in range(10)]
        per_slot, extra = divmod(remaining, len(slots))
        if remaining:
            for offset, (role, slot) in enumerate(slots):
                count = 1 + per_slot + (offset < extra)
                if count > 20_000:
                    raise ValueError('Padding exceeds role text contract')
                doc['outputs'][role]['uncertainties'][slot] = 'x' * count
        raw = compact(doc)
        if len(raw) > 2_000_000:
            raise ValueError('Fixture exceeds existing session file size limit')
        path.write_bytes(raw)
        sizes.append(len(path.read_text(encoding='utf-8').encode('utf-8')))
    assert sum(sizes) == (target_bytes if target_bytes is not None else total)
    retained = retained_bytes = 0
    for size in sizes:
        if retained < 2048 and retained_bytes + size <= LIMIT:
            retained += 1
            retained_bytes += size
    return dict(completed_sessions=len(paths), normalized_utf8_bytes=sum(sizes),
                min_session_bytes=min(sizes, default=0), max_session_bytes=max(sizes, default=0),
                expected_retained_entries=retained, expected_retained_input_bytes=retained_bytes,
                uncertainty_padding_bytes=padding)


def validate_history(source, root, timeout):
    """Use the measured source's actual role validator outside the timed CLI."""
    code = """import json, sys
from pathlib import Path
from zar.roles import validate_response
for path in Path(sys.argv[1]).glob('*.json'):
    document = json.loads(path.read_text(encoding='utf-8'))
    for role, value in document['outputs'].items():
        validate_response(role, value)
"""
    subprocess.run([sys.executable, '-c', code, str(root / '.autoresearch/sessions')],
                   cwd=source, check=True, capture_output=True, timeout=timeout)


def prepare(source, root, mode, output, timeout):
    if mode == 'plan':
        return
    prepared = BASE['run'](source, root, 'plan' if mode == 'status' else 'prepare', output, timeout)
    identifier = prepared['session_id']
    (root / 'active-session.txt').write_text(identifier, encoding='utf-8')
    if mode == 'resume':
        session = json.loads((root / '.autoresearch/sessions' / (identifier + '.json')).read_text())
        assert session['state'] == 'planning' and session['calls'] == 3
        assert list(session['outputs']) == BASE['ROLES'][:2]
        assert session['max_calls'] == 9 and session['error']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=HERE.parents[1])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', choices=list(CASES), nargs='+', default=list(CASES))
    parser.add_argument('--records', type=int, default=100)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--label', default='working-tree')
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 1 or args.records < 1 or args.timeout <= 0:
        parser.error('New output directory and positive records/repeats/timeout required')
    if len(set(args.cases)) != len(args.cases):
        parser.error('Cases must be unique')
    original = args.source.resolve()
    digest = BASE['tree_digest'](original / 'zar', '*.py')
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
                  source_digest=digest, measurement_digest=measurement, records=args.records,
                  warmups=1, repeats=args.repeats, cases=[])
    previous = json.loads(args.compare.read_text()) if args.compare else None
    if previous:
        for field in ('measurement_version', 'measurement_digest', 'python', 'platform', 'records', 'warmups', 'repeats'):
            assert previous[field] == report[field], 'Comparison mismatch: ' + field
        assert [case['key'] for case in previous['cases']] == args.cases, 'Comparison cases differ'
    for key in args.cases:
        definition = CASES[key]
        seed = private / (key + '-fixture')
        lessons = BASE['fixture'](source, seed, args.records, definition['sessions'], private, args.timeout)
        dimensions = resize_history(seed, definition['target_bytes'], definition.get('memory_characters'))
        for lesson in lessons:
            saved = json.loads((seed / '.autoresearch/sessions' / (lesson['session_id'] + '.json')).read_text())
            lesson['proposal'] = saved['outputs']['memory']
        validate_history(source, seed, args.timeout)
        if key.startswith('entries-'):
            assert dimensions['normalized_utf8_bytes'] < LIMIT, 'Entry axis also crosses byte limit'
        seed_digest = BASE['tree_digest'](seed, '*')
        records = BASE['records_digest'](seed)
        history = BASE['history_digest'](seed)
        prior = next((c for c in previous['cases'] if c['key'] == key), None) if previous else None
        if prior:
            assert prior['fixture_digest'] == seed_digest and prior['dimensions'] == dimensions
        case = dict(key=key, dimensions=dimensions, fixture_digest=seed_digest, operations={})
        for mode in ('plan', 'status', 'resume'):
            samples = []
            for repeat in range(args.repeats + 1):
                name = f'{key}-{mode}-{repeat}'
                root = private / name
                shutil.copytree(seed, root)
                prepare(source, root, mode, private / (name + '-prepare'), args.timeout)
                sample = BASE['run'](source, root, mode, private / (name + '-measured'), args.timeout)
                BASE['verify'](root, sample, mode, lessons, records, history)
                if repeat:
                    samples.append(sample)
                # No benchmark state crosses invocations; keep diagnostic stdout,
                # not duplicate potentially large per-trial fixture directories.
                shutil.rmtree(root)
            assert len({sample['semantic_sha256'] for sample in samples}) == 1
            if prior:
                assert samples[0]['semantic_sha256'] == prior['operations'][mode]['trials'][0]['semantic_sha256']
            summary = dict(trials=samples)
            for field in ('wall_seconds', 'peak_rss_bytes', 'stdout_bytes', 'record_loads', 'session_loads', 'model_calls', 'prompt_bytes'):
                values = [sample[field] for sample in samples]
                summary['median_' + field] = statistics.median(values) if all(v is not None for v in values) else None
            case['operations'][mode] = summary
            print(f'{key} {mode}: {summary["median_wall_seconds"]:.4f}s', flush=True)
        assert BASE['tree_digest'](seed, '*') == seed_digest
        report['cases'].append(case)
        BASE['write_json'](output / (key + '.json'), case)
    assert measurement_digest() == measurement, 'Measurement code changed during benchmark'
    assert BASE['tree_digest'](original / 'zar', '*.py') == digest, 'Source changed during benchmark'
    assert BASE['tree_digest'](source / 'zar', '*.py') == digest
    BASE['write_json'](output / 'summary.json', report)


if __name__ == '__main__':
    main()
