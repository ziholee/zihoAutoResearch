"""Synthetic failure memory contracts; recorded support is not verified causality."""
from copy import deepcopy
import unittest

from zar.memories import prepare_add, validate_memory, validate_links, memory_card

STAMP = '2026-10-11T00:00:00Z'
PROOF = dict(kind='fixture', ref='failure.log', locator=None, sha256=None)
RESOLUTION = dict(kind='fixture', ref='resolution.log', locator=None, sha256=None)


def experiment(identifier='failed-1', status='failed'):
    return dict(id=identifier, revision=1,
        environment=dict(os='linux', runtime='Python 3.11', device='CPU'),
        comparison=dict(id='cmp', dataset_ref='data', split_ref='split', metric='loss',
                        direction='minimize', evaluation_ref='eval', min_delta=0),
        code_ref='code-1', config_ref='config-1',
        run_context=dict(scope='proxy', seed=1, budget_ref='budget-1'),
        execution=dict(status=status, evidence=[deepcopy(PROOF if status == 'failed' else RESOLUTION)]),
        decision=None)


def body(**changes):
    value = dict(id='memory-1', supersedes_id=None, status='active', cause='Author diagnosis',
                 remedy=None, limitation='Synthetic observation; no causal verification.',
                 evidence=[deepcopy(PROOF)], failure_experiment_id='failed-1', resolution_experiment_id=None)
    value.update(changes)
    return value


