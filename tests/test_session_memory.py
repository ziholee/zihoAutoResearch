"""A model's lesson is a proposal, never proof of a reusable causal effect."""
from copy import deepcopy
import unittest
from zar import session_memory as memory
from zar.roles import RoleError, validate_response


def record(identifier, score, baseline=None):
    return dict(id=identifier, revision=1, baseline_id=baseline, correction=None,
                comparison=dict(direction='minimize', min_delta=0),
                environment=dict(os='other', runtime='python', device='cpu'),
                run_context=dict(scope='full', seed=42, budget_ref='one'),
                execution=dict(status='succeeded', score=score), decision=None)


class SessionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.base=record('base',2);self.candidate=record('candidate',1,'base')
        self.records={'base':self.base,'candidate':self.candidate}
        self.session=dict(id='session',experiment_id='candidate',outputs={'implementation':{'changes':[]}},memory_contract_version=1)

    def evidence(self):return memory.build_evidence(self.session,self.records)
    def proposal(self,effect='helped'):
        return dict(summary='observation',evidence=['records'],uncertainties=[],next_action='stop',lesson='proposal',limitation='one run',
                    contrast=dict(effect=effect,applicability='same conditions',evidence=list(self.evidence()['handles'])))

    def test_comparable_improvement_remains_single_observation_hold(self):
        out=memory.assess(self.proposal(),self.evidence())
        self.assertEqual((out['status'],out['claim_effect'],out['observed_effect']),('hold','helped','helped'))
        self.assertIn('single_comparison_not_causal_evidence',out['reasons'])
        self.assertEqual(out['provenance']['experiment']['id'],'candidate')

    def test_missing_contrast_and_baseline_cannot_promote(self):
        proposal=self.proposal();proposal.pop('contrast')
        self.assertIn('missing_contrast',memory.assess(proposal,self.evidence())['reasons'])
        self.candidate['baseline_id']=None
        out=memory.assess(proposal,self.evidence())
        self.assertIsNone(out['observed_effect']);self.assertIn('missing_baseline',out['reasons'])

    def test_claim_opposite_direction_and_confounded_are_held(self):
        out=memory.assess(self.proposal('hurt'),self.evidence())
        self.assertIn('claim_disagrees_with_observation',out['reasons'])
        out=memory.assess(self.proposal('confounded'),self.evidence())
        self.assertIn('model_reports_confounding',out['reasons'])

    def test_multiple_files_do_not_assert_multiple_treatments(self):
        self.session['outputs']['implementation']['changes']=[{'path':'a'},{'path':'b'}]
        out=memory.assess(self.proposal(),self.evidence())
        self.assertIn('intervention_isolation_unverified',out['reasons'])
        self.assertNotIn('model_reports_confounding',out['reasons'])

    def test_unknown_mismatch_and_correction_remove_observed_effect(self):
        for change in ('unknown','mismatch','correction','missing_score'):
            with self.subTest(change=change):
                records=deepcopy(self.records)
                if change=='unknown':records['candidate']['execution']['status']='unknown'
                elif change=='mismatch':records['candidate']['run_context']['scope']='proxy'
                elif change=='missing_score':records['candidate']['execution']['score']=None
                else:records['corrected']=dict(record('corrected',1,'base'),correction={'supersedes_id':'candidate'})
                evidence=memory.build_evidence(self.session,records)
                self.assertIsNone(memory.assess({},evidence)['observed_effect'])

    def test_invented_or_old_hash_reference_rejected(self):
        proposal=self.proposal();proposal['contrast']['evidence']=['invented']
        with self.assertRaises(ValueError):memory.assess(proposal,self.evidence())
        proposal=self.proposal();self.candidate['revision']=2
        with self.assertRaises(ValueError):memory.assess(proposal,self.evidence())

    def test_projection_rechecks_changed_or_missing_original(self):
        old=dict(self.session,outputs=dict(self.session['outputs'],memory=self.proposal()),created_at='now')
        old['memory_assessment']=memory.assess(old['outputs']['memory'],self.evidence())
        self.candidate['revision']=2
        out=memory.project(old,self.records)
        self.assertIn('source_changed',out['assessment']['reasons'])
        self.assertEqual(out['proposal'],old['outputs']['memory'])
        self.assertIsNone(out['assessment']['observed_effect'])

    def test_reuse_recomputes_assessment_not_saved_judgment(self):
        old=dict(self.session,outputs=dict(self.session['outputs'],memory=self.proposal()),created_at='now')
        old['memory_assessment']=memory.assess(old['outputs']['memory'],self.evidence())
        old['memory_assessment'].update(status='verified',observed_effect='hurt',reasons=[])
        projected=memory.project(old,self.records)['assessment']
        self.assertEqual(projected['status'],'hold')
        self.assertEqual(projected['observed_effect'],'helped')
        self.assertIn('single_comparison_not_causal_evidence',projected['reasons'])

    def test_legacy_output_is_unassessed(self):
        old=dict(self.session,outputs={'memory':{'lesson':'old'}},created_at='now')
        old.pop('memory_contract_version')
        self.assertEqual(memory.project(old,self.records)['assessment']['status'],'unassessed')

    def test_contrast_grammar_bounded_and_versioned(self):
        proposal=self.proposal()
        validate_response('memory',proposal,memory_version=1)
        with self.assertRaises(RoleError):validate_response('memory',proposal)
        for value in ({},dict(proposal['contrast'],extra=1),dict(proposal['contrast'],evidence=['x']*21)):
            proposal['contrast']=value
            with self.assertRaises(RoleError):validate_response('memory',proposal,memory_version=1)


