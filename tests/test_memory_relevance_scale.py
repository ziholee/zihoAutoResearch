"""Small deterministic selector-scale checks; no provider or timing thresholds."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import benchmark_memory_relevance as bench
from zar import research, session_memory as memory
from zar.codec import loads, dumps


class MemoryRelevanceScaleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = bench.fixture(self.root, records=100, sessions=20)

    def test_older_matches_beat_newest_mismatches_and_stale(self):
        result = bench.select(self.root, self.data, {})
        bench.verify(result, self.data)
        self.assertEqual(result[1]['counts']['matched'], 6)
        self.assertEqual(result[1]['counts']['source_changed'], 1)

    def test_shared_references_hash_once_per_record_not_per_session(self):
        self.data['experiments'] = bench.CountingRecords(self.data['experiments'])
        with patch.object(memory, 'identity', wraps=memory.identity) as hashing:
            bench.verify(bench.select(self.root, self.data, {}), self.data)
        self.assertLessEqual(hashing.call_count, 4)
        self.assertLessEqual(self.data['experiments'].values_calls, 1)

    def test_cold_warm_and_uncached_results_identical_under_cache_bounds(self):
        expected = bench.select(self.root, self.data, None)
        for entries, bytes_limit in ((3, 8 * 1024 * 1024), (2048, sum(self.data['sizes'][:3])),
                                     (2048, sum(self.data['sizes'][:3]) - 1)):
            with self.subTest(entries=entries, bytes_limit=bytes_limit), \
                    patch.object(research, 'HISTORY_CACHE_MAX_ENTRIES', entries), \
                    patch.object(research, 'HISTORY_CACHE_MAX_BYTES', bytes_limit):
                cache = {}
                self.assertEqual(bench.select(self.root, self.data, cache), expected)
                self.assertEqual(bench.select(self.root, self.data, cache), expected)
                count, byte_count = bench.retained(self.data['sizes'])
                self.assertEqual(len(cache), count)
                self.assertEqual(sum(value[2] for value in cache.values()), byte_count)

    def test_same_size_same_mtime_history_edit_invalidates_cache(self):
        cache = {}
        before = bench.select(self.root, self.data, cache)
        path = self.root / '.autoresearch/sessions' / (bench.identifier(5) + '.json')
        stat = path.stat()
        document = loads(path.read_text())
        document['outputs']['memory']['lesson'] = 'n'
        raw = dumps(document).encode()
        self.assertEqual(len(raw), stat.st_size)
        path.write_bytes(raw)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        after = bench.select(self.root, self.data, cache)
        self.assertEqual(path.stat().st_mtime_ns, stat.st_mtime_ns)
        self.assertEqual(after, bench.select(self.root, self.data, None))
        self.assertNotEqual(before, after)
        self.assertEqual(after[0][0]['proposal']['lesson'], 'n')
        self.assertEqual(after[0][0]['assessment']['status'], 'hold')

    def test_all_matched_shared_pair_selects_newest_five_and_keeps_hold(self):
        root = self.root / 'all-matched'
        data = bench.fixture(root, records=100, sessions=20, memory_characters=160,
                             distribution='all-matched')
        expected = [bench.identifier(index) for index in (19, 18, 17, 16, 15)]
        data['experiments'] = bench.CountingRecords(data['experiments'])
        with patch.object(memory, 'identity', wraps=memory.identity) as hashing:
            result = bench.select(root, data, {})
        bench.verify(result, data)
        self.assertEqual([item['session_id'] for item in result[0]], expected)
        self.assertEqual(result[1]['counts']['matched'], 19)
        self.assertEqual(result[1]['counts']['source_changed'], 1)
        self.assertEqual(result[1]['counts']['mismatch'], 0)
        self.assertLessEqual(hashing.call_count, 3)
        self.assertEqual(data['experiments'].values_calls, 1)

    def test_small_measurement_separates_wall_and_allocation_passes(self):
        result = bench.measure(self.root, self.data, repeats=1)
        self.assertEqual(result['selected_count'], 5)
        self.assertEqual(len(result['cold_wall_seconds']), 1)
        self.assertEqual(len(result['warm_wall_seconds']), 1)
        self.assertGreater(result['cold_peak_traced_bytes'], 0)
        self.assertTrue(result['equivalent'])


if __name__ == '__main__':
    unittest.main()
