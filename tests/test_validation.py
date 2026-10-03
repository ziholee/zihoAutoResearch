import unittest
from decimal import Decimal
from pathlib import Path
from zar.codec import loads, dumps
from zar.validation import validate_document


class ValidationTests(unittest.TestCase):
    def test_decimal_roundtrip(self):
        value = loads('{"n": 0.12345678901234567890123456789}')
        self.assertEqual(value['n'], Decimal('0.12345678901234567890123456789'))
        self.assertEqual(loads(dumps(value)), value)

    def test_json_rejects_duplicates_nonfinite_and_arrays(self):
        for source in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '[]'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                loads(source)

    def test_contract_fixtures(self):
        for filename, kind in [('project', 'project'), ('review', 'review'),
                               ('baseline', 'experiment'), ('candidate', 'experiment'),
                               ('submission', 'submission')]:
            doc = loads(Path(f'examples/contract-v1/{filename}.json').read_text())
            self.assertEqual(validate_document(doc, kind), [], filename)

    def test_unknown_nested_field_and_bool_revision(self):
        doc = loads(Path('examples/contract-v1/project.json').read_text())
        doc['environment']['surprise'] = 'x'
        doc['revision'] = True
        self.assertEqual(len(validate_document(doc, 'project')), 2)

    def test_lone_surrogates_and_excessive_nesting_are_errors(self):
        for source in ('{"x":"\\ud800"}', '{"\\udfff":1}', '{"x":' + '[' * 2000 + '0' + ']' * 2000 + '}'):
            with self.subTest(source=source[:40]), self.assertRaises(ValueError):
                loads(source)

    def test_malformed_nested_objects_return_diagnostics(self):
        for name, kind, field in [('project','project','environment'),
                                  ('review','review','items'),
                                  ('candidate','experiment','execution'),
                                  ('submission','submission','artifact')]:
            for replacement in (None, [], 'bad', 2, True):
                doc = loads(Path(f'examples/contract-v1/{name}.json').read_text())
                doc[field] = replacement
                self.assertTrue(validate_document(doc, kind))
