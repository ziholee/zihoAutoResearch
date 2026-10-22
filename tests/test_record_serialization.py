"""Small isolated fixture validates the developer serialization measurement path."""
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/profile_record_serialization.py'


class RecordSerializationTests(unittest.TestCase):
    def test_modes_compare_actual_bytes_and_separate_allocations(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'report'
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
                '--before', str(ROOT), '--after', str(ROOT), '--output', str(output),
                '--records', '2', '--repeats', '1'], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            case = report['cases'][0]
            self.assertTrue(case['byte_equality_verified'])
            self.assertEqual(set(case['modes']), {'control', 'scalar-profile', 'allocation'})
            for mode, data in case['modes'].items():
                for label, trials in data['trials'].items():
                    self.assertEqual(len(trials), 1)
                    trial = trials[0]
                    self.assertTrue(trial['validated'])
                    self.assertEqual(trial['sha256'], case['sha256'])
                    self.assertEqual(trial['serialized_bytes'], case['serialized_bytes'])
                    self.assertEqual(trial['experiment_count'], 2)
                    self.assertGreater(trial['seconds']['total'], 0)
                    self.assertEqual(trial['allocation'] is not None, mode == 'allocation')
                    self.assertEqual(trial['scalar_profile'] is not None, mode == 'scalar-profile')
                    if mode == 'scalar-profile':
                        self.assertGreater(trial['scalar_profile']['calls'], 0)
                        self.assertGreaterEqual(trial['scalar_profile']['traversal_validation_assembly_seconds'], 0)
                    if mode == 'allocation':
                        self.assertEqual([e['phase'] for e in trial['allocation']['events']],
                            ['begin', 'serialized', 'utf8_encoded', 'text_released', 'hashed'])
                        self.assertGreater(trial['allocation']['peak_traced_bytes'], 0)
            self.assertEqual(report['source_digest']['before'], report['source_digest']['after'])

    def test_rejects_nonpositive_counts_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'report'
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
                '--before', str(ROOT), '--after', str(ROOT), '--output', str(output),
                '--records', '0'], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output.exists())

    def test_rejects_changed_canonical_bytes_even_when_json_is_equivalent(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'changed'; source.mkdir()
            for name in ('zar', 'examples', 'skills'):
                shutil.copytree(ROOT / name, source / name,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copy2(ROOT / 'pyproject.toml', source / 'pyproject.toml')
            codec = source / 'zar/codec.py'
            codec.write_text(codec.read_text(encoding='utf-8') +
                "\n_original_dumps = dumps\ndef dumps(value, *, ensure_ascii=False):\n"
                "    return _original_dumps(value, ensure_ascii=ensure_ascii) + ' '\n", encoding='utf-8')
            output = Path(temp) / 'report'
            result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
                '--before', str(ROOT), '--after', str(source), '--output', str(output),
                '--records', '2', '--repeats', '1'], capture_output=True, text=True, timeout=120)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Canonical serialization bytes changed', result.stderr)
            self.assertFalse((output / 'summary.json').exists())
