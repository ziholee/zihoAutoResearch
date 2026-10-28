"""Opt-in interactive file contract keeps separate save/transmission consent."""
import unittest
from unittest.mock import patch
from zar.codec import loads
from zar.setup import setup
import test_setup as helpers


class FileProvenanceSetupTests(unittest.TestCase):
    setUp = helpers.SetupTests.setUp
    ask = helpers.SetupTests.ask

    def policy(self):
        (self.root / 'evaluation.py').write_text('PRIVATE_EVALUATION', encoding='utf-8')
        return dict(version=1, evaluation_paths=['evaluation.py'], provenance_paths=[])

    def test_opt_in_persists_only_hash_and_never_sends_without_consent(self):
        policy = self.policy()
        with patch('zar.research.chat') as chat:
            result = setup(self.root, ask=self.ask, emit=lambda value: None, file_contract=policy)
        chat.assert_not_called()
        self.assertTrue(result['saved'])
        project = loads((self.root / '.autoresearch/project.json').read_text())
        self.assertEqual(project['file_contract'], policy)
        self.assertIn('evaluation.py', result['session']['file_manifest']['files'])
        self.assertNotIn('PRIVATE_EVALUATION', str(result))

    def test_change_during_save_confirmation_does_not_initialize(self):
        policy = self.policy()
        def changed(prompt):
            if prompt.startswith('save:'):
                (self.root / 'evaluation.py').write_text('changed', encoding='utf-8')
            return self.ask(prompt)
        with self.assertRaises(ValueError):
            setup(self.root, ask=changed, emit=lambda value: None, file_contract=policy)
        self.assertFalse((self.root / '.autoresearch').exists())


if __name__ == '__main__':
    unittest.main()
