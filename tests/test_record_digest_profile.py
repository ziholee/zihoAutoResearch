"""Actual digest inputs must match even when one source hashes in chunks."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/profile_record_digest.py'


def source_copy(destination):
    destination.mkdir()
    for name in ('zar', 'examples', 'skills'):
        shutil.copytree(ROOT / name, destination / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(ROOT / 'pyproject.toml', destination / 'pyproject.toml')
    return destination / 'zar/research.py'


def run(before, after, output, count='2'):
    return subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
        '--before', str(before), '--after', str(after), '--output', str(output),
        '--records', count, '--repeats', '1'], capture_output=True, text=True, timeout=120)


class RecordDigestProfileTests(unittest.TestCase):
    def test_fallback_and_chunked_helper_compare_bytes_and_separate_allocations(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            before = temp / 'before'
            path = source_copy(before)
            # Hide the public helper from the profiler while preserving internal
            # fixture-start references introduced when the product adopted it.
            path.write_text(path.read_text(encoding='utf-8').replace(
                'records_digest', 'fixture_records_digest'), encoding='utf-8')
            after = temp / 'after'
            path = source_copy(after)
            path.write_text(path.read_text(encoding='utf-8') +
                "\ndef records_digest(value):\n"
                "    data = dumps(value).encode('utf-8')\n"
                "    result = hashlib.sha256(data[:11])\n"
                "    for start in range(11, len(data), 11):\n"
                "        result.update(data[start:start + 11])\n"
                "    return result.hexdigest()\n", encoding='utf-8')
            output = temp / 'report'
            result = run(before, after, output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            case = report['cases'][0]
            self.assertTrue(case['byte_equality_verified'])
            self.assertEqual(set(case['modes']), {'control', 'allocation'})
            for mode, data in case['modes'].items():
                self.assertEqual(data['order'], [['before', 'after']])
                for label, trials in data['trials'].items():
                    self.assertEqual(len(trials), 1)
                    trial = trials[0]
                    self.assertTrue(trial['validated'])
                    self.assertEqual(trial['sha256'], case['sha256'])
                    self.assertEqual(trial['serialized_bytes'], case['serialized_bytes'])
                    self.assertEqual(trial['experiment_count'], 2)
                    self.assertGreater(trial['seconds'], 0)
                    self.assertEqual(trial['allocation'] is not None, mode == 'allocation')
                    if mode == 'allocation':
                        self.assertGreater(trial['allocation']['peak_traced_bytes'], 0)
                    if label == 'before':
                        self.assertEqual(trial['chunks'], 1)
                    else:
                        self.assertGreater(trial['chunks'], 1)
                        self.assertEqual(trial['max_chunk_bytes'], 11)

    def test_rejects_changed_hash_input_even_when_json_is_equivalent(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            source = temp / 'changed'
            path = source_copy(source)
            path.write_text(path.read_text(encoding='utf-8') +
                "\ndef records_digest(value):\n"
                "    return hashlib.sha256(dumps(value).encode('utf-8') + b' ').hexdigest()\n",
                encoding='utf-8')
            output = temp / 'report'
            result = run(ROOT, source, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Canonical digest input bytes changed', result.stderr)
            self.assertFalse((output / 'summary.json').exists())

    def test_rejects_invalid_counts_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'report'
            result = run(ROOT, ROOT, output, '0')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())
