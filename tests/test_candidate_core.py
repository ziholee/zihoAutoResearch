"""Candidate contracts preserve author reasoning and original version references."""
import copy
from decimal import Decimal
import unittest
from unittest.mock import patch
from zar.candidates import prepare_add, validate_candidate, validate_links, validate_creation, candidate_card

STAMP = '2026-01-01T00:00:00Z'
PROJECT = dict(environment=dict(os='linux', runtime='python', device='cpu'), comparison=None)

def body(**changes):
    value = dict(id='candidate-1', supersedes_id=None, status='selected', hypothesis='Test one change',
        parent_id=None, analysis='Observed failure motivates this test', evidence=[], exploratory_reason='Untested idea',
        expected_effect='May improve', expected_cost=dict(run_seconds=None, note='Unknown cost'),
        uncertainty='No run yet', decision_reason='Cheapest useful check',
        reconsideration=dict(trigger='initial', reason='First proposal'), memory_ids=[])
    value.update(changes)
    return value

def candidate(**changes):
    return prepare_add(body(**changes), STAMP, PROJECT)[0]

def records(*docs, experiments=None, memories=None):
    return dict(candidate={d['id']:d for d in docs}, experiment=experiments or {}, memory=memories or {})

def problems(data):
    found=[]
    validate_links(data, lambda doc, message, *args: found.append((doc['id'],message,args)))
    return found

