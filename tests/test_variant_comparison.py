"""Paused parent, bounded attempts and explicit recovery for role comparisons."""
import os
import time
import unittest
from unittest.mock import patch

import test_research as fixtures
from zar import research as r, variant_comparison as v
from zar.codec import dumps, loads


class VariantComparisonTests(unittest.TestCase):
    setUp = fixtures.ResearchTests.setUp
    start = fixtures.ResearchTests.start
    respond = fixtures.ResearchTests.respond

    def prepared(self, *, approve=True):
        s = self.start()
        (self.root / 'variant.md').write_text('Ask for missing evidence first.')
        c = v.prepare(self.root, s['id'], 'variant.md')
        if approve:
            c = v.approve(self.root, c['id'], c['approval_token'])
        return s, c

    def answer(self, profile, messages, remaining):
        return self.respond(profile, messages)

    def test_pair_consumes_parent_budget_without_outputs_then_normal_loop_resumes(self):
        s, c = self.prepared()
        with patch('zar.research.call_api', side_effect=self.answer) as call:
            result = v.advance(self.root, c['id'], send=True)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args_list[0].args[0], call.call_args_list[1].args[0])
        self.assertEqual(call.call_args_list[0].args[1][1], call.call_args_list[1].args[1][1])
        self.assertEqual(result['summary']['status'], 'hold')
        parent = r.load(self.root, s['id'])
        self.assertEqual((parent['state'], parent['calls'], parent['outputs']), ('planning', 2, {}))
        self.assertFalse((self.root / 'metric.json').exists())
        self.assertEqual((self.root / 'train.py').read_text(), self.code)
        with patch('zar.research.call_api', side_effect=self.answer):
            parent = r.advance(self.root, s['id'], send=True)
        self.assertEqual(parent['state'], 'awaiting_approval')
        self.assertEqual(parent['calls'], 7)

    def test_approval_send_and_parent_suspension_all_required(self):
        s, c = self.prepared(approve=False)
        with patch('zar.research.call_api') as call:
            with self.assertRaises(r.ResearchError):
                v.advance(self.root, c['id'], send=True)
            with self.assertRaises(r.ResearchError):
                v.approve(self.root, c['id'], 'wrong-token')
            v.approve(self.root, c['id'], c['approval_token'])
            with self.assertRaises(r.ResearchError):
                v.advance(self.root, c['id'])
            with self.assertRaises(r.ResearchError):
                r.advance(self.root, s['id'], send=True)
            call.assert_not_called()
        self.assertEqual(r.load(self.root, s['id'])['calls'], 0)

    def test_interruption_requires_confirmation_and_never_replays_attempted_arm(self):
        s, c = self.prepared()
        with patch('zar.research.call_api', side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                v.advance(self.root, c['id'], send=True)
        self.assertEqual(v.load(self.root, c['id'])['state'], 'calling')
        self.assertEqual(r.load(self.root, s['id'])['calls'], 1)
        with self.assertRaises(r.ResearchError):
            v.recover(self.root, c['id'])
        with self.assertRaises(r.ResearchError):
            v.cancel(self.root, c['id'])
        recovered = v.recover(self.root, c['id'], confirm_stopped=True)
        self.assertEqual(recovered['arms']['original']['state'], 'unknown')
        with patch('zar.research.call_api', side_effect=self.answer) as call:
            result = v.advance(self.root, c['id'], send=True)
        self.assertEqual(call.call_count, 1)
        self.assertIn('Ask for missing evidence first.', call.call_args.args[1][0]['content'])
        self.assertEqual(result['summary']['reason'], 'incomplete_or_invalid_pair')
        self.assertEqual(r.load(self.root, s['id'])['calls'], 2)

    def test_second_arm_interrupt_recovery_finishes_without_any_replay(self):
        s, c = self.prepared()
        def answer(profile, messages, remaining):
            if 'Ask for missing evidence first.' in messages[0]['content']:
                raise KeyboardInterrupt
            return self.answer(profile, messages, remaining)
        with patch('zar.research.call_api', side_effect=answer) as call:
            with self.assertRaises(r.ResearchError):
                v.advance(self.root, c['id'], send=True)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(v.load(self.root, c['id'])['state'], 'unknown')
        v.recover(self.root, c['id'], confirm_stopped=True)
        with patch('zar.research.call_api') as call:
            result = v.advance(self.root, c['id'], send=True)
            call.assert_not_called()
        self.assertEqual(result['arms']['original']['state'], 'validated')
        self.assertEqual(result['arms']['variant']['state'], 'unknown')
        self.assertEqual(r.load(self.root, s['id'])['calls'], 2)

    def test_response_processing_after_deadline_blocks_without_extending_parent(self):
        s, c = self.prepared()
        def answer(*args):
            result = self.answer(*args)
            if 'Ask for missing evidence first.' in args[1][0]['content']:
                late = patch('zar.variant_comparison.time.time', return_value=float(s['deadline']) + 1)
                late.start(); self.addCleanup(late.stop)
            return result
        with patch('zar.research.call_api', side_effect=answer) as call:
            with self.assertRaises(r.ResearchError):
                v.advance(self.root, c['id'], send=True)
        self.assertEqual(call.call_count, 2)
        result = v.load(self.root, c['id'])
        self.assertEqual((result['state'], result['error']), ('blocked', 'deadline_exceeded'))
        self.assertEqual(result['summary']['status'], 'hold')
        v.cancel(self.root, c['id'])
        parent = r.load(self.root, s['id'])
        self.assertEqual(float(parent['deadline']), float(s['deadline']))
        self.assertEqual(parent['outputs'], {})

    def test_variant_file_edit_invalidates_approved_pair(self):
        s, c = self.prepared()
        (self.root / 'variant.md').write_text('Different instructions')
        with patch('zar.research.call_api') as call:
            with self.assertRaises(r.ResearchError):
                v.advance(self.root, c['id'], send=True)
            call.assert_not_called()
        self.assertEqual(r.load(self.root, s['id'])['calls'], 0)

    def test_cancel_releases_parent_without_consuming_calls(self):
        s, c = self.prepared()
        result = v.cancel(self.root, c['id'])
        self.assertEqual(result['state'], 'cancelled')
        parent = r.load(self.root, s['id'])
        self.assertEqual((parent['state'], parent['calls']), ('planning', 0))
        self.assertNotIn('active_comparison', parent)

    def test_insufficient_calls_and_deadline_stop_before_transmission(self):
        s = self.start()
        (self.root / 'variant.md').write_text('Alternate')
        s['calls'] = s['max_calls'] - 1
        r.save(self.root, s)
        with self.assertRaises(r.ResearchError):
            v.prepare(self.root, s['id'], 'variant.md')
        s['calls'] = 0
        s['deadline'] = time.time() + 10
        r.save(self.root, s)
        c = v.prepare(self.root, s['id'], 'variant.md')
        v.approve(self.root, c['id'], c['approval_token'])
        with patch('zar.research.call_api') as call:
            with self.assertRaises(r.ResearchError):
                v.advance(self.root, c['id'], send=True)
            call.assert_not_called()
        self.assertEqual(r.load(self.root, s['id'])['calls'], 0)

    def test_selected_history_same_size_mtime_rewrite_blocks_before_call(self):
        history = dict(id='session-' + 'a' * 32, experiment_id=None,
                       created_at='2026-01-01', state='complete',
                       outputs={'memory': {'lesson': 'before'}})
        p = self.root / '.autoresearch/sessions' / (history['id'] + '.json')
        p.parent.mkdir(exist_ok=True)
        p.write_text(dumps(history))
        s, c = self.prepared()
        original = p.stat()
        p.write_text(p.read_text().replace('before', 'after!'))
        os.utime(p, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertEqual(p.stat().st_size, original.st_size)
        with patch('zar.research.call_api') as call:
            with self.assertRaises(r.ResearchError):
                v.advance(self.root, c['id'], send=True)
            call.assert_not_called()
        self.assertEqual(r.load(self.root, s['id'])['calls'], 0)

    def test_current_role_instructions_change_invalidates_approval(self):
        s, c = self.prepared(approve=False)
        with patch('zar.skill_variant.role_instructions', return_value='Changed role'):
            with self.assertRaises(ValueError):
                v.approve(self.root, c['id'], c['approval_token'])
        self.assertEqual(r.load(self.root, s['id'])['calls'], 0)

    def test_unknown_evidence_invalidates_response_without_applying(self):
        s, c = self.prepared()
        def answer(*args):
            result = self.answer(*args)
            body = loads(result['content'])
            body['evidence'] = ['invented-evidence']
            result['content'] = dumps(body)
            return result
        with patch('zar.research.call_api', side_effect=answer):
            result = v.advance(self.root, c['id'], send=True)
        self.assertEqual(result['arms']['original']['state'], 'invalid')
        self.assertEqual(result['arms']['variant']['state'], 'invalid')
        self.assertEqual(result['summary']['status'], 'hold')
        self.assertEqual(r.load(self.root, s['id'])['outputs'], {})

    def test_source_changes_during_call_block_second_arm(self):
        s, c = self.prepared()
        def answer(*args):
            result = self.answer(*args)
            (self.root / 'train.py').write_text('# changed during call')
            return result
        with patch('zar.research.call_api', side_effect=answer) as call:
            with self.assertRaises(r.ResearchError):
                v.advance(self.root, c['id'], send=True)
        self.assertEqual(call.call_count, 1)
        result = v.load(self.root, c['id'])
        self.assertEqual((result['state'], result['error']), ('blocked', 'inputs_changed'))
        self.assertEqual(result['arms']['variant']['state'], 'pending')
        self.assertEqual(r.load(self.root, s['id'])['outputs'], {})


    def test_completed_pair_recovers_parent_release_write_failure_without_calls(self):
        s, c = self.prepared()
        original_save = r.save
        def fail_release(root, session):
            if session['state'] == 'planning':
                raise OSError('injected parent release failure')
            original_save(root, session)
        with patch('zar.research.call_api', side_effect=self.answer) as call, \
                patch('zar.research.save', side_effect=fail_release):
            with self.assertRaises(OSError):
                v.advance(self.root, c['id'], send=True)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(v.load(self.root, c['id'])['state'], 'complete')
        self.assertEqual(r.load(self.root, s['id'])['state'], 'comparing')
        with patch('zar.research.call_api') as call:
            result = v.recover(self.root, c['id'], confirm_stopped=True)
            call.assert_not_called()
        self.assertEqual(result['state'], 'complete')
        parent = r.load(self.root, s['id'])
        self.assertEqual((parent['state'], parent['calls'], parent['outputs']), ('planning', 2, {}))
        self.assertNotIn('active_comparison', parent)

    def test_baseline_interpretation_and_memory_pairs_remain_separate_held_proposals(self):
        s = r.start(self.root, profile=self.profile, goal='test', read_paths=['train.py'],
                    command='train', metric_file='metric.json', metric_key='score',
                    max_calls=20, session_seconds=120, scope='full', seed=42,
                    budget_ref='test-five-seconds', mode='baseline')
        with patch('zar.research.call_api', side_effect=self.answer):
            s = r.advance(self.root, s['id'], send=True)
        r.approve(self.root, s['id'], s['approval_token'])
        s = r.run_session(self.root, s['id'])
        self.assertEqual(s['state'], 'observed')
        (self.root / 'variant.md').write_text('State uncertainty before the conclusion.')
        before_outputs = s['outputs']
        c = v.prepare(self.root, s['id'], 'variant.md')
        self.assertEqual(c['bundle']['role'], 'interpretation')
        v.approve(self.root, c['id'], c['approval_token'])
        with patch('zar.research.call_api', side_effect=self.answer):
            pair = v.advance(self.root, c['id'], send=True)
        self.assertEqual(pair['summary']['status'], 'hold')
        self.assertFalse(pair['summary']['automatic_selection'])
        self.assertTrue(all(a['state'] == 'validated' for a in pair['arms'].values()))
        parent = r.load(self.root, s['id'])
        self.assertEqual(parent['outputs'], before_outputs)
        self.assertEqual(parent['state'], 'observed')
        with patch('zar.research.call_api', side_effect=self.answer):
            parent = r.advance(self.root, s['id'], send=True)
        self.assertEqual(parent['state'], 'awaiting_decision')
        parent = r.decide(self.root, s['id'], parent['approval_token'])
        self.assertEqual(parent['state'], 'remembering')
        before_outputs = parent['outputs']
        c = v.prepare(self.root, s['id'], 'variant.md')
        self.assertEqual(c['bundle']['role'], 'memory')
        v.approve(self.root, c['id'], c['approval_token'])
        with patch('zar.research.call_api', side_effect=self.answer):
            pair = v.advance(self.root, c['id'], send=True)
        self.assertEqual(pair['summary']['status'], 'hold')
        self.assertFalse(pair['summary']['automatic_selection'])
        for arm in pair['arms'].values():
            self.assertEqual(arm['state'], 'validated')
            self.assertEqual(arm['assessment']['status'], 'hold')
        parent = r.load(self.root, s['id'])
        self.assertEqual(parent['outputs'], before_outputs)
        self.assertNotIn('memory', parent['outputs'])
        self.assertEqual(parent['state'], 'remembering')
        self.assertIsNone(r.get_project(self.root)['selected_experiment_id'])
        with patch('zar.research.call_api', side_effect=self.answer):
            parent = r.advance(self.root, s['id'], send=True)
        self.assertEqual(parent['state'], 'complete')
        self.assertEqual(parent['memory_assessment']['status'], 'hold')
        self.assertEqual(parent['calls'], 11)


if __name__ == '__main__':
    unittest.main()
