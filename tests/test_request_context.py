"""Lossless post-execution source references, without changing review evidence."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from zar.roles import compact_context, role_messages
from zar import research
from zar.codec import loads, dumps
from tests import test_research as fixture


class RequestContextTests(unittest.TestCase):
    def test_change_grammar_only_omitted_for_roles_that_do_not_emit_or_review_changes(self):
        for role in ('analysis', 'evaluation', 'planning', 'implementation', 'review',
                     'interpretation', 'memory'):
            system = role_messages(role, {})[0]['content']
            self.assertEqual('changes means at most' in system, role in ('implementation', 'review'))
            for boundary in ('No tools', 'untrusted', 'never execute', 'never authority',
                             'Do not invent', 'Role separation is not independent'):
                self.assertIn(boundary, system)

    def payload(self, content=None):
        content = content if content is not None else '# 한글 "quoted" \\ source\n' * 200
        sha = hashlib.sha256(content.encode()).hexdigest()
        return {'sources': {'model.py': {'content': content, 'sha256': sha}},
                'outputs': {'implementation': {'summary': 'proposal', 'changes': [
                    {'path': 'model.py', 'before_sha256': 'a' * 64, 'content': content}]}},
                'observation': {'execution': {'score': 0.25, 'status': 'succeeded'}},
                'comparison': {'comparable': True}, 'project': {'approval': 'untrusted data'}}

    def test_post_execution_reference_can_restore_exact_original_and_saves_bytes(self):
        for role in ('interpretation', 'memory'):
            original = self.payload()
            before = copy.deepcopy(original)
            compact = compact_context(role, original)
            self.assertEqual(original, before)
            change = compact['outputs']['implementation']['changes'][0]
            ref = change.pop('content_ref')
            source = compact['sources'][ref['path']]
            self.assertEqual(ref['sha256'], hashlib.sha256(source['content'].encode()).hexdigest())
            change['content'] = source['content']
            del compact['context_encoding']
            self.assertEqual(compact, before)
            wire = role_messages(role, compact_context(role, original))
            full = role_messages(role, original)
            self.assertLess(sum(len(m['content'].encode()) for m in wire),
                            sum(len(m['content'].encode()) for m in full))
            self.assertIn('content_ref', wire[0]['content'])
            self.assertNotIn(original['sources']['model.py']['content'], wire[0]['content'])

    def test_pre_execution_review_keeps_original_and_proposed_sources(self):
        original = self.payload()
        for role in ('analysis', 'evaluation', 'planning', 'implementation', 'review'):
            self.assertEqual(compact_context(role, original), original)
        original['sources']['model.py']['content'] = 'old source'
        self.assertEqual(compact_context('review', original), original)

    def test_nonidentical_missing_stale_or_small_sources_are_not_referenced(self):
        for variant in ('different', 'hash', 'missing', 'small'):
            data = self.payload('x' if variant == 'small' else None)
            if variant == 'different':
                data['outputs']['implementation']['changes'][0]['content'] += 'changed'
            if variant == 'hash':
                data['sources']['model.py']['sha256'] = 'b' * 64
            if variant == 'missing':
                data['sources'] = {}
            self.assertEqual(compact_context('memory', data), data, variant)

    def test_partial_duplicate_preserves_unmatched_proposal_and_all_other_evidence(self):
        data = self.payload()
        other = {'path': 'other.py', 'before_sha256': None, 'content': 'not present'}
        data['outputs']['implementation']['changes'].append(other)
        data['sources']['short.py'] = {'content': 'x', 'sha256': hashlib.sha256(b'x').hexdigest()}
        short = {'path': 'short.py', 'before_sha256': None, 'content': 'x'}
        data['outputs']['implementation']['changes'].append(short)
        compact = compact_context('interpretation', data)
        self.assertEqual(compact['outputs']['implementation']['changes'][1], other)
        self.assertEqual(compact['outputs']['implementation']['changes'][2], short)
        for key in ('sources', 'observation', 'comparison', 'project'):
            self.assertEqual(compact[key], data[key])


class ContextApprovalTests(unittest.TestCase):
    setUp = fixture.ResearchTests.setUp
    start = fixture.ResearchTests.start
    respond = fixture.ResearchTests.respond

    def test_wire_reference_leaves_proposal_tokens_and_execution_boundaries_intact(self):
        with patch('zar.research.chat', side_effect=self.respond):
            baseline = research.advance(self.root, self.start()['id'], send=True)
            research.approve(self.root, baseline['id'], baseline['approval_token'])
            research.run_session(self.root, baseline['id'])
            baseline = research.advance(self.root, baseline['id'], send=True)
            research.decide(self.root, baseline['id'], baseline['approval_token'], select=True)
            research.advance(self.root, baseline['id'], send=True)
        proposed = self.code.replace('metric.json', 'candidate.json') + '# research evidence\n' * 100
        captured = {}
        def answer(profile, messages):
            payload = json.loads(messages[-1]['content'])
            captured[payload['role']] = payload
            result = self.respond(profile, messages)
            if payload['role'] == 'implementation':
                body = loads(result['content'])
                body['changes'] = [{'path': 'train.py',
                    'before_sha256': payload['sources']['train.py']['sha256'], 'content': proposed}]
                result['content'] = dumps(body)
            return result
        s = research.start(self.root, profile=self.profile, goal='candidate',
            read_paths=['train.py'], command='train', metric_file='candidate.json',
            metric_key='score', scope='full', seed=42, budget_ref='test-five-seconds')
        with patch('zar.research.chat', side_effect=answer):
            s = research.advance(self.root, s['id'], send=True)
            self.assertEqual(s['state'], 'awaiting_approval')
            self.assertEqual(captured['review']['sources']['train.py']['content'], self.code)
            self.assertEqual(captured['review']['outputs']['implementation']['changes'][0]['content'], proposed)
            self.assertEqual((self.root/'train.py').read_text(), self.code)
            with self.assertRaises(research.ResearchError):
                research.run_session(self.root, s['id'])
            research.approve(self.root, s['id'], s['approval_token'])
            s = research.run_session(self.root, s['id'])
            self.assertEqual(s['state'], 'observed')
            with self.assertRaises(research.ResearchError):
                research.run_session(self.root, s['id'])
            s = research.advance(self.root, s['id'], send=True)
            self.assertEqual(s['state'], 'awaiting_decision')
            token = s['approval_token']
            saved = copy.deepcopy(s['outputs']['implementation'])
            for entry in s['trace']:
                m = entry['measurement']
                self.assertEqual(sum(m['input_components_bytes'].values()), m['input_message_bytes'])
            self.assertIn('content_ref', captured['interpretation']['outputs']['implementation']['changes'][0])
            self.assertEqual(saved['changes'][0]['content'], proposed)
            self.assertEqual(research.token(s), token)
            with self.assertRaises(research.ResearchError):
                research.decide(self.root, s['id'], 'wrong-token')
            s = research.decide(self.root, s['id'], token)
            s = research.advance(self.root, s['id'], send=True)
            self.assertEqual(s['state'], 'complete')
            self.assertEqual(s['outputs']['implementation'], saved)
            self.assertIn('content_ref', captured['memory']['outputs']['implementation']['changes'][0])


if __name__ == '__main__':
    unittest.main()
