"""Exact fixture dimensions and fresh-process boundary protocol smoke checks."""
import copy
import json
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BENCH = runpy.run_path(str(ROOT / 'scripts/benchmark_session_boundaries.py'))
BASE = BENCH['BASE']


class SessionBoundaryBenchmarkTests(unittest.TestCase):
    def test_exact_bytes_and_role_contracts(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp)
            seed = private / 'seed'
            BASE['fixture'](ROOT, seed, 2, 128, private, 60)
            for target in (8 * 1024 * 1024 - 1, 8 * 1024 * 1024, 8 * 1024 * 1024 + 1):
                # Reuse a pristine seed: prior padding must not be accumulated.
                root = private / str(target)
                shutil.copytree(seed, root)
                info = BENCH['resize_history'](root, target)
                BENCH['validate_history'](ROOT, root, 60)
                self.assertEqual(info['normalized_utf8_bytes'], target)
                self.assertEqual(info['expected_retained_entries'], 127 if target > 8 * 1024 * 1024 else 128)
                self.assertLessEqual(info['expected_retained_input_bytes'], 8 * 1024 * 1024)
                self.assertLess(info['max_session_bytes'], 2_000_000)

    def test_large_response_and_memory_resume_protocol(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp)
            seed = private / 'seed'
            lessons = BASE['fixture'](ROOT, seed, 2, 6, private, 60)
            BENCH['resize_history'](seed, 6 * 1024 * 1024, memory_characters=16_000)
            BENCH['validate_history'](ROOT, seed, 60)
            for lesson in lessons:
                lesson['proposal']['lesson'] = 'm' * 16_000
            records, history = BASE['records_digest'](seed), BASE['history_digest'](seed)
            for mode in ('plan', 'status', 'resume'):
                root = private / mode
                shutil.copytree(seed, root)
                BENCH['prepare'](ROOT, root, mode, private / (mode + '-prepare'), 60)
                result = BASE['run'](ROOT, root, mode, private / (mode + '-measured'), 60)
                original = copy.deepcopy(result)
                BASE['verify'](root, result, mode, lessons, records, history)
                self.assertTrue(result['validated'])
                self.assertEqual(result['model_calls'], {'plan': 5, 'status': 0, 'resume': 3}[mode])
                self.assertEqual(result['stderr_bytes'], 0)
                if original['calls']:
                    original['calls'][0]['prior_lessons'].reverse()
                    with self.assertRaises(AssertionError):
                        BASE['verify'](root, original, mode, lessons, records, history)

    def test_padding_rejects_unsupported_sizes(self):
        with tempfile.TemporaryDirectory() as temp:
            private = Path(temp)
            seed = private / 'seed'
            BASE['fixture'](ROOT, seed, 2, 1, private, 60)
            with self.assertRaises(ValueError):
                BENCH['resize_history'](seed, 1)
            with self.assertRaises(ValueError):
                BENCH['resize_history'](seed, 2_000_000)
            with self.assertRaises(ValueError):
                BENCH['resize_history'](seed, memory_characters=20_001)


if __name__ == '__main__':
    unittest.main()
