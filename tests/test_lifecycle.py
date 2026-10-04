import copy
import json
from decimal import Decimal

from test_experiments import ExperimentHarness


class LifecycleTests(ExperimentHarness):
    def correction(self, current, **changes):
        execution=copy.deepcopy(current['execution']); execution.update(changes)
        return dict(id='exp-corrected',revision=current['revision'],execution=execution,
                    reason='Transcription error; same run, no rerun',
                    evidence=[dict(kind='user_report',ref='checked original log',locator=None,sha256=None)])

    def correct(self, body, id='exp-1', expected=0):
        return self.invoke('experiment','correct',id,'--file',str(self.write_input(body)),expected=expected)

    def test_cancel_never_run_releases_budget_and_closes_unfinished(self):
        project=json.loads(self.stored.read_text()); project['budget']['max_experiments']=1
        self.invoke('project','set','--file',str(self.write_input(project)))
        self.register(); doc=json.loads(self.record().read_text())
        doc['execution'].update(status='cancelled',note='Plan replaced before launch')
        self.update(doc)
        self.assertEqual(self.invoke('status')['data']['unfinished'],[])
        self.register(self.create('exp-2'))
        doc=json.loads(self.record().read_text()); doc['execution'].update(status='running',started_at='2026-01-01T00:00:00Z')
        self.update(doc,expected=3)

    def test_unknown_start_can_be_recorded_then_resolved(self):
        self.register(); doc=json.loads(self.record().read_text())
        evidence=[dict(kind='user_report',ref='launch connection lost',locator=None,sha256=None)]
        doc['execution'].update(status='unknown',note='Start not confirmed',evidence=evidence)
        self.update(doc)
        saved=json.loads(self.record().read_text()); self.assertIsNone(saved['execution']['started_at'])
        doc=self.success(saved)
        self.update(doc)
        self.assertEqual(json.loads(self.record().read_text())['execution']['status'],'succeeded')

    def test_unknown_to_cancel_requires_new_evidence_no_known_start(self):
        self.register(); doc=json.loads(self.record().read_text())
        doc['execution'].update(status='unknown',note='Start not confirmed',
                                evidence=[dict(kind='user_report',ref='connection lost',locator=None,sha256=None)])
        self.update(doc); doc=json.loads(self.record().read_text())
        doc['execution']['status']='cancelled'
        self.update(doc,expected=3)
        doc['execution']['evidence'].append(dict(kind='user_report',ref='confirmed launch never happened',locator=None,sha256=None))
        self.update(doc)

    def test_correction_preserves_original_and_does_not_spend_run_budget(self):
        project=json.loads(self.stored.read_text()); project['budget']['max_experiments']=1
        self.invoke('project','set','--file',str(self.write_input(project)))
        self.register(); self.update(self.success(json.loads(self.record().read_text())))
        before=self.record().read_bytes(); current=json.loads(before)
        output=self.correct(self.correction(current,score=0.75))['data']['experiment']
        self.assertEqual(output['execution']['score'],0.75)
        self.assertEqual(output['correction']['supersedes_id'],'exp-1')
        self.assertEqual(output['code_ref'],current['code_ref'])
        self.assertIsNone(output['decision'])
        self.assertEqual(output['decision_history'],[])
        self.assertEqual(self.record().read_bytes(),before)
        state=self.invoke('status')['data']
        self.assertEqual(state['budget_used'],1)
        self.assertEqual(state['superseded_experiment_ids'],['exp-1'])

    def test_correction_rejects_stale_input_branching_and_artifact_changes(self):
        self.register(); self.update(self.success(json.loads(self.record().read_text())))
        current=json.loads(self.record().read_text()); body=self.correction(current,score=0.75)
        body['revision']-=1; self.correct(body,expected=3)
        body['revision']+=1; self.correct(body)
        body['id']='exp-other'; self.correct(body,expected=3)
        before=self.record().read_bytes()
        self.update(current,expected=3)
        self.assertEqual(self.record().read_bytes(),before)
        latest=json.loads(self.record('exp-corrected').read_text()); body=self.correction(latest,score=0.7); body['id']='exp-corrected-2'
        self.correct(body,id='exp-corrected')
        self.invoke('check')

    def test_selected_experiment_must_be_deselected_before_correction(self):
        self.register(); self.update(self.success(json.loads(self.record().read_text())))
        current=json.loads(self.record().read_text())
        decision=dict(status='keep',validity='valid',reason='fixture',evidence=current['execution']['evidence'],next_action=None)
        current['decision']=decision; current['decision_history']=[dict(decided_at=current['updated_at'],decision=decision)]
        self.record().write_text(json.dumps(current))
        project=json.loads(self.stored.read_text()); project['selected_experiment_id']='exp-1'
        self.invoke('project','set','--file',str(self.write_input(project)))
        self.correct(self.correction(current,score=0.7),expected=3)
        self.assertFalse(self.record('exp-corrected').exists())

    def test_optional_correction_omission_is_legacy_compatible(self):
        self.register(); doc=json.loads(self.record().read_text())
        doc.pop('correction')
        doc['execution'].update(status='running',started_at='2026-01-01T00:00:00Z')
        self.update(doc)
        self.assertEqual(json.loads(self.record().read_text())['execution']['status'],'running')

    def test_correction_requires_reason_evidence_and_same_artifacts(self):
        self.register(); self.update(self.success(json.loads(self.record().read_text())))
        current=json.loads(self.record().read_text()); before=self.record().read_bytes()
        body=self.correction(current,score=0.8); body['reason']=''
        self.correct(body,expected=2)
        body=self.correction(current,score=0.8); body['evidence']=[]
        self.correct(body,expected=2)
        body=self.correction(current,score=0.8)
        body['execution']['artifacts']=[dict(role='model',path='model.bin',sha256=None,
                                             code_ref=current['code_ref'],config_ref=current['config_ref'],evidence=body['evidence'])]
        self.correct(body,expected=3)
        self.assertEqual(self.record().read_bytes(),before)

    def test_correction_uses_original_plan_after_project_settings_change(self):
        self.register(); self.update(self.success(json.loads(self.record().read_text())))
        current=json.loads(self.record().read_text())
        project=json.loads(self.stored.read_text()); project['comparison']['id']='comparison-2'; project['environment']['os']='windows'
        self.invoke('project','set','--file',str(self.write_input(project)))
        result=self.correct(self.correction(current,score=0.8))['data']['experiment']
        self.assertEqual(result['comparison'],json.loads(self.record().read_text(),parse_float=Decimal)['comparison'])
        self.assertEqual(result['environment'],current['environment'])

    def test_correction_preserves_existing_submission_link_and_reports_staleness(self):
        from test_fixture_project import FixtureProjectTests
        FixtureProjectTests.prepare_fixture(self)
        candidate=json.loads(self.record('exp-candidate').read_text())
        submission=self.stored.parent/'submissions/submission-1.json'
        before=submission.read_bytes()
        result=self.correct(self.correction(candidate,score=0.9),id='exp-candidate')
        self.assertIsNone(result['data']['experiment']['decision'])
        self.assertEqual(submission.read_bytes(),before)
        self.assertTrue(any(d['code']=='reference_superseded' for d in self.invoke('check')['diagnostics']))