class CandidateCoreTests(unittest.TestCase):
    def test_generated_metadata_and_evidence_requirement(self):
        doc, errors=prepare_add(body(), STAMP, PROJECT)
        self.assertEqual(errors, [])
        self.assertEqual(validate_candidate(doc), [])
        self.assertIsNot(doc['conditions']['environment'], PROJECT['environment'])
        for changes in [dict(exploratory_reason=None), dict(revision=1), dict(memory_ids=['a','a']),
                        dict(expected_cost=dict(run_seconds=Decimal('NaN'),note='unknown')),
                        dict(expected_cost=dict(run_seconds=-1,note='negative'))]:
            self.assertTrue(prepare_add(body(**changes), STAMP, PROJECT)[1], changes)

    def test_malformed_fields_never_crash(self):
        good=candidate()
        for key in good:
            for value in [None, [], {}, True]:
                doc=copy.deepcopy(good); doc[key]=value
                validate_candidate(doc)

    def test_corrections_identity_branch_retirement_and_cycles(self):
        a=candidate(); b=candidate(id='candidate-2',supersedes_id=a['id'],status='deferred')
        self.assertEqual(problems(records(a,b)), [])
        c=candidate(id='candidate-3',supersedes_id=a['id'])
        self.assertTrue(problems(records(a,b,c)))
        b['hypothesis']='Changed identity'; self.assertTrue(problems(records(a,b)))
        b['hypothesis']=a['hypothesis']; b['status']='retired'
        c['supersedes_id']=b['id']; self.assertTrue(problems(records(a,b,c)))
        self.assertTrue(problems(records(candidate(status='retired'))))
        a['supersedes_id']=b['id']; self.assertTrue(problems(records(a,b)))

    def test_creation_requires_current_selected_but_historical_link_is_warning(self):
        a=candidate(); b=candidate(id='candidate-2',supersedes_id=a['id'],status='deferred')
        exp=dict(id='exp',candidate_id=a['id'],hypothesis=a['hypothesis'],parent_id=None,**PROJECT)
        self.assertEqual(validate_creation(exp,records(a)), [])
        self.assertTrue(validate_creation(exp,records(a,b)))
        found=problems(records(a,b,experiments={'exp':exp}))
        self.assertTrue(found)
        self.assertTrue(all(item[2][-1]=='warning' for item in found))
        exp['hypothesis']='Unrelated'; self.assertTrue(problems(records(a,experiments={'exp':exp})))

    def test_missing_references_and_ancestry_cycle(self):
        a=candidate(parent_id='exp',memory_ids=['missing'])
        self.assertTrue(problems(records(a)))
        exp=dict(id='exp',candidate_id=a['id'],hypothesis=a['hypothesis'],parent_id='exp',**PROJECT)
        found=problems(records(a,experiments={'exp':exp}))
        self.assertTrue(any('cycle' in item[1] for item in found))

    def test_card_bounds_and_ancestor_outcomes_exclude_corrected_trials(self):
        a=candidate(analysis='x'*1000); b=candidate(id='candidate-2',supersedes_id=a['id'])
        exp=dict(id='exp',revision=1,candidate_id=a['id'],execution=dict(status='failed',score=None),baseline_id=None)
        corrected=copy.deepcopy(exp); corrected.update(id='exp-new', correction=dict(supersedes_id='exp'))
        data=records(a,b,experiments={'exp':exp,'exp-new':corrected})
        card=candidate_card(b,data)
        self.assertEqual(card['signals']['failed'],1)
        self.assertEqual(card['outcomes'][0]['id'],'exp-new')
        self.assertEqual(card['outcomes'][0]['candidate_id'],a['id'])
        self.assertEqual(card['outcomes'][0]['actual_cost_state'],'unknown')
        self.assertLessEqual(len(candidate_card(a,data)['author_summary']['analysis']),160)

    def test_signal_comparison_uses_declared_minimum_and_requires_comparable_scope(self):
        a=candidate()
        comparison=dict(id='metric',dataset_ref='data',split_ref='split',metric='error',direction='minimize',evaluation_ref='eval',min_delta=Decimal('0.1'))
        base=dict(id='base',revision=1,kind='baseline',parent_id=None,baseline_id=None,
                  comparison=comparison,environment=PROJECT['environment'],run_context=dict(scope='full',budget_ref='budget',seed=1),
                  code_ref='code',config_ref='config',command={},decision=None,execution=dict(status='succeeded',score=Decimal('1.0')))
        exp=copy.deepcopy(base); exp.update(id='exp',baseline_id='base',candidate_id=a['id'])
        exp['execution']['score']=Decimal('0.95')
        data=records(a,experiments={'base':base,'exp':exp})
        from zar.comparisons import compare, compare_pair
        full = compare(base, exp, data['experiment'])
        full.pop('repeats')
        self.assertEqual(compare_pair(base, exp, data['experiment']), full)
        with patch('zar.comparisons.repeat_summary', side_effect=AssertionError('unneeded repeat scan')):
            card=candidate_card(a,data)
        self.assertEqual(card['signals']['non_improving'],1)
        self.assertEqual(card['outcomes'][0]['comparison']['improvement'],Decimal('0.05'))
        exp['run_context']['scope']='proxy'
        self.assertEqual(candidate_card(a,data)['signals']['non_improving'],0)
        exp['run_context']['scope']='full'; exp['execution']['score']=Decimal('0.9')
        self.assertEqual(candidate_card(a,data)['signals']['non_improving'],0)

    def test_card_bounds_memory_evidence_and_stale_sources(self):
        proof=dict(kind='user_report',ref='x'*500,sha256=None,locator=None)
        a=candidate(memory_ids=['m1','m2','m3','m4'],evidence=[proof]*5)
        memories={key:dict(id=key,revision=1,status='retired',supersedes_id=None) for key in a['memory_ids']}
        card=candidate_card(a,records(a,memories=memories))
        self.assertEqual(len(card['memory_sources']),3)
        self.assertEqual(card['memories_omitted'],1)
        self.assertEqual(card['evidence_omitted'],2)
        self.assertEqual(card['stale_refs_omitted'],1)
        self.assertEqual(len(card['stale_refs']),3)
        self.assertTrue(card['truncated_fields'])

    def test_correction_cannot_precede_source_at_submicrosecond_precision(self):
        a=candidate(); b=candidate(id='candidate-2',supersedes_id=a['id'])
        a['created_at']=a['updated_at']='2026-01-01T00:00:00.123456789Z'
        b['created_at']=b['updated_at']='2026-01-01T00:00:00.123456788Z'
        self.assertTrue(any('predates' in item[1] for item in problems(records(a,b))))

    def test_forecast_timing_reports_backfilled_predictions_without_rejecting_history(self):
        a=candidate()
        a['created_at']=a['updated_at']='2026-01-01T00:00:00.123456789Z'
        exp=dict(id='exp',revision=1,candidate_id=a['id'],hypothesis=a['hypothesis'],parent_id=None,
                 execution=dict(status='failed',score=None,started_at='2026-01-01T00:00:00.123456788Z'),
                 baseline_id=None,**PROJECT)
        data=records(a,experiments={'exp':exp})
        found=problems(data)
        self.assertTrue(any(item[2] == ('candidate_forecast_timing', 'warning') for item in found))
        self.assertTrue(all(item[2][-1]=='warning' for item in found))
        self.assertEqual(candidate_card(a,data)['outcomes'][0]['forecast_timing'],'recorded_after_execution')
        exp['execution']['started_at']=a['created_at']
        self.assertEqual(candidate_card(a,data)['outcomes'][0]['forecast_timing'],'before_execution')
        self.assertEqual(problems(data),[])
        exp['execution']['started_at']=None
        self.assertEqual(candidate_card(a,data)['outcomes'][0]['forecast_timing'],'unknown')
        del exp['execution']['started_at']
        self.assertEqual(candidate_card(a,data)['outcomes'][0]['forecast_timing'],'unknown')
