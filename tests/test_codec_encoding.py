"""Keep canonical bytes and strict scalar handling while reusing an encoder."""
from decimal import Decimal
import json
import math
import unittest
from unittest.mock import patch

from zar.codec import dumps, loads


class CodecEncodingTests(unittest.TestCase):
    def test_repeated_record_keys_do_not_rebuild_scalar_encoder(self):
        documents = [{'id': str(i), 'note': '한글 "quote"\n'} for i in range(100)]
        expected = json.dumps(documents, ensure_ascii=False) + '\n'
        with patch.object(json, 'JSONEncoder', wraps=json.JSONEncoder) as factory:
            self.assertEqual(dumps(documents), expected)
        self.assertEqual(factory.call_count, 1)

    def test_validated_keys_skip_generic_scalar_type_dispatch(self):
        key = 'repeated-field-name'
        documents = [{key: i} for i in range(100)]
        checks = []
        builtin_isinstance = isinstance
        def observe(value, types):
            if value is key:
                checks.append(types)
            return builtin_isinstance(value, types)
        with patch('zar.codec.isinstance', side_effect=observe, create=True):
            actual = dumps(documents)
        self.assertEqual(actual, json.dumps(documents) + '\n')
        # One string-key validation per dictionary, no repeated generic dispatch.
        self.assertEqual(checks, [str] * 100)

    def test_key_encoding_respects_calls_and_ascii_settings(self):
        document = {'한글': {'한글': Decimal('1.00')}}
        self.assertEqual(dumps(document), '{"한글": {"한글": 1.00}}\n')
        self.assertEqual(dumps(document, ensure_ascii=True),
                         '{"\\ud55c\\uae00": {"\\ud55c\\uae00": 1.00}}\n')
        document['한글']['한글'] = Decimal('-0E+2')
        self.assertEqual(dumps(document), '{"한글": {"한글": -0E+2}}\n')

    def test_many_unique_and_large_keys_preserve_insertion_order_and_hash(self):
        import hashlib
        from zar.research import digest
        document = {f'field-{i}': {'shared': i} for i in reversed(range(1000))}
        document['큰' * 1000] = {'shared': True}
        expected = (json.dumps(document, ensure_ascii=False) + '\n').encode('utf-8')
        self.assertEqual(dumps(document).encode('utf-8'), expected)
        self.assertEqual(digest(document), hashlib.sha256(expected).hexdigest())

    def test_nested_scalars_match_stdlib_bytes_in_both_modes(self):
        document = {'키\n': ['é', '😀', '\x00\t"\\', None, True, False,
                            -0.0, 1e-100, 1e100, 10**100, {'empty': []}]}
        for ascii_mode in (False, True):
            self.assertEqual(dumps(document, ensure_ascii=ascii_mode),
                             json.dumps(document, ensure_ascii=ascii_mode,
                                        allow_nan=False) + '\n')

    def test_decimal_lexemes_and_strict_errors_remain(self):
        document = {'score': Decimal('0.123456789012345678901234567890'),
                    'zero': Decimal('-0.00'), 'exponent': Decimal('1E+99')}
        expected = ('{"score": 0.123456789012345678901234567890, '
                    '"zero": -0.00, "exponent": 1E+99}\n')
        self.assertEqual(dumps(document), expected)
        self.assertEqual(loads(expected), document)
        for value in (math.nan, math.inf, -math.inf,
                      Decimal('NaN'), Decimal('Infinity'), {1: 'bad key'}, {1, 2}):
            with self.assertRaises(ValueError):
                dumps({'bad': value})


if __name__ == '__main__':
    unittest.main()
