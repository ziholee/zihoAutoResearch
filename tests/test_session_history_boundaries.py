"""Production-size cache limits preserve selection and content freshness."""
import os
from pathlib import Path
import tempfile
import unittest
import weakref
from unittest.mock import patch

from zar import research
from zar.codec import dumps


class HistoryBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.directory = self.root / '.autoresearch/sessions'
        self.directory.mkdir(parents=True)
        self.active = {'id': 'session-' + 'f' * 32}

    def write(self, index, size=None):
        doc = dict(id=f'session-{index:032x}', experiment_id=f'exp-{index}',
                   created_at=f'{index:08d}', state='complete',
                   outputs={'analysis': {'summary': ''}, 'memory': {'lesson': 'before'}})
        text = dumps(doc)
        if size is not None:
            doc['outputs']['analysis']['summary'] = 'x' * (size - len(text.encode()))
            text = dumps(doc)
            self.assertEqual(len(text.encode()), size)
        path = self.directory / (doc['id'] + '.json')
        path.write_text(text, encoding='utf-8')
        return path

    def select(self, cache):
        return research._prior_lessons(self.root, self.active, cache)

    def assert_changed(self, path, cache):
        stat = path.stat()
        text = path.read_text(encoding='utf-8')
        path.write_text(text.replace('before', 'after!'), encoding='utf-8')
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(path.stat().st_size, stat.st_size)
        selected = self.select(cache)
        self.assertEqual(selected[-1]['proposal']['lesson'], 'after!')
        path.write_text('{', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.select(cache)
        path.unlink()
        self.assertNotIn(path.stem, [x['session_id'] for x in self.select(cache)])

    def test_real_entry_limit_and_uncached_newest_change(self):
        for index in range(2047):
            self.write(index)
        cache = {}
        for count in (2047, 2048, 2049):
            if count > 2047:
                newest = self.write(count - 1)
            self.select(cache)
            with patch.object(research, 'loads', wraps=research.loads) as parse:
                selected = self.select(cache)
            self.assertEqual(len(cache), min(count, 2048))
            self.assertEqual(parse.call_count, max(0, count - 2048))
            self.assertEqual([x['experiment_id'] for x in selected],
                             [f'exp-{i}' for i in range(count - 5, count)])
        self.assertNotIn(newest.stem, cache)
        self.assert_changed(newest, cache)

    def test_real_byte_limit_and_large_uncached_newest_change(self):
        limit = 8 * 1024 * 1024
        size = limit // 8
        for index in range(7):
            self.write(index, size)
        for delta in (-1, 0, 1):
            newest = self.write(7, size + delta)
            cache = {}
            self.assertEqual(sum(p.stat().st_size for p in self.directory.glob('*.json')), limit + delta)
            self.select(cache)
            with patch.object(research, 'loads', wraps=research.loads) as parse:
                selected = self.select(cache)
            self.assertEqual(len(cache), 8 if delta <= 0 else 7)
            self.assertLessEqual(sum(item[2] for item in cache.values()), limit)
            self.assertEqual(parse.call_count, 0 if delta <= 0 else 1)
            self.assertEqual([x['experiment_id'] for x in selected], [f'exp-{i}' for i in range(3, 8)])
        self.assertNotIn(newest.stem, cache)
        self.assert_changed(newest, cache)

    def test_uncached_memory_is_released_before_scanning_all_history(self):
        # Track actual lifetime of projected memories, independent of RSS noise.
        class Memory(dict):
            pass
        live = weakref.WeakValueDictionary()
        peak = 0
        serial = 0
        original = research.loads
        def parse(text):
            nonlocal peak, serial
            doc = original(text)
            memory = Memory(doc['outputs']['memory'])
            doc['outputs']['memory'] = memory
            live[serial] = memory
            serial += 1
            peak = max(peak, len(live))
            return doc
        for index in range(50):
            self.write(index)
        with patch.object(research, 'HISTORY_CACHE_MAX_BYTES', 0), \
                patch.object(research, 'loads', side_effect=parse):
            selected = self.select({})
        self.assertEqual([x['experiment_id'] for x in selected],
                         [f'exp-{i}' for i in range(45, 50)])
        # Five retained candidates plus in-flight parser/reference allowance.
        self.assertLessEqual(peak, 7)
