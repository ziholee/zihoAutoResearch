"""Mixed-scale contracts are checked by isolated CLI workers with small fixtures."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/verify_mixed_research.py'
VERIFY = runpy.run_path(str(SCRIPT))


class MixedResearchTests(unittest.TestCase):
    def test_tied_expected_memories_use_explicit_identifier_tiebreak(self):
        candidates = [dict(session_id=f'session-{i}', created_at='same') for i in reversed(range(6))]
        self.assertEqual([x['session_id'] for x in VERIFY['expected'](candidates)],
                         [f'session-{i}' for i in range(1, 6)])

    def test_small_mixed_cli_preserves_mutation_approval_and_restart_contracts(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'mixed'
            completed = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
                '--source', str(ROOT), '--output', str(output), '--records', '2', '--sessions', '6',
                '--memory-characters', '16000'], capture_output=True, text=True, timeout=120)
            if completed.returncode:
                errors = '\n'.join(p.read_text(encoding='utf-8') for p in (output / 'private').glob('*.stderr'))
                self.fail(completed.stdout + completed.stderr + errors)
            report = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(set(report['scenarios']), set(VERIFY['SCENARIOS']))
            for result in report['scenarios'].values():
                self.assertTrue(result['validated'] and result['execution_absent'])
                self.assertEqual(result['stderr_bytes'], 0)
            for name in ('record-edit', 'record-add', 'record-delete', 'record-correction'):
                result = report['scenarios'][name]
                self.assertEqual((result['model_calls'], result['stored_call_attempts'], result['preserved_successful_roles']), (2, 2, 1))
            self.assertEqual(report['scenarios']['between-roles']['model_calls'], 1)
            self.assertEqual(report['scenarios']['history-changes']['memory_mutations'], 3)
            resume = report['scenarios']['resume']
            self.assertEqual((resume['model_calls'], resume['stored_call_attempts'], resume['preserved_successful_roles']), (3, 6, 5))
            self.assertTrue(resume['new_process_memory_update_verified'])
            self.assertTrue(report['scenarios']['approval']['approval_checked'])
            self.assertTrue(report['scenarios']['stale-approval']['stale_approval_refused'])


class LargeMixedResearchTests(unittest.TestCase):
    def test_large_hypotheses_preserve_all_mutation_and_approval_scenarios(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'large'
            completed = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(SCRIPT),
                '--source', str(ROOT), '--output', str(output), '--records', '63',
                '--sessions', '6', '--memory-characters', '32', '--large-characters', '128'],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            report = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(report['large_characters'], 128)
            self.assertIsNotNone(report['record_dimensions'])
            self.assertEqual(set(report['scenarios']), set(VERIFY['SCENARIOS']))
            self.assertTrue(all(r['validated'] and r['execution_absent'] for r in report['scenarios'].values()))
            self.assertTrue(report['scenarios']['stale-approval']['stale_approval_refused'])
            self.assertTrue(report['scenarios']['resume']['new_process_memory_update_verified'])
