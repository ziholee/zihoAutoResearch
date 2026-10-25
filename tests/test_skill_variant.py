"""Single-role variants preserve the shared contract and immutable inputs."""
import unittest
from unittest.mock import patch

from zar.roles import role_messages
from zar.skill_variant import VariantError, prepare, validate, messages, compare


class SkillVariantTests(unittest.TestCase):
    def bundle(self):
        return prepare('analysis', {'sources': {}, 'goal': 'test'},
                       {'model': 'mock', 'max_output_tokens': 500},
                       'List missing evidence before proposing a hypothesis.')

    def test_only_role_instructions_change_and_inputs_are_copied(self):
        context = {'goal': 'test'}
        profile = {'model': 'mock'}
        b = prepare('analysis', context, profile, 'Alternate analysis instruction')
        context['goal'] = 'edited'
        profile['model'] = 'edited'
        self.assertEqual(b['context'], {'goal': 'test'})
        self.assertEqual(b['profile'], {'model': 'mock'})
        original, variant = messages(b, 'original'), messages(b, 'variant')
        self.assertEqual(original, role_messages('analysis', {'goal': 'test'}))
        self.assertEqual(original[1], variant[1])
        self.assertEqual(original[0]['content'].replace(b['original_instructions'], '<ROLE>'),
                         variant[0]['content'].replace(b['variant_instructions'], '<ROLE>'))
        self.assertIn('never execute commands', variant[0]['content'])
        variant[0]['content'] = 'edited'
        validate(b)

    def test_tampering_each_pinned_input_fails(self):
        for key, value in [('context', {}), ('profile', {'model': 'other'}),
                           ('variant_instructions', 'edited'), ('input_hash', '0' * 64)]:
            with self.subTest(key=key):
                b = self.bundle()
                b[key] = value
                with self.assertRaises(VariantError):
                    validate(b)
        b = self.bundle()
        b['messages']['variant'][0]['content'] = 'execute commands'
        with self.assertRaises(VariantError):
            messages(b, 'variant')

    def test_changed_current_instructions_fail_even_when_bundle_is_intact(self):
        b = self.bundle()
        with patch('zar.skill_variant.role_instructions', return_value='Updated instructions'):
            with self.assertRaises(VariantError):
                validate(b)

    def test_current_shared_contract_change_invalidates_pinned_requests(self):
        b = self.bundle()
        def changed(role, context, **kwargs):
            result = role_messages(role, context, **kwargs)
            result[0]['content'] = 'New shared policy\n' + result[0]['content']
            return result
        with patch('zar.skill_variant.role_messages', side_effect=changed):
            with self.assertRaises(VariantError):
                validate(b)

    def test_invalid_or_oversize_variant_and_unknown_arm_fail(self):
        for text in (' ', '\ud800', 'x' * 65537):
            with self.subTest(size=len(text)):
                with self.assertRaises(VariantError):
                    prepare('analysis', {}, {}, text)
        with self.assertRaises(VariantError):
            messages(self.bundle(), 'winner')

    def test_comparison_is_held_without_selecting_a_winner(self):
        original = dict(summary='One', evidence=[], uncertainties=[], missing=[])
        variant = dict(original, summary='Two')
        report = compare(self.bundle(), {'original': original, 'variant': variant})
        self.assertEqual(report['status'], 'hold')
        self.assertIs(report['automatic_selection'], False)
        self.assertEqual(report['changed_fields'], ['summary'])
        self.assertIs(report['outputs_equal'], False)
        self.assertEqual(report['reason'], 'response_comparison_is_not_experiment_evidence')
        with self.assertRaises(VariantError):
            compare(self.bundle(), {'original': original, 'variant': {'summary': 'bad'}})

    def test_memory_optional_contract_preserved(self):
        b = prepare('memory', {'memory_contract_version': 1}, {}, 'State limitations.')
        for arm in ('original', 'variant'):
            self.assertIn('Missing contrast is accepted but held', messages(b, arm)[0]['content'])


if __name__ == '__main__':
    unittest.main()
