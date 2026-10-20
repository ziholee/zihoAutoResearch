import copy
import json
import unittest
from decimal import Decimal

from zar.call_metrics import (new_measurement, measure_messages, measure_input_components,
                             record_answer, summarize)


class CallMetricsTests(unittest.TestCase):
    def test_input_components_partition_actual_multilingual_message_bytes(self):
        context = {'sources': {'模型.py': {'content': 'print("한글")\n\\'}},
                   'records': ['기록'], 'observation': {'score': 1},
                   'comparison': None, 'prior_lessons': [],
                   'next_context': {'parent': '前'}, 'revision_context': None,
                   'outputs': {'analysis': {'summary': '日本語'}},
                   'goal': '실험', 'allowed_tools': []}
        messages = [{'role': 'system', 'content': '지침\n"안전"'},
                    {'role': 'user', 'content': json.dumps(context, ensure_ascii=False,
                                                         separators=(',', ':'))}]
        result = measure_input_components(messages)
        self.assertEqual(sum(result.values()), measure_messages(messages))
        self.assertEqual(result['instructions'], len('지침\n"안전"'.encode()))
        self.assertEqual(result['sources'],
                         len('"sources":{"模型.py":{"content":"print(\\"한글\\")\\n\\\\"}}'.encode()))
        self.assertEqual(result['outputs'],
                         len('"outputs":{"analysis":{"summary":"日本語"}}'.encode()))
        self.assertEqual(result['framing'], 2 + len(context) - 1)
        self.assertEqual(result['other'], len('"goal":"실험""allowed_tools":[]'.encode()))
        record_fields = ('records', 'observation', 'comparison', 'prior_lessons',
                         'next_context', 'revision_context')
        self.assertEqual(result['records'], sum(
            len(json.dumps({key: context[key]}, ensure_ascii=False,
                           separators=(',', ':'))[1:-1].encode())
            for key in record_fields))
        self.assertTrue(all(type(value) is int for value in result.values()))

    def test_empty_context_and_noncanonical_messages_do_not_invent_breakdown(self):
        canonical = [{'role': 'system', 'content': ''}, {'role': 'user', 'content': '{}'}]
        self.assertEqual(measure_input_components(canonical),
                         dict(instructions=0, sources=0, records=0, outputs=0, other=0, framing=2))
        for content in ('{ "sources": {} }', '[]', '{"a":1,"a":2}', '{"x":NaN}', 'invalid'):
            messages = [canonical[0], {'role': 'user', 'content': content}]
            self.assertIsNone(measure_input_components(messages), content)
        self.assertIsNone(measure_input_components(canonical + [canonical[1]]))
        self.assertIsNone(measure_input_components(list(reversed(canonical))))

    def test_component_summary_preserves_legacy_unknown_and_rejects_bad_partitions(self):
        parts = dict(instructions=10, sources=20, records=0, outputs=5, other=3, framing=2)
        measured = new_measurement()
        measured.update(input_message_bytes=40, input_components_bytes=parts)
        legacy = {'version': 1, 'input_message_bytes': 12}
        malformed = []
        for bad in (True, -1, 1.5, '20', float('nan'), 2**64, None):
            item = copy.deepcopy(measured)
            item['input_components_bytes']['sources'] = bad
            malformed.append(item)
        for modify in (lambda p: p.pop('records'), lambda p: p.update(extra=0),
                       lambda p: p.update(sources=21)):
            item = copy.deepcopy(measured)
            modify(item['input_components_bytes'])
            malformed.append(item)
        missing_total = copy.deepcopy(measured)
        missing_total['input_message_bytes'] = None
        malformed.append(missing_total)
        session = {'calls': 2 + len(malformed), 'trace': [
            {'role': 'review', 'measurement': measured},
            {'role': 'planning', 'measurement': legacy},
            *({'role': 'review', 'measurement': item} for item in malformed)]}
        original = copy.deepcopy(session)
        result = summarize(session)
        self.assertEqual(session, original)
        for name, value in parts.items():
            self.assertEqual(result['total']['input_components_bytes'][name],
                             {'value': value, 'observations': 1})
            self.assertEqual(result['roles']['review']['input_components_bytes'][name],
                             {'value': value, 'observations': 1})
            self.assertEqual(result['roles']['planning']['input_components_bytes'][name],
                             {'value': None, 'observations': 0})
        self.assertIsNone(new_measurement()['input_components_bytes'])

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
