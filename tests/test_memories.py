"""Public failure-memory contract: immutable records and scoped recall."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

from test_experiments import ExperimentHarness
from zar.cli import main


class MemoryTests(ExperimentHarness):
    def setUp(self):
        super().setUp()
        self.register()
        doc = json.loads(self.record().read_text())
        self.proof = dict(kind='user_report', ref='simulated failure', locator=None, sha256=None)
        doc['execution'].update(status='failed', started_at='2026-01-01T00:00:00Z', note='simulated error', finished_at='2026-01-01T00:01:00Z',
                                exit_code=1, evidence=[self.proof])
        self.update(doc)

    def body(self, identifier='memory-1', **changes):
        value = dict(id=identifier, supersedes_id=None, status='active', cause='Recorded failure cause',
                     remedy=None, limitation='Synthetic observation; causal explanation not independently verified',
                     failure_experiment_id='exp-1', resolution_experiment_id=None, evidence=[self.proof])
        value.update(changes)
        return value

    def add(self, body=None, expected=0):
        return self.invoke('memory', 'add', '--file', str(self.write_input(body or self.body())), expected=expected)

    def memory(self, identifier='memory-1'):
        return self.stored.parent / 'memories' / (identifier + '.json')

    def test_add_preserves_originals_and_legacy_missing_directory(self):
        directory = self.stored.parent / 'memories'
        if directory.exists(): directory.rmdir()
        before = {p: p.read_bytes() for p in self.stored.parent.rglob('*.json')}
        saved = self.add()['data']['memory']
        self.assertEqual(saved['revision'], 1)
        self.assertEqual(saved['conditions']['code_ref'], 'code-1')
        self.assertEqual(saved['conditions']['environment']['os'], 'linux')
        self.assertTrue(self.memory().is_file())
        self.assertTrue(all(p.read_bytes() == value for p, value in before.items()))
        self.assertEqual(self.invoke('status')['data']['budget_used'], 1)

    def test_correction_retirement_preserve_source_and_exclude_recall(self):
        self.add(); original = self.memory().read_bytes()
        self.add(self.body('memory-2', supersedes_id='memory-1', cause='Corrected explanation'))
        self.assertEqual(self.memory().read_bytes(), original)
        self.add(self.body('branch', supersedes_id='memory-1'), expected=3)
        self.add(self.body('memory-3', supersedes_id='memory-2', status='retired'))
        self.add(self.body('revive', supersedes_id='memory-3'), expected=3)
        context = self.invoke('context', '--memories', '--experiment', 'exp-1')['data']
        self.assertEqual(context['cards'], [])
        self.assertEqual(context['memory_counts'], {'total': 3, 'active': 0, 'retired': 1, 'superseded': 2})
        self.invoke('report', '--output', 'memory.md')
        report = (self.stored.parent / 'reports/memory.md').read_text()
        for identifier in ('memory-1', 'memory-2', 'memory-3'):
            self.assertIn(identifier, report)
        self.assertIn('.autoresearch/memories/memory-1.json', report)
        self.assertIn('폐기된 기억 (정정 끝점)', report)

    def test_reject_missing_links_generated_metadata_and_global_collision(self):
        for body, status in ((self.body(failure_experiment_id='missing'), 3),
                             (self.body(resolution_experiment_id='missing', remedy='fix'), 3),
                             (self.body('exp-1'), 3), (self.body(schema_version=1), 2),
                             (self.body(evidence=[]), 2)):
            with self.subTest(body=body): self.add(body, expected=status)
        self.assertFalse(self.memory().exists())

    def test_atomic_failure_and_symlink_directory_preserve_originals(self):
        self.add(); before = self.memory().read_bytes()
        body = self.body('memory-2', supersedes_id='memory-1')
        with patch('zar.storage.os.replace', side_effect=OSError('simulated replace failure')):
            status = main(['memory', 'add', '--file', str(self.write_input(body)), '--project', str(self.project), '--json'])
        self.assertEqual(status, 4)
        self.assertFalse(self.memory('memory-2').exists())
        self.assertEqual(self.memory().read_bytes(), before)
        directory = self.memory().parent
        renamed = directory.with_name('saved-memories'); directory.rename(renamed)
        directory.symlink_to(renamed, target_is_directory=True)
        self.invoke('context', '--memories', expected=3)

    def test_bounded_pages_snapshot_and_default_recall_hint(self):
        for index in range(8): self.add(self.body(f'memory-{index}', cause='실패' * 300))
        original = {p: p.read_bytes() for p in self.memory().parent.glob('*.json')}
        default = self.invoke('context')['data']
        self.assertEqual(default['memory_counts']['active'], 8)
        offset, seen, snapshot = 0, [], None
        while offset is not None:
            args = ['context', '--memories', '--experiment', 'exp-1', '--limit', '3', '--offset', str(offset), '--max-bytes', '8192']
            if snapshot: args.extend(['--snapshot', snapshot])
            result = self.invoke(*args); data = result['data']
            from zar.codec import dumps
            self.assertLessEqual(len(dumps(result, ensure_ascii=True).encode('ascii')) + 1, 8192)
            snapshot = data['snapshot_id']
            seen.extend(c['id'] for c in data['cards'])
            self.assertTrue(all(c['source'].startswith('.autoresearch/memories/') for c in data['cards']))
            self.assertTrue(all(c['truncated_fields'] for c in data['cards']))
            self.assertFalse(data['safeguards']['evidence_checked'])
            offset = data['page']['next_offset']
        self.assertEqual(len(seen), 8); self.assertEqual(len(set(seen)), 8)
        self.assertTrue(all(p.read_bytes() == value for p, value in original.items()))
        self.add(self.body('memory-new'))
        self.invoke('context', '--memories', '--snapshot', snapshot, expected=3)

    def test_resolution_provenance_evidence_hash_and_scope_mismatch(self):
        import hashlib
        evidence_file = self.project / 'observed.txt'
        evidence_file.write_bytes(b'synthetic repair\r\n')
        proof = dict(kind='file', ref=evidence_file.name, locator='line 1',
                     sha256=hashlib.sha256(evidence_file.read_bytes()).hexdigest())
        self.register(self.create('repair', code_ref='repaired-code'))
        resolution = self.success(json.loads(self.record('repair').read_text()))
        resolution['execution']['evidence'] = [proof]
        self.invoke('experiment', 'update', 'repair', '--file', str(self.write_input(resolution)))
        body = self.body(resolution_experiment_id='repair', remedy='Recorded fix', evidence=[self.proof, proof])
        self.add(body)
        recalled = self.invoke('context', '--memories', '--experiment', 'repair')['data']['cards'][0]
        self.assertEqual(recalled['resolution_source']['record_id'], 'repair')
        self.assertEqual(recalled['condition_matches']['code_ref'], 'mismatch')
        self.assertEqual(recalled['applicability'], 'mismatch')
        self.assertFalse(recalled['evidence_checked'])
        args = ['evidence', 'read', '--kind', 'memory', '--id', 'memory-1', '--pointer', '/evidence/1', '--revision', '1']
        page = self.invoke(*args)['data']
        self.assertEqual(page['text'], 'synthetic repair\r\n')
        evidence_file.write_bytes(b'changed repair\n')
        result = self.invoke(*args, expected=3)
        self.assertEqual(result['diagnostics'][-1]['code'], 'evidence_changed')
        self.assertFalse(self.invoke('context', '--memories')['data']['cards'][0]['evidence_checked'])
        self.assertIn('evidence_changed', {d['code'] for d in self.invoke('check')['diagnostics']})

    def test_failed_first_add_leaves_legacy_layout_and_snapshot_intact(self):
        directory = self.memory().parent
        directory.rmdir()
        before = self.invoke('context')['data']['snapshot_id']
        with patch('zar.storage.os.replace', side_effect=OSError('simulated replace failure')):
            status = main(['memory', 'add', '--file', str(self.write_input(self.body())), '--project', str(self.project), '--json'])
        self.assertEqual(status, 4)
        self.assertFalse(directory.exists())
        self.assertEqual(self.invoke('context')['data']['snapshot_id'], before)
