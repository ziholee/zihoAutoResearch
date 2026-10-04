import copy
import json

from test_cli import CliHarness


class ExperimentTests(CliHarness):
    def setUp(self):
        super().setUp()
        doc = self.ready(self.init())
        self.invoke('project', 'set', '--file', str(self.write_input(doc)))

    def create(self, id='exp-1', **changes):
        body = dict(id=id, kind='baseline', hypothesis='Test records only', parent_id=None,
                    baseline_id=None, code_ref='code-1', config_ref='config-1',
                    command={'name':'train','argv':['never-execute-this'],'cwd':'.'}, review_ids=[])
        body.update(changes)
        return body

    def register(self, body=None, expected=0):
        return self.invoke('experiment', 'create', '--file', str(self.write_input(body or self.create())), expected=expected)

    def record(self, id='exp-1'):
        return self.stored.parent / 'experiments' / (id + '.json')

    def update(self, doc, expected=0):
        return self.invoke('experiment', 'update', 'exp-1', '--file', str(self.write_input(doc)), expected=expected)

    def success(self, doc):
        doc['execution'].update(status='succeeded', started_at='2026-01-01T00:00:00Z',
                                finished_at='2026-01-01T00:01:00Z', exit_code=0, score=1.25,
                                evidence=[{'kind':'user_report','ref':'simulated result','locator':None,'sha256':None}])
        return doc

    def test_create_copies_settings_and_preserves_project(self):
        before = self.stored.read_bytes()
        self.register()
        doc = json.loads(self.record().read_text())
        project = json.loads(before)
        self.assertEqual(doc['comparison'], project['comparison'])
        self.assertEqual(doc['environment'], project['environment'])
        self.assertEqual(doc['execution']['status'], 'planned')
        self.assertEqual(doc['revision'], 1)
        self.assertIsNone(doc['decision'])
        self.assertEqual(self.stored.read_bytes(), before)
        self.assertEqual(self.invoke('status')['data']['unfinished'], [{'id':'exp-1','status':'planned'}])

    def test_duplicate_and_missing_references_do_not_write(self):
        self.register()
        before = self.record().read_bytes()
        self.register(expected=3)
        self.register(self.create('exp-2', parent_id='missing'), expected=3)
        self.register(self.create('exp-2', review_ids=['missing']), expected=3)
        self.assertEqual(self.record().read_bytes(), before)
        self.assertFalse(self.record('exp-2').exists())

    def test_budget_and_unready_project_block_creation(self):
        doc = json.loads(self.stored.read_text())
        doc['budget']['max_experiments'] = 1
        self.invoke('project','set','--file',str(self.write_input(doc)))
        self.register()
        self.register(self.create('exp-2'), expected=3)
        doc = json.loads(self.stored.read_text()); doc['objective'] = None
        self.invoke('project','set','--file',str(self.write_input(doc)))
        self.register(self.create('exp-3'), expected=3)

    def test_create_rejects_generated_fields_and_invalid_id(self):
        self.register(self.create(revision=100), expected=2)
        self.register(self.create('../outside'), expected=2)
        self.assertEqual(list((self.stored.parent/'experiments').iterdir()), [])

    def test_running_success_and_stale_revision(self):
        self.register()
        doc = json.loads(self.record().read_text())
        doc['execution'].update(status='running', started_at='2026-01-01T00:00:00Z')
        self.update(doc)
        self.update(doc, expected=3)
        doc = self.success(json.loads(self.record().read_text()))
        self.update(doc)
        saved = json.loads(self.record().read_text())
        self.assertEqual(saved['revision'], 3)
        self.assertEqual(saved['execution']['score'], 1.25)
        self.assertEqual(self.invoke('status')['data']['unfinished'], [])

    def test_terminal_results_and_plans_are_immutable(self):
        self.register()
        self.update(self.success(json.loads(self.record().read_text())))
        before = self.record().read_bytes()
        doc = json.loads(before)
        for field, value in [('hypothesis','different'), ('code_ref','other')]:
            changed = copy.deepcopy(doc); changed[field] = value
            self.update(changed, expected=3)
        changed = copy.deepcopy(doc); changed['execution']['score'] = 0.5
        self.update(changed, expected=3)
        self.assertEqual(self.record().read_bytes(), before)

    def test_direct_failure_requires_observation_evidence(self):
        self.register()
        doc = json.loads(self.record().read_text())
        doc['execution'].update(status='failed', started_at='2026-01-01T00:00:00Z',
                                finished_at='2026-01-01T00:01:00Z', exit_code=1, note='simulated failure')
        self.update(doc, expected=3)
        doc['execution']['evidence'] = self.success(copy.deepcopy(doc))['execution']['evidence']
        self.update(doc)

    def test_unknown_resume_requires_new_evidence_and_keeps_start(self):
        self.register()
        doc = json.loads(self.record().read_text())
        doc['execution'].update(status='running', started_at='2026-01-01T00:00:00Z')
        self.update(doc)
        doc = json.loads(self.record().read_text())
        doc['execution'].update(status='unknown', note='lost observation')
        self.update(doc)
        doc = json.loads(self.record().read_text()); doc['execution']['status'] = 'running'
        self.update(doc, expected=3)
        doc['execution']['evidence'] = [{'kind':'user_report','ref':'process checked','locator':None,'sha256':None}]
        self.update(doc)
        doc = json.loads(self.record().read_text()); doc['execution']['started_at'] = '2026-01-01T00:00:01Z'
        self.update(doc, expected=3)

    def test_execution_evidence_cannot_be_erased_and_reused_to_resolve_unknown(self):
        self.register()
        doc = json.loads(self.record().read_text())
        evidence = [{'kind':'user_report','ref':ref,'locator':None,'sha256':None}
                    for ref in ('initial observation', 'lost process observation')]
        doc['execution'].update(status='running', started_at='2026-01-01T00:00:00Z',
                                evidence=evidence)
        self.update(doc)
        for status in ('running', 'unknown'):
            if status == 'unknown':
                doc = json.loads(self.record().read_text())
                doc['execution'].update(status='unknown', note='lost observation')
                self.update(doc)
            before = self.record().read_bytes()
            for replacement in ([], evidence[:1], list(reversed(evidence)),
                                [dict(evidence[0], ref='replacement'), evidence[1]]):
                with self.subTest(status=status, replacement=replacement):
                    doc = json.loads(before)
                    doc['execution']['evidence'] = replacement
                    self.update(doc, expected=3)
                    self.assertEqual(self.record().read_bytes(), before)
        doc = self.success(json.loads(self.record().read_text()))
        doc['execution']['evidence'] = evidence
        self.update(doc, expected=3)
        doc['execution']['evidence'] = evidence + [
            {'kind':'user_report','ref':'new confirmed result','locator':None,'sha256':None}]
        self.update(doc)
        self.assertEqual(json.loads(self.record().read_text())['execution']['evidence'],
                         doc['execution']['evidence'])

    def test_artifacts_are_append_only_and_submission_hash_required(self):
        self.register()
        self.update(self.success(json.loads(self.record().read_text())))
        doc = json.loads(self.record().read_text())
        artifact = dict(role='submission', path='simulated.csv', sha256=None, code_ref='code-1',
                        config_ref='config-1', evidence=doc['execution']['evidence'])
        doc['execution']['artifacts'] = [artifact]
        self.update(doc, expected=2)
        artifact['sha256'] = 'a'*64
        self.update(doc)
        doc = json.loads(self.record().read_text()); doc['execution']['artifacts'] = []
        self.update(doc, expected=3)

    def test_invalid_transition_and_decision_changes_preserve_record(self):
        self.register()
        before = self.record().read_bytes()
        doc = json.loads(before)
        doc['execution'].update(status='unknown', started_at='2026-01-01T00:00:00Z', note='unobserved')
        self.update(doc, expected=3)
        self.assertEqual(self.record().read_bytes(), before)
        self.update(self.success(json.loads(before)))
        before = self.record().read_bytes(); doc = json.loads(before)
        decision = dict(status='keep',validity='valid',reason='fake decision',
                        evidence=doc['execution']['evidence'],next_action=None)
        doc['decision'] = decision
        doc['decision_history'] = [dict(decided_at=doc['updated_at'], decision=decision)]
        self.update(doc, expected=3)
        self.assertEqual(self.record().read_bytes(), before)

    def test_candidate_baseline_and_settings_snapshot(self):
        self.register()
        doc = json.loads(self.stored.read_text())
        doc['environment']['os'] = 'windows'
        self.invoke('project','set','--file',str(self.write_input(doc)))
        self.register(self.create('exp-2', kind='performance', baseline_id='exp-1', parent_id='exp-1'))
        self.assertEqual(json.loads(self.record('exp-2').read_text())['environment']['os'], 'windows')
        self.assertEqual(json.loads(self.record().read_text())['environment']['os'], 'linux')
        doc = json.loads(self.stored.read_text()); doc['comparison']['id'] = 'new-comparison'
        self.invoke('project','set','--file',str(self.write_input(doc)))
        self.register(self.create('exp-3',kind='performance',baseline_id='exp-1'), expected=3)
        self.assertFalse(self.record('exp-3').exists())

    def test_create_write_failure_leaves_no_record(self):
        from unittest.mock import patch
        from zar.cli import main
        from contextlib import redirect_stdout
        import io
        source = self.write_input(self.create())
        with patch('zar.storage.os.replace', side_effect=OSError('simulated disk failure')):
            with redirect_stdout(io.StringIO()) as output:
                code = main(['experiment','create','--file',str(source),'--project',str(self.project),'--json'])
        self.assertEqual(code, 4)
        self.assertFalse(json.loads(output.getvalue())['ok'])
        self.assertEqual(list((self.stored.parent/'experiments').iterdir()), [])
        self.assertFalse((self.stored.parent/'.lock').exists())

    def test_text_output_with_unicode_warning_does_not_fail_after_save(self):
        import os
        import subprocess
        import sys
        from test_cli import REPO
        self.register()
        doc = self.success(json.loads(self.record().read_text()))
        doc['execution']['evidence'] = [dict(kind='fixture', ref='없는-로그.txt', locator=None, sha256=None)]
        source = self.write_input(doc)
        result = subprocess.run([sys.executable, '-m', 'zar', 'experiment', 'update', 'exp-1',
                                 '--file', str(source), '--project', str(self.project)],
                                env={**os.environ, 'PYTHONIOENCODING':'cp1252', 'PYTHONPATH':str(REPO)},
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'warning:', result.stdout)
        self.assertEqual(json.loads(self.record().read_text())['revision'], 2)
