import copy
import unittest
from decimal import Decimal

from zar.call_metrics import new_measurement, measure_messages, record_answer, summarize


class CallMetricsTests(unittest.TestCase):
    def test_utf8_content_only_and_zero_output(self):
        m = new_measurement()
        self.assertIsNone(m['output_text_bytes'])
        self.assertEqual(measure_messages([{'role': 'system', 'content': 'abc'},
                                           {'role': 'user', 'content': '한'}]), 6)
        record_answer(m, {'content': '', 'usage': None}, 'http')
        self.assertEqual(m['output_text_bytes'], 0)
        self.assertTrue(all(v is None for v in m['tokens'].values()))

    def test_provider_mapping_partial_counts_never_derive_total(self):
        m = new_measurement()
        record_answer(m, {'content': '한', 'usage': {'prompt_tokens': 7,
            'completion_tokens': 2, 'prompt_tokens_details': {'cached_tokens': 0},
            'secret': 'must not appear'}}, 'http')
        self.assertEqual(m['tokens'], {'input_tokens': 7, 'output_tokens': 2,
                                      'total_tokens': None, 'cached_input_tokens': 0})
        self.assertEqual(m['output_text_bytes'], 3)
        self.assertNotIn('secret', str(m))
        record_answer(m, {'content': 'x', 'usage': {'input_tokens': 4,
            'output_tokens': 1, 'cached_input_tokens': 3}}, 'codex')
        self.assertEqual(m['tokens'], {'input_tokens': 4, 'output_tokens': 1,
                                      'total_tokens': None, 'cached_input_tokens': 3})

    def test_untrusted_numeric_values_rejected_and_decimal_normalized(self):
        for bad in (True, -1, 1.5, '12', float('inf'), float('nan'),
                    Decimal('NaN'), Decimal('Infinity'), Decimal('1e1000000'), 2**64):
            m = new_measurement()
            record_answer(m, {'content': None, 'usage': {'prompt_tokens': bad}}, 'http')
            self.assertIsNone(m['tokens']['input_tokens'], repr(bad))
            self.assertIsNone(m['output_text_bytes'])
        m = new_measurement()
        record_answer(m, {'content': '', 'usage': {'prompt_tokens': Decimal('12')}}, 'http')
        self.assertEqual(m['tokens']['input_tokens'], 12)
        self.assertIs(type(m['tokens']['input_tokens']), int)

    def test_summary_partial_errors_repeats_legacy_and_crash_are_readonly(self):
        first = new_measurement()
        first.update(call_seconds=Decimal('0.25'), input_message_bytes=10)
        record_answer(first, {'content': '', 'usage': {'prompt_tokens': 0}}, 'http')
        error = new_measurement()
        error.update(call_seconds=0.75, input_message_bytes=10)
        session = {'calls': 5, 'trace': [
            {'role': 'analysis', 'measurement': first},
            {'role': 'analysis', 'result': 'error', 'measurement': error},
            {'role': 'planning', 'usage': {'prompt_tokens': 99}},
            {'role': 'review', 'measurement': new_measurement()}]}
        original = copy.deepcopy(session)
        s = summarize(session)
        self.assertEqual(session, original)
        total = s['total']
        self.assertEqual((total['attempts'], total['measured_attempts'], total['unmeasured_attempts']), (5, 3, 2))
        self.assertEqual(total['call_seconds'], {'value': 1.0, 'observations': 2})
        self.assertEqual(total['input_message_bytes'], {'value': 20, 'observations': 2})
        self.assertEqual(total['output_text_bytes'], {'value': 0, 'observations': 1})
        self.assertEqual(total['tokens']['input_tokens'], {'value': 0, 'observations': 1})
        self.assertEqual(total['tokens']['total_tokens'], {'value': None, 'observations': 0})
        self.assertEqual(s['roles']['analysis']['attempts'], 2)
        self.assertEqual(s['roles']['planning']['unmeasured_attempts'], 1)
        self.assertEqual(s['roles']['planning']['tokens']['input_tokens']['value'], None)

    def test_summary_empty_unsupported_and_invalid_measurements(self):
        self.assertEqual(summarize({'calls': 0})['total']['call_seconds'], {'value': None, 'observations': 0})
        s = summarize({'calls': 2, 'trace': [
            {'role': 'analysis', 'measurement': {'version': 2, 'call_seconds': 1}},
            {'role': 'review', 'measurement': {'version': 1, 'call_seconds': Decimal('Infinity'),
             'input_message_bytes': True, 'tokens': {'input_tokens': -1}}}]})
        self.assertEqual(s['total']['measured_attempts'], 1)
        self.assertEqual(s['total']['call_seconds']['observations'], 0)
        self.assertEqual(s['total']['input_message_bytes']['observations'], 0)
        self.assertEqual(s['total']['tokens']['input_tokens']['observations'], 0)
