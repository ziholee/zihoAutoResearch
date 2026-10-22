"""Relevance selection through fresh CLI processes and a loopback provider."""
from copy import deepcopy
import json
import os
import unittest

from zar.codec import dumps, loads
import test_session_memory_http as memory_helpers


class MemoryRelevanceHTTPTests(unittest.TestCase):
    # Reuse only fixture methods, never inherit unrelated test cases.
    setUp = memory_helpers.SessionMemoryHTTPTests.setUp
    stop_server = memory_helpers.SessionMemoryHTTPTests.stop_server
    invoke = memory_helpers.SessionMemoryHTTPTests.invoke
    start = memory_helpers.SessionMemoryHTTPTests.start
    assert_no_execution = memory_helpers.SessionMemoryHTTPTests.assert_no_execution
    response = memory_helpers.SessionMemoryHTTPTests.response
    evidence_handles = memory_helpers.SessionMemoryHTTPTests.evidence_handles
    saved = memory_helpers.SessionMemoryHTTPTests.saved

    def test_new_selection_pin_invalidates_approval_without_model_calls(self):
        session = self.start()
        self.assertEqual(session['memory_selection_version'], 1)
        session = self.invoke('advance', session['id'], '--send')
        self.assertEqual(session['state'], 'awaiting_approval')
        self.assertEqual(session['calls'], 5)
        saved = self.saved(session['id'])
        saved.pop('memory_selection_version')
        (self.root / '.autoresearch/sessions' / (session['id'] + '.json')).write_text(dumps(saved))
        self.invoke('approve', session['id'], '--token', session['approval_token'], expected=3)
        self.invoke('run', session['id'], expected=3)
        self.assertEqual(len(self.requests), 5)
        self.assertEqual(self.invoke('status', session['id'])['calls'], 5)
        self.assert_no_execution()

    through_decision = memory_helpers.SessionMemoryHTTPTests.through_decision
    complete = memory_helpers.SessionMemoryHTTPTests.complete

    def seed_history(self):
        """Derive provenance from an actual loopback/execution lifecycle."""
        completed = self.complete(self.start())
        template = self.saved(completed['id'])
        record_path = self.root / '.autoresearch/experiments' / (completed['experiment_id'] + '.json')
        matched = loads(record_path.read_text())
        mismatch = deepcopy(matched)
        mismatch['id'] = 'experiment-other-protocol'
        mismatch['comparison']['dataset_ref'] = 'other-dataset'
        mismatch['comparison']['id'] = 'cmp-other'
        (record_path.parent / (mismatch['id'] + '.json')).write_text(dumps(mismatch))
        (self.root / '.autoresearch/sessions' / (completed['id'] + '.json')).unlink()
        (self.root / 'metric.json').unlink()
        project_path = self.root / '.autoresearch/project.json'
        project = loads(project_path.read_text())
        project['selected_experiment_id'] = None
        project['budget']['max_experiments'] = 20
        project_path.write_text(dumps(project))
        self.requests.clear()
        self.history_template = template
        self.history_records = {matched['id']: matched, mismatch['id']: mismatch}
        self.matched_record = matched
        self.mismatched_record = mismatch
        return self.history(1, '2026-01-01', matched), self.history(2, '2026-02-01', mismatch)

    def history(self, number, stamp, record=None):
        from zar.session_memory import assess, build_evidence
        history = deepcopy(self.history_template)
        history.update(id=f'session-{number:032x}', created_at=stamp)
        history['outputs']['memory']['lesson'] = f'Historical lesson {number}'
        if record is None:
            history['experiment_id'] = None
            history.pop('memory_assessment', None)
            history.pop('memory_contract_version', None)
        else:
            history['experiment_id'] = record['id']
            evidence = build_evidence(history, self.history_records)
            history['outputs']['memory']['contrast']['evidence'] = list(evidence['handles'])
            history['memory_assessment'] = assess(history['outputs']['memory'], evidence)
        path = self.root / '.autoresearch/sessions' / (history['id'] + '.json')
        path.write_text(dumps(history))
        return path

    def contexts(self):
        return [json.loads(request[2]['messages'][-1]['content']) for request in self.requests]

    def test_older_match_precedes_unknown_and_excludes_newer_mismatch_without_promoting_hold(self):
        matched_path, mismatch_path = self.seed_history()
        unknown_path = self.history(3, '2026-03-01')
        session = self.invoke('advance', self.start()['id'], '--send')
        self.assertEqual(session['state'], 'awaiting_approval')
        self.assertEqual(session['calls'], 5)
        self.assertEqual(len(self.requests), 5)
        for context in self.contexts():
            lessons = context['prior_lessons']
            self.assertEqual([item['session_id'] for item in lessons], [matched_path.stem, unknown_path.stem])
            self.assertEqual([item['relevance'] for item in lessons], ['matched', 'unknown'])
            self.assertEqual(lessons[0]['assessment']['status'], 'hold')
            self.assertEqual(lessons[1]['assessment']['status'], 'unassessed')
            self.assertNotIn(mismatch_path.stem, [item['session_id'] for item in lessons])
            self.assertEqual(context['memory_selection']['counts']['mismatch'], 1)
        self.invoke('run', session['id'], expected=3)
        self.assertEqual(len(self.requests), 5)
        self.assertFalse((self.root / 'metric.json').exists())

    def test_unknown_fallback_is_bounded_and_ordered_newest_first(self):
        self.seed_history()
        for path in (self.root / '.autoresearch/sessions').glob('*.json'):
            path.unlink()
        paths = [self.history(n, f'2026-01-{n:02d}') for n in range(1, 8)]
        session = self.invoke('advance', self.start()['id'], '--send')
        self.assertEqual(session['calls'], 5)
        for context in self.contexts():
            lessons = context['prior_lessons']
            self.assertEqual([item['session_id'] for item in lessons], [path.stem for path in reversed(paths[-5:])])
            self.assertTrue(all(item['relevance'] == 'unknown' for item in lessons))
            self.assertTrue(all(item['assessment']['status'] == 'unassessed' for item in lessons))
            self.assertEqual(context['memory_selection']['limit'], 5)

    def test_versionless_session_resumes_legacy_recent_five_order(self):
        self.seed_history()
        paths = [self.history(n, f'2026-03-{n:02d}', self.mismatched_record) for n in range(3, 9)]
        session = self.start()
        saved = self.saved(session['id'])
        saved.pop('memory_selection_version')
        (self.root / '.autoresearch/sessions' / (session['id'] + '.json')).write_text(dumps(saved))
        session = self.invoke('advance', session['id'], '--send')
        self.assertEqual(session['calls'], 5)
        self.assertNotIn('memory_selection_version', self.saved(session['id']))
        for context in self.contexts():
            self.assertEqual([item['session_id'] for item in context['prior_lessons']], [path.stem for path in paths[-5:]])
            self.assertNotIn('memory_selection', context)
            self.assertTrue(all('relevance' not in item for item in context['prior_lessons']))

    def test_same_size_mtime_history_change_reselects_in_next_http_role(self):
        self.seed_history()
        # Six equal-length timestamps force one eligible match outside top five.
        paths = [self.history(n, f'2026-04-{n:02d}', self.matched_record) for n in range(3, 9)]
        original_response = self.response
        mutation = []
        def mutate_after_analysis(context):
            if context['role'] == 'analysis':
                path = paths[0]
                stat = path.stat()
                text = path.read_text()
                changed = text.replace('2026-04-03', '2026-04-30')
                self.assertNotEqual(text, changed)
                path.write_text(changed)
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                mutation.append((path.stat().st_size == stat.st_size, path.stat().st_mtime_ns == stat.st_mtime_ns))
            return original_response(context)
        self.response = mutate_after_analysis
        session = self.invoke('advance', self.start()['id'], '--send')
        self.assertEqual(session['calls'], 5)
        self.assertEqual(mutation, [(True, True)])
        contexts = self.contexts()
        self.assertNotIn(paths[0].stem, [item['session_id'] for item in contexts[0]['prior_lessons']])
        for context in contexts[1:]:
            self.assertEqual(context['prior_lessons'][0]['session_id'], paths[0].stem)
            self.assertEqual(len(context['prior_lessons']), 5)
