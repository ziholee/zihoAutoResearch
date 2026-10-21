"""Reuse bounded projections without reusing record snapshots across model calls."""
import copy
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

from zar import cli, records, research
from zar.codec import dumps, loads

ROOT = Path(__file__).resolve().parents[1]
BENCH = runpy.run_path(str(ROOT / 'scripts/benchmark_research_scale.py'))


class RecordProjectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.private = Path(temp.name).resolve()
        self.root = self.private / 'project'
        BENCH['fixture'](ROOT, self.root, 2, 0, self.private, 60)
        self.record = self.root / '.autoresearch/experiments/exp-000000.json'
        self.session = research.start(self.root,
            profile=dict(base_url='http://localhost:9999/v1', model='mock', api_key_env='ZAR_TEST_UNUSED'),
            goal='Inspect synthetic candidate', read_paths=['train.py'], command='train',
            metric_file='metric.json', metric_key='rmse', max_calls=9, session_seconds=300,
            scope='full', seed=42, budget_ref='synthetic')
        self.payloads = []

    def respond(self, profile, messages):
        payload = json.loads(messages[-1]['content'])
        self.payloads.append(payload)
        return dict(content=json.dumps(BENCH['body'](payload['role'])), usage=None)

    def test_one_projection_but_all_freshness_checks_and_latest_role_outputs(self):
        with patch.object(cli, 'build_context', wraps=cli.build_context) as build, \
                patch.object(records, 'load_records', wraps=records.load_records) as reads, \
                patch.object(research, 'chat', side_effect=self.respond):
            result = research.advance(self.root, self.session['id'], send=True)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(reads.call_count, 10)
        self.assertEqual(result['state'], 'awaiting_approval')
        self.assertEqual([p['role'] for p in self.payloads], BENCH['ROLES'])
        # The role compactor may omit old responses; each role still sees its
        # required evidence. The final review must include implementation.
        self.assertIn('implementation', self.payloads[-1]['outputs'])
        self.assertEqual(len({p['records']['snapshot_id'] for p in self.payloads}), 1)
        self.assertFalse((self.root / 'metric.json').exists())

    def mutate(self, kind):
        doc = loads(self.record.read_text())
        if kind == 'delete':
            self.record.unlink()
        elif kind == 'project':
            path = self.root / '.autoresearch/project.json'
            project = loads(path.read_text()); project['objective'] = 'Changed objective'
            path.write_text(dumps(project))
        else:
            path = self.record
            if kind in ('add', 'correction'):
                doc['id'] = 'new-record'; path = path.with_name('new-record.json')
            if kind == 'correction':
                doc['correction'] = dict(supersedes_id='exp-000000', reason='Corrected evidence',
                    evidence=[dict(kind='user_report', ref='synthetic correction', locator=None, sha256=None)])
            doc['hypothesis'] = 'Changed hypothesis'
            path.write_text(dumps(doc))

    def test_changes_during_second_call_are_detected_after_projection_reuse(self):
        for kind in ('edit', 'delete', 'add', 'correction', 'project'):
            with self.subTest(kind=kind):
                # Each case gets an untouched project and a new session.
                if self.payloads:
                    self.setUp()
                def answer(*args):
                    result = self.respond(*args)
                    if len(self.payloads) == 2:
                        self.mutate(kind)
                    return result
                with patch.object(cli, 'build_context', wraps=cli.build_context) as build, \
                        patch.object(research, 'chat', side_effect=answer):
                    with self.assertRaises(research.ResearchError):
                        research.advance(self.root, self.session['id'], send=True)
                saved = research.load(self.root, self.session['id'])
                self.assertEqual(saved['state'], 'blocked')
                self.assertEqual(saved['error'], 'inputs_changed')
                self.assertEqual(list(saved['outputs']), ['analysis'])
                self.assertEqual(build.call_count, 1)

    def test_change_between_roles_is_detected_before_another_model_call(self):
        original = research.save
        def save(root, session):
            original(root, session)
            if session['state'] == 'planning' and 'analysis' in session['outputs']:
                self.mutate('edit')
        with patch.object(research, 'save', side_effect=save), \
                patch.object(research, 'chat', side_effect=self.respond):
            with self.assertRaises(research.ResearchError):
                research.advance(self.root, self.session['id'], send=True)
        self.assertEqual(len(self.payloads), 1)

    def test_interruption_discards_projection_and_resume_preserves_successes(self):
        def interrupted(profile, messages):
            if json.loads(messages[-1]['content'])['role'] == 'planning':
                raise KeyboardInterrupt('mock interruption')
            return self.respond(profile, messages)
        with patch.object(cli, 'build_context', wraps=cli.build_context) as build, \
                patch.object(research, 'chat', side_effect=interrupted):
            with self.assertRaises(research.ResearchError):
                research.advance(self.root, self.session['id'], send=True)
            self.assertEqual(build.call_count, 1)
        before = research.load(self.root, self.session['id'])
        with patch.object(cli, 'build_context', wraps=cli.build_context) as build, \
                patch.object(research, 'chat', side_effect=self.respond):
            after = research.advance(self.root, self.session['id'], send=True)
            self.assertEqual(build.call_count, 1)
        self.assertEqual(after['calls'], 6)
        self.assertEqual(after['state'], 'awaiting_approval')
        self.assertEqual([p['role'] for p in self.payloads], BENCH['ROLES'])
        for role in ('analysis', 'evaluation'):
            self.assertEqual(before['outputs'][role], after['outputs'][role])
        self.mutate('edit')
        with self.assertRaises(research.ResearchError):
            research.approve(self.root, after['id'], after['approval_token'])

    def test_new_completed_memory_is_visible_on_next_role(self):
        def answer(*args):
            result = self.respond(*args)
            if len(self.payloads) == 1:
                old = copy.deepcopy(self.session)
                old.update(id='session-' + '0' * 32, state='complete',
                           experiment_id='exp-000000', outputs={'memory': BENCH['body']('memory')})
                research.save(self.root, old)
            return result
        with patch.object(research, 'chat', side_effect=answer):
            research.advance(self.root, self.session['id'], send=True)
        self.assertEqual(self.payloads[0]['prior_lessons'], [])
        self.assertEqual(self.payloads[1]['prior_lessons'][0]['session_id'], 'session-' + '0' * 32)


if __name__ == '__main__':
    unittest.main()