class MemoryCoreTests(unittest.TestCase):
    def setUp(self):
        self.experiments = {'failed-1': experiment(), 'fixed-1': experiment('fixed-1', 'succeeded')}

    def prepare(self, **changes):
        doc, errors = prepare_add(body(**changes), STAMP, self.experiments)
        self.assertEqual(errors, [])
        return doc

    def issues(self, *docs):
        errors = []
        validate_links({'experiment': self.experiments, 'memory': {d['id']: d for d in docs}},
                       lambda doc, message, code='conflict', severity='error': errors.append((code, severity, message)))
        return errors

    def test_author_cannot_supply_conditions_or_metadata_and_snapshot_is_copied(self):
        doc = self.prepare()
        self.assertEqual(doc['conditions']['code_ref'], 'code-1')
        self.experiments['failed-1']['environment']['runtime'] = 'changed'
        self.assertEqual(doc['conditions']['environment']['runtime'], 'Python 3.11')
        for extra in ({'revision': 9}, {'conditions': {}}):
            self.assertTrue(prepare_add(body(**extra), STAMP, self.experiments)[1])

    def test_sources_require_failure_and_resolution_evidence(self):
        doc = self.prepare(resolution_experiment_id='fixed-1', remedy='Author proposed fix')
        self.assertTrue(self.issues(doc))
        doc['evidence'].append(deepcopy(RESOLUTION))
        self.assertEqual(self.issues(doc), [])
        doc['evidence'] = [deepcopy(RESOLUTION)]
        self.assertTrue(self.issues(doc))
        doc['evidence'].insert(0, deepcopy(PROOF))
        self.experiments['fixed-1']['environment']['runtime'] = 'different'
        self.assertTrue(self.issues(doc))

    def test_absent_nonfailure_and_mutated_conditions_rejected(self):
        self.assertTrue(prepare_add(body(failure_experiment_id='absent'), STAMP, self.experiments)[1])
        doc = self.prepare()
        doc['conditions']['code_ref'] = 'fake'
        self.assertTrue(self.issues(doc))
        doc['conditions']['code_ref'] = 'code-1'
        self.experiments['failed-1']['execution']['status'] = 'succeeded'
        self.assertTrue(self.issues(doc))

    def test_correction_retires_without_mutation_and_cannot_branch_or_revive(self):
        original = self.prepare()
        retired = self.prepare(id='memory-2', supersedes_id='memory-1', status='retired')
        self.assertEqual(self.issues(original, retired), [])
        branch = self.prepare(id='memory-3', supersedes_id='memory-1')
        self.assertTrue(self.issues(original, retired, branch))
        branch['supersedes_id'] = 'memory-2'
        self.assertTrue(self.issues(original, retired, branch))
        retired['supersedes_id'] = None
        self.assertTrue(self.issues(retired))

    def test_correction_cycles_and_reversed_time_rejected(self):
        first = self.prepare()
        second = self.prepare(id='memory-2', supersedes_id='memory-1')
        second['created_at'] = second['updated_at'] = '2026-10-10T00:00:00Z'
        self.assertTrue(self.issues(first, second))
        first['supersedes_id'] = 'memory-2'
        self.assertTrue(self.issues(first, second))

    def test_required_limitation_and_remedy_and_immutable_revision(self):
        for changes in ({'limitation': ''}, {'evidence': []}, {'resolution_experiment_id': 'fixed-1'}):
            self.assertTrue(prepare_add(body(**changes), STAMP, self.experiments)[1])
        doc = self.prepare()
        doc['revision'] = 2
        self.assertTrue(validate_memory(doc))

    def test_superseded_source_warns_without_retargeting(self):
        doc = self.prepare()
        corrected = experiment('failed-2')
        corrected['correction'] = dict(supersedes_id='failed-1')
        self.experiments['failed-2'] = corrected
        issues = self.issues(doc)
        self.assertEqual([(c, s) for c, s, _ in issues], [('memory_source_superseded', 'warning')])
        self.assertEqual(doc['failure_experiment_id'], 'failed-1')
        out = memory_card(doc, self.experiments, self.experiments['failed-1'])
        self.assertTrue(out['stale_source'])
        self.assertEqual(out['applicability'], 'mismatch')

    def test_discarded_success_is_failure_source_but_not_its_own_resolution(self):
        failed = self.experiments['failed-1']
        failed['execution']['status'] = 'succeeded'
        failed['decision'] = dict(status='discard', evidence=[deepcopy(PROOF)])
        doc = self.prepare()
        self.assertEqual(self.issues(doc), [])
        doc.update(resolution_experiment_id='failed-1', remedy='Unsupported self reference')
        self.assertTrue(self.issues(doc))

    def test_historical_discard_support_survives_current_hold_or_keep(self):
        failed = self.experiments['failed-1']
        failed['execution'].update(status='succeeded', evidence=[])
        failed['decision_history'] = [dict(decided_at=STAMP,
            decision=dict(status='discard', evidence=[deepcopy(PROOF)]))]
        doc = self.prepare()
        for status in ('hold', 'keep'):
            failed['decision'] = dict(status=status, evidence=[])
            self.assertEqual(self.issues(doc), [])
        failed['decision_history'][0]['decision']['status'] = 'hold'
        self.assertTrue(self.issues(doc))

    def test_resolution_scope_and_budget_mismatch_rejected_seed_may_differ(self):
        doc = self.prepare(resolution_experiment_id='fixed-1', remedy='Author fix',
                           evidence=[deepcopy(PROOF), deepcopy(RESOLUTION)])
        resolution = self.experiments['fixed-1']
        resolution['run_context']['seed'] = 2
        self.assertEqual(self.issues(doc), [])
        self.assertEqual(memory_card(doc, self.experiments, self.experiments['failed-1'])['resolution_scope'], 'matched')
        for key, value in (('scope', 'full'), ('budget_ref', 'other-budget')):
            original = resolution['run_context'][key]
            resolution['run_context'][key] = value
            self.assertTrue(self.issues(doc))
            out = memory_card(doc, self.experiments, self.experiments['failed-1'])
            self.assertEqual(out['resolution_scope'], 'mismatch')
            self.assertEqual(out['applicability'], 'mismatch')
            resolution['run_context'][key] = original

    def test_legacy_resolution_scope_is_allowed_but_recall_stays_unknown(self):
        doc = self.prepare(resolution_experiment_id='fixed-1', remedy='Author fix',
                           evidence=[deepcopy(PROOF), deepcopy(RESOLUTION)])
        self.experiments['fixed-1'].pop('run_context')
        self.assertEqual(self.issues(doc), [])
        out = memory_card(doc, self.experiments, self.experiments['failed-1'])
        self.assertEqual(out['resolution_scope'], 'unknown')
        self.assertEqual(out['applicability'], 'unknown')

    def test_evidence_locator_and_hash_must_match_original_exactly(self):
        doc = self.prepare()
        doc['evidence'][0]['locator'] = 'different section'
        self.assertTrue(self.issues(doc))
        doc['evidence'][0]['locator'] = None
        doc['evidence'][0]['sha256'] = 'a' * 64
        self.assertTrue(self.issues(doc))

    def test_correction_cannot_switch_failure_even_with_identical_conditions(self):
        first = self.prepare()
        self.experiments['failed-2'] = experiment('failed-2')
        second = self.prepare(id='memory-2', supersedes_id='memory-1', failure_experiment_id='failed-2')
        self.assertTrue(self.issues(first, second))

    def test_projection_without_anchor_or_known_environment_is_unknown(self):
        doc = self.prepare()
        out = memory_card(doc, self.experiments, None)
        self.assertEqual(set(out['condition_matches'].values()), {'unknown'})
        self.assertEqual(out['applicability'], 'unknown')
        anchor = deepcopy(self.experiments['failed-1'])
        anchor['environment']['device'] = None
        out = memory_card(doc, self.experiments, anchor)
        self.assertEqual(out['condition_matches']['environment'], 'unknown')
        self.assertEqual(out['failure_source']['record_id'], 'failed-1')
        self.assertEqual(out['failure_source']['record_revision'], 1)
        self.assertIsNone(out['resolution_source'])
        self.assertEqual(out['resolution_state'], 'unresolved')

    def test_projection_bounds_and_unknown_scope_do_not_claim_verification(self):
        doc = self.prepare(cause='x' * 200, evidence=[deepcopy(PROOF)] * 4)
        anchor = deepcopy(self.experiments['failed-1'])
        anchor['code_ref'] = 'different'
        anchor.pop('run_context')
        out = memory_card(doc, self.experiments, anchor)
        self.assertEqual(out['condition_matches']['code_ref'], 'mismatch')
        self.assertEqual(out['applicability'], 'mismatch')
        self.assertEqual(out['condition_matches']['run_context'], 'unknown')
        self.assertFalse(out['evidence_checked'])
        self.assertNotIn('verified', out)
        self.assertLessEqual(len(out['author_summary']['cause']), 160)
        self.assertEqual(len(out['evidence']), 3)
        self.assertEqual(out['evidence_omitted'], 1)
        self.assertEqual(out['evidence'][0]['pointer'], '/evidence/0')
        self.assertTrue(out['truncated_fields'])

    def test_known_mismatch_is_not_hidden_by_other_unknown_fields(self):
        doc = self.prepare()
        for key, changed in [('environment', dict(os='windows', runtime='Python 3.11', device=None)),
                             ('run_context', dict(scope='full', seed=None, budget_ref='budget-1'))]:
            with self.subTest(key=key):
                anchor = deepcopy(self.experiments['failed-1'])
                anchor[key] = changed
                out = memory_card(doc, self.experiments, anchor)
                self.assertEqual(out['condition_matches'][key], 'mismatch')
                self.assertEqual(out['applicability'], 'mismatch')
        anchor = deepcopy(self.experiments['failed-1'])
        anchor['environment']['device'] = None
        self.assertEqual(memory_card(doc, self.experiments, anchor)['applicability'], 'unknown')


if __name__ == '__main__':
    unittest.main()