class SessionMemoryGateTests(unittest.TestCase):
    def setUp(self):
        from tests.test_research import ResearchTests
        ResearchTests.setUp(self)
    def start(self):
        from tests.test_research import ResearchTests
        return ResearchTests.start(self)
    def respond(self,*args):
        from tests.test_research import ResearchTests
        return ResearchTests.respond(self,*args)

    def test_legacy_token_unchanged_and_new_pin_protected(self):
        from zar import research
        from unittest.mock import patch
        session=self.start()
        with patch('zar.research.chat',side_effect=self.respond):
            session=research.advance(self.root,session['id'],send=True)
        pinned=research.token(session)
        session.pop('memory_contract_version')
        session.pop('memory_selection_version', None)
        # This fixture predates both memory policy and connection pins.
        session.pop('transmission_contract', None)
        expected=research.digest(dict({k:session[k] for k in ('id','goal','profile','project_hash','records_hash','sources','command','metric_file','metric_key','outputs','experiment_id','run_context','deadline','max_calls','environment_hash')}, **{k:session[k] for k in ('revision_context','next_context','experiment_mode','baseline_id') if k in session}))
        self.assertEqual(research.token(session),expected)
        self.assertNotEqual(pinned,expected)
        research.save(self.root,session)
        with self.assertRaises(research.ResearchError):research.approve(self.root,session['id'],pinned)

    def test_record_change_during_memory_call_blocks_completion(self):
        from zar import research
        from zar.codec import loads,dumps
        from unittest.mock import patch
        session=self.start()
        with patch('zar.research.chat',side_effect=self.respond):session=research.advance(self.root,session['id'],send=True)
        research.approve(self.root,session['id'],session['approval_token'])
        research.run_session(self.root,session['id'])
        with patch('zar.research.chat',side_effect=self.respond):session=research.advance(self.root,session['id'],send=True)
        session=research.decide(self.root,session['id'],session['approval_token'])
        def mutate(*args):
            answer=self.respond(*args)
            path=self.root/'.autoresearch/experiments'/(session['experiment_id']+'.json')
            value=loads(path.read_text());value['hypothesis']='changed after request'
            path.write_text(dumps(value));return answer
        with patch('zar.research.chat',side_effect=mutate):
            with self.assertRaises(research.ResearchError):research.advance(self.root,session['id'],send=True)
        saved=research.status(self.root,session['id'])
        self.assertEqual(saved['state'],'blocked');self.assertNotIn('memory_assessment',saved)
        self.assertNotIn('memory',saved['outputs']);self.assertEqual(saved['calls'],7)

    def test_exact_decimal_assessment_survives_lossy_transport_and_reprojection(self):
        from decimal import Decimal
        import json
        from zar import research
        from zar.codec import dumps
        from unittest.mock import patch
        sent=[]
        def respond(profile,messages):
            payload=json.loads(messages[-1]['content'])
            answer=self.respond(profile,messages)
            if payload['role']=='memory':
                sent.append(payload['memory_evidence'])
                body=json.loads(answer['content'])
                body['contrast']=dict(effect='helped',applicability='synthetic only',
                    evidence=list(payload['memory_evidence']['handles']))
                answer['content']=dumps(body)
            return answer
        def finish():
            session=self.start()
            with patch('zar.research.chat',side_effect=respond):
                session=research.advance(self.root,session['id'],send=True)
            research.approve(self.root,session['id'],session['approval_token'])
            research.run_session(self.root,session['id'])
            with patch('zar.research.chat',side_effect=respond):
                session=research.advance(self.root,session['id'],send=True)
            session=research.decide(self.root,session['id'],session['approval_token'],select=True)
            with patch('zar.research.chat',side_effect=respond):
                return research.advance(self.root,session['id'],send=True)
        (self.root/'train.py').write_text('from pathlib import Path\nPath("metric.json").write_text(\'{"score":2e-400}\')\n')
        finish()
        (self.root/'metric.json').unlink()
        (self.root/'train.py').write_text('from pathlib import Path\nPath("metric.json").write_text(\'{"score":1e-400}\')\n')
        session=finish()
        self.assertEqual(sent[-1]['comparison']['improvement'],0)
        self.assertEqual(session['calls'],7)
        self.assertEqual(session['state'],'complete')
        self.assertEqual(session['memory_assessment']['observed_effect'],'helped')
        self.assertEqual(session['memory_assessment']['comparison']['improvement'],Decimal('1e-400'))
        from zar import cli
        experiments=cli.load_records(self.root,research.get_project(self.root)).records['experiment']
        projected=memory.project(session,experiments)['assessment']
        self.assertEqual(projected,session['memory_assessment'])
