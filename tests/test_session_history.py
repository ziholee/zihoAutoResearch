"""Fresh history selection with bounded, content-checked parsing reuse."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from zar import cli, research
from zar.codec import dumps, loads


class SessionHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.directory = self.root / '.autoresearch/sessions'
        self.directory.mkdir(parents=True)
        self.active = {'id': 'session-' + 'f' * 32}

    def history(self, number, stamp='2026-01-01', *, state='complete', memory=True, lesson='before'):
        identifier = f'session-{number:032x}'
        doc = dict(id=identifier, experiment_id=f'exp-{number}', created_at=stamp,
                   state=state, outputs={'memory': {'lesson': lesson}} if memory else {})
        path = self.directory / (identifier + '.json')
        path.write_text(dumps(doc), encoding='utf-8')
        return path

    def select(self, cache):
        return research._prior_lessons(self.root, self.active, cache=cache)

    def test_recent_five_uses_timestamp_then_filename_and_eligibility(self):
        # Deliberately disagree with filename order; equal timestamps retain it.
        for number, stamp in enumerate(('8', '1', '7', '3', '6', '6', '2')):
            self.history(number, stamp)
        self.history(20, '9', state='planning')
        self.history(21, '9', memory=False)
        self.active = {'id': f'session-{22:032x}'}
        self.history(22, '9')
        cache = {}
        expected = [3, 4, 5, 2, 0]
        for _ in range(2):
            self.assertEqual([x['experiment_id'] for x in self.select(cache)],
                             [f'exp-{n}' for n in expected])

    def test_unchanged_history_is_reread_but_parsed_once(self):
        self.history(1)
        cache = {}
        with patch.object(research, '_read_session', wraps=research._read_session) as read, \
                patch.object(research, 'loads', wraps=research.loads) as parse:
            first = self.select(cache)
            second = self.select(cache)
        self.assertEqual(first, second)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(parse.call_count, 1)
        first[0]['proposal']['lesson'] = 'mutated by caller'
        self.assertEqual(self.select(cache)[0]['proposal']['lesson'], 'before')

    def test_same_size_same_mtime_change_is_visible(self):
        path = self.history(1)
        cache = {}
        self.assertEqual(self.select(cache)[0]['proposal']['lesson'], 'before')
        original = path.stat()
        path.write_text(path.read_text(encoding='utf-8').replace('before', 'after!'), encoding='utf-8')
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(path.stat().st_size, original.st_size)
        self.assertEqual(path.stat().st_mtime_ns, original.st_mtime_ns)
        self.assertEqual(self.select(cache)[0]['proposal']['lesson'], 'after!')

    def test_add_delete_state_and_memory_changes_are_visible(self):
        one = self.history(1)
        cache = {}
        self.assertEqual(len(self.select(cache)), 1)
        self.history(2, state='planning')
        self.assertEqual(len(self.select(cache)), 1)
        self.history(2)
        self.assertEqual(len(self.select(cache)), 2)
        one.unlink()
        self.assertEqual([x['experiment_id'] for x in self.select(cache)], ['exp-2'])
        self.history(2, memory=False)
        self.assertEqual(self.select(cache), [])
        self.history(2, lesson='new memory')
        self.assertEqual(self.select(cache)[0]['proposal']['lesson'], 'new memory')
        self.history(2, state='planning')
        self.assertEqual(self.select(cache), [])

    def test_changed_invalid_history_is_not_hidden_by_cache(self):
        path = self.history(1)
        cache = {}
        self.select(cache)
        for invalid in ('{"state":"complete","state":"complete"}', '[1]', '{"x":NaN}', '{'):
            with self.subTest(invalid=invalid):
                path.write_text(invalid, encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.select(cache)
        path.write_text(' ' * 2_000_001, encoding='utf-8')
        with self.assertRaisesRegex(research.ResearchError, 'size limit'):
            self.select(cache)

    def test_cached_file_replaced_with_symlink_is_rejected(self):
        path = self.history(1)
        cache = {}
        self.select(cache)
        target = self.root / 'outside.json'
        target.write_bytes(path.read_bytes())
        path.unlink()
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable on this host')
        with self.assertRaisesRegex(research.ResearchError, 'Redirected'):
            self.select(cache)

    def test_cache_limits_do_not_limit_selection_or_freshness(self):
        first = self.history(1, '1')
        self.history(2, '2')
        size = len(first.read_bytes())
        for entry_limit, byte_limit in ((1, 8 * 1024 * 1024), (2048, size), (2048, 0)):
            with self.subTest(entries=entry_limit, bytes=byte_limit), \
                    patch.object(research, 'HISTORY_CACHE_MAX_ENTRIES', entry_limit), \
                    patch.object(research, 'HISTORY_CACHE_MAX_BYTES', byte_limit):
                cache = {}
                with patch.object(research, 'loads', wraps=research.loads) as parse:
                    self.select(cache)
                    selected = self.select(cache)
                self.assertEqual([x['experiment_id'] for x in selected], ['exp-1', 'exp-2'])
                self.assertLessEqual(len(cache), entry_limit)
                self.assertLessEqual(sum(entry[2] for entry in cache.values()), byte_limit)
                self.assertEqual(parse.call_count, 4 if byte_limit == 0 else 3)
                first.unlink()
                self.assertEqual([x['experiment_id'] for x in self.select(cache)], ['exp-2'])
                self.assertNotIn(first.stem, cache)
                self.history(1, '1')

    def test_invalid_history_filename_is_still_rejected(self):
        self.history(1).rename(self.directory / 'unexpected.json')
        with self.assertRaisesRegex(research.ResearchError, 'Invalid session ID'):
            self.select({})


class SessionHistoryLoopTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        cli.initialize(self.root)
        (self.root / 'train.py').write_text('# unchanged source\n', encoding='utf-8')
        path = self.root / '.autoresearch/project.json'
        project = loads(path.read_text(encoding='utf-8'))
        project.update(name='test', objective='bounded mock experiment',
            comparison=dict(id='cmp', dataset_ref='synthetic', split_ref='fixed', metric='score',
                            direction='minimize', evaluation_ref='v1', min_delta=0),
            environment=dict(os='other', runtime='python', device='cpu'),
            commands=[dict(name='train', argv=[sys.executable, 'train.py'], cwd='.')],
            budget=dict(max_experiments=3, max_run_seconds=5), editable_paths=['train.py'])
        path.write_text(dumps(project), encoding='utf-8')
        self.session = research.start(self.root,
            profile=dict(base_url='http://localhost:9999/v1', model='mock', api_key_env='ZAR_TEST_UNUSED'),
            goal='test', read_paths=['train.py'], command='train', metric_file='metric.json',
            metric_key='score', max_calls=9, session_seconds=300, scope='full', seed=42, budget_ref='test')
        self.history_id = 'session-' + '0' * 32
        self.path = self.root / '.autoresearch/sessions' / (self.history_id + '.json')
        self.history = dict(id=self.history_id, experiment_id=None, created_at='2026-01-01',
                            state='complete', outputs={'memory': {'lesson': 'before'}})
        self.write_history()
        self.payloads = []

    def write_history(self):
        self.path.write_text(dumps(self.history), encoding='utf-8')

    def respond(self, profile, messages):
        payload = json.loads(messages[-1]['content'])
        self.payloads.append(payload)
        role = payload['role']
        body = dict(summary='Observed source', evidence=['train.py'], uncertainties=[])
        body.update(dict(analysis=dict(missing=[]), evaluation=dict(verdict='pass'),
                         planning=dict(hypothesis='baseline'), implementation=dict(changes=[]),
                         review=dict(verdict='pass'))[role])
        return dict(content=dumps(body), usage=None)

    def test_advance_rereads_history_five_times_but_parses_it_once(self):
        history_text = self.path.read_text(encoding='utf-8')
        original_read, original_parse = Path.read_text, research.loads
        reads, parses = [], []
        def read(path, *args, **kwargs):
            if path == self.path:
                reads.append(path)
            return original_read(path, *args, **kwargs)
        def parse(text):
            if text == history_text:
                parses.append(text)
            return original_parse(text)
        with patch.object(Path, 'read_text', new=read), \
                patch.object(research, 'loads', side_effect=parse), \
                patch.object(research, 'chat', side_effect=self.respond):
            result = research.advance(self.root, self.session['id'], send=True)
        self.assertEqual(len(reads), 5)
        self.assertEqual(len(parses), 1)
        self.assertEqual(result['state'], 'awaiting_approval')

    def test_next_role_observes_changed_memory_and_still_requires_approval(self):
        def respond(*args):
            answer = self.respond(*args)
            if len(self.payloads) == 1:
                self.history['outputs']['memory']['lesson'] = 'updated'
                self.write_history()
            return answer
        with patch.object(research, 'chat', side_effect=respond):
            result = research.advance(self.root, self.session['id'], send=True)
        self.assertEqual(self.payloads[0]['prior_lessons'][0]['proposal']['lesson'], 'before')
        self.assertEqual([p['prior_lessons'][0]['proposal']['lesson'] for p in self.payloads[1:]],
                         ['updated'] * 4)
        self.assertEqual(result['state'], 'awaiting_approval')
        self.assertFalse((self.root / 'metric.json').exists())
        with self.assertRaises(research.ResearchError):
            research.run_session(self.root, self.session['id'])

    def test_resume_reloads_history_and_preserves_successful_roles(self):
        def interrupted(*args):
            payload = json.loads(args[1][-1]['content'])
            if payload['role'] == 'planning':
                raise KeyboardInterrupt('mock interruption')
            return self.respond(*args)
        with patch.object(research, 'chat', side_effect=interrupted):
            with self.assertRaises(research.ResearchError):
                research.advance(self.root, self.session['id'], send=True)
        prior = research.load(self.root, self.session['id'])
        self.assertEqual(prior['calls'], 3)
        self.assertEqual(list(prior['outputs']), ['analysis', 'evaluation'])
        self.history['outputs']['memory']['lesson'] = 'after restart'
        self.write_history()
        self.payloads.clear()
        with patch.object(research, 'chat', side_effect=self.respond):
            result = research.advance(self.root, self.session['id'], send=True)
        self.assertEqual([p['role'] for p in self.payloads], ['planning', 'implementation', 'review'])
        self.assertTrue(all(p['prior_lessons'][0]['proposal']['lesson'] == 'after restart'
                            for p in self.payloads))
        saved = research.load(self.root, self.session['id'])
        self.assertEqual(saved['calls'], 6)
        for role in ('analysis', 'evaluation'):
            self.assertEqual(saved['outputs'][role], prior['outputs'][role])
        self.assertEqual(result['state'], 'awaiting_approval')
