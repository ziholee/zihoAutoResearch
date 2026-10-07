import copy
from decimal import Decimal

from test_experiments import ExperimentHarness
from zar.codec import loads, dumps


class ComparisonTests(ExperimentHarness):
    def write_input(self, document):
        path = self.root / 'input.json'
        path.write_text(dumps(document), encoding='utf-8')
        return path

    def complete(self, id, score, **changes):
        body = self.create(id, **changes)
        body.setdefault('run_context', dict(scope='full', seed=1, budget_ref='epochs-10'))
        self.register(body)
        doc = loads(self.record(id).read_text())
        doc = self.success(doc); doc['execution']['score'] = Decimal(score)
        self.invoke('experiment','update',id,'--file',str(self.write_input(doc)))
        return loads(self.record(id).read_text())

    def compare(self, base='base', candidate='candidate'):
        return self.invoke('experiment','compare',base,candidate)['data']

    def decide(self, doc, status='keep', validity='valid', expected=0):
        body = dict(revision=doc['revision'], decision=dict(status=status,validity=validity,
                    reason='Explicit human assessment',evidence=doc['execution']['evidence'],
                    next_action='Check observations' if status=='hold' else None))
        return self.invoke('experiment','decide',doc['id'],'--file',str(self.write_input(body)),expected=expected)

    def test_exact_decimal_and_no_automatic_selection(self):
        project=loads(self.stored.read_text()); project['comparison'].update(id='comparison-exact',min_delta=Decimal('0.1'))
        self.invoke('project','set','--file',str(self.write_input(project)))
        self.complete('base','1.2'); candidate=self.complete('candidate','1.1',kind='performance',baseline_id='base')
        before=self.record('candidate').read_bytes(); project_before=self.stored.read_bytes()
        result=self.compare()
        self.assertTrue(result['comparable']); self.assertEqual(result['improvement'],Decimal('0.1'))
        self.assertTrue(result['meets_min_delta'])
        self.assertEqual(self.record('candidate').read_bytes(),before)
        output=self.decide(candidate)['data']['experiment']
        self.assertEqual(len(output['decision_history']),1)
        self.assertEqual(self.stored.read_bytes(),project_before)
        self.decide(candidate,expected=3)
        output=self.decide(output,status='hold')['data']['experiment']
        self.assertEqual(len(output['decision_history']),2)

    def test_long_decimal_tie_and_maximize(self):
        project=loads(self.stored.read_text()); project['comparison'].update(id='comparison-max',direction='maximize',min_delta=0)
        self.invoke('project','set','--file',str(self.write_input(project)))
        self.complete('base','1.000000000000000000000000000001')
        self.complete('candidate','1.000000000000000000000000000002')
        self.assertEqual(self.compare()['improvement'],Decimal('1e-30'))
        tie=self.complete('tie','1.000000000000000000000000000001',kind='performance',baseline_id='base')
        self.decide(tie)
        self.assertFalse(self.compare('base','tie')['meets_min_delta'])

    def test_scope_mismatch_and_legacy_unknown_do_not_compute_delta(self):
        self.complete('base','2')
        doc=self.complete('candidate','1',run_context=dict(scope='proxy',seed=2,budget_ref='epochs-10'))
        result=self.compare(); self.assertFalse(result['comparable']); self.assertIsNone(result['raw_delta'])
        self.assertIn('scope_mismatch',result['reasons'])
        doc.pop('run_context'); self.record('candidate').write_text(dumps(doc))
        result=self.compare(); self.assertIn('run_context_unknown',result['reasons'])
        self.assertIsNone(result['improvement'])

    def test_mismatched_environment_budget_and_comparison(self):
        self.complete('base','2'); doc=self.complete('candidate','1')
        for field,value,reason in [('environment',dict(os='windows',runtime='python',device='cpu'),'environment_mismatch'),
                                   ('run_context',dict(scope='full',seed=1,budget_ref='epochs-20'),'budget_mismatch')]:
            changed=copy.deepcopy(doc); changed[field]=value
            self.record('candidate').write_text(dumps(changed))
            self.assertIn(reason,self.compare()['reasons'])
        changed=copy.deepcopy(doc); changed['comparison'].update(id='other',split_ref='other')
        self.record('candidate').write_text(dumps(changed))
        self.assertIn('comparison_mismatch',self.compare()['reasons'])

    def test_unknown_context_cannot_keep_but_can_hold(self):
        self.complete('base','2'); doc=self.complete('candidate','1',kind='performance',baseline_id='base',run_context=None)
        self.decide(doc,expected=3)
        self.decide(doc,status='hold',validity='not_comparable')

    def test_corrected_baseline_requires_reassessment(self):
        base=self.complete('base','2'); candidate=self.complete('candidate','1',kind='performance',baseline_id='base')
        body=dict(id='base-fixed',revision=base['revision'],execution=copy.deepcopy(base['execution']),
                  reason='Result typo',evidence=base['execution']['evidence'])
        body['execution']['score']=Decimal('0.5')
        self.invoke('experiment','correct','base','--file',str(self.write_input(body)))
        self.assertIn('baseline_superseded',self.compare('base-fixed','candidate')['reasons'])
        self.decide(candidate,expected=3)

    def test_confirmation_count_variance_and_evidence_limits(self):
        self.complete('base','2'); self.complete('candidate','1')
        first=self.compare()['repeats']['candidate']
        self.assertEqual(first['count'],1); self.assertIsNone(first['sample_variance'])
        self.complete('repeat','3',kind='confirmation',parent_id='candidate',baseline_id='base',
                      run_context=dict(scope='full',seed=2,budget_ref='epochs-10'))
        stats=self.compare()['repeats']['candidate']
        self.assertEqual(stats['count'],2)
        self.assertEqual(stats['sample_variance'],{'numerator':2,'denominator':1})
        self.assertEqual(stats['distinct_known_seeds'],2)
        self.assertIn('evidence_unverified',[d['code'] for d in self.invoke('experiment','compare','base','candidate')['diagnostics']])

    def test_context_immutable_and_invalid_redecision_allowed(self):
        doc=self.complete('base','2')
        changed=copy.deepcopy(doc); changed['run_context']['scope']='proxy'
        self.invoke('experiment','update','base','--file',str(self.write_input(changed)),expected=3)
        doc=self.decide(doc,status='discard',validity='invalid')['data']['experiment']
        self.decide(doc)

    def test_repeats_preserve_correction_lineage_and_exclude_changed_commands(self):
        self.complete('base','4'); candidate=self.complete('candidate','1')
        repeat=self.complete('repeat','3',kind='confirmation',parent_id='candidate',baseline_id='base')
        body=dict(id='candidate-fixed',revision=candidate['revision'],execution=copy.deepcopy(candidate['execution']),
                  reason='Result typo',evidence=candidate['execution']['evidence'])
        body['execution']['score']=Decimal('2')
        self.invoke('experiment','correct','candidate','--file',str(self.write_input(body)))
        self.assertEqual(self.compare('base','candidate-fixed')['repeats']['candidate']['count'],2)
        repeat['command']['argv']=['different-training-command']
        self.record('repeat').write_text(dumps(repeat))
        self.assertEqual(self.compare('base','candidate-fixed')['repeats']['candidate']['count'],1)

    def test_selected_decision_change_requires_deselect_and_failure_cannot_keep(self):
        base=self.complete('base','2')
        base=self.decide(base)['data']['experiment']
        project=loads(self.stored.read_text()); project['selected_experiment_id']='base'
        self.invoke('project','set','--file',str(self.write_input(project)))
        before=self.record('base').read_bytes()
        self.decide(base,status='hold',expected=3)
        self.assertEqual(self.record('base').read_bytes(),before)
        self.register(self.create('failed',run_context=dict(scope='full',seed=None,budget_ref='epochs-10')))
        doc=loads(self.record('failed').read_text())
        doc['execution'].update(status='failed',started_at='2026-01-01T00:00:00Z',finished_at='2026-01-01T00:01:00Z',
                                exit_code=1,note='simulated failure',evidence=base['execution']['evidence'])
        self.invoke('experiment','update','failed','--file',str(self.write_input(doc)))
        doc=loads(self.record('failed').read_text()); self.decide(doc,expected=3)
        self.decide(doc,status='discard',validity='invalid')

    def test_corrected_confirmation_is_counted_once_and_seed_unknown_is_explicit(self):
        self.complete('base','4'); self.complete('candidate','1')
        repeat=self.complete('repeat','3',kind='confirmation',parent_id='candidate',baseline_id='base',
                             run_context=dict(scope='full',seed=None,budget_ref='epochs-10'))
        body=dict(id='repeat-fixed',revision=repeat['revision'],execution=copy.deepcopy(repeat['execution']),
                  reason='Result typo',evidence=repeat['execution']['evidence'])
        body['execution']['score']=Decimal('2')
        self.invoke('experiment','correct','repeat','--file',str(self.write_input(body)))
        stats=self.compare()['repeats']['candidate']
        self.assertEqual(stats['experiment_ids'],['candidate','repeat-fixed'])
        self.assertEqual(stats['count'],2); self.assertEqual(stats['unknown_seed_count'],1)
        self.assertEqual(stats['sample_variance'],{'numerator':1,'denominator':2})

    def test_unknown_environment_invalid_assessment_and_missing_evidence_are_distinct(self):
        self.complete('base','2'); doc=self.complete('candidate','3')
        self.assertFalse(self.compare()['meets_min_delta'])
        changed=copy.deepcopy(doc); changed['environment']['device']=None
        self.record('candidate').write_text(dumps(changed))
        self.assertIn('environment_unknown',self.compare()['reasons'])
        self.assertEqual(self.compare()['repeats']['candidate']['count'],0)
        changed=copy.deepcopy(doc)
        changed['execution']['evidence']=[dict(kind='file',ref='missing-log.txt',locator=None,sha256=None)]
        self.record('candidate').write_text(dumps(changed))
        result=self.invoke('experiment','compare','base','candidate')
        self.assertTrue(result['data']['comparable'])
        self.assertIn('evidence_missing',[d['code'] for d in result['diagnostics']])
        self.decide(changed,status='discard',validity='invalid')
        self.assertIn('candidate_invalid_decision',self.compare()['reasons'])

    def test_invalid_context_and_no_keep_evidence_do_not_write(self):
        body=self.create('bad',run_context=dict(scope='full',seed=True,budget_ref='budget'))
        self.register(body,expected=2)
        self.assertFalse(self.record('bad').exists())
        doc=self.complete('base','1'); before=self.record('base').read_bytes()
        body=dict(revision=doc['revision'],decision=dict(status='keep',validity='valid',reason='No proof',evidence=[],next_action=None))
        self.invoke('experiment','decide','base','--file',str(self.write_input(body)),expected=2)
        self.assertEqual(self.record('base').read_bytes(),before)
