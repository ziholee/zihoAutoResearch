"""Record hashing preserves exact legacy bytes without whole-store buffers."""
from decimal import Decimal
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from zar import research
from zar.codec import dumps


class RecordDigestTests(unittest.TestCase):
    def capture(self, records):
        chunks = []
        class Hash:
            def __init__(self, data=b''):
                self.hash = hashlib.sha256()
                self.update(data)
            def update(self, data):
                chunks.append(data)
                self.hash.update(data)
            def hexdigest(self):
                return self.hash.hexdigest()
        with patch.object(research, 'hashlib', SimpleNamespace(sha256=Hash)):
            result = getattr(research, 'records_digest', research.digest)(records)
        return result, chunks

    def test_bounded_batches_preserve_bytes_at_boundaries(self):
        for count in (0, 1, 63, 64, 65, 128, 129, 1000):
            with self.subTest(count=count):
                records = {'empty': {}, 'experiment': {
                    f'exp-{i}': {'note': '한글 😀 "\\\n', 'score': Decimal('-0.00'),
                                 'items': [None, True, False, 1e-100, Decimal('1E+99')]}
                    for i in reversed(range(count))}, 'last': {}}
                result, chunks = self.capture(records)
                expected = dumps(records).encode('utf-8')
                self.assertEqual(b''.join(chunks), expected)
                self.assertEqual(result, hashlib.sha256(expected).hexdigest())
                if count == 1000:
                    self.assertLess(max(map(len, chunks)), len(expected) // 10)

    def test_order_edits_and_empty_store_match_legacy_identity(self):
        for records in ({}, {'b': {}, 'a': {}}, {'a': {}, 'b': {}},
                        {'experiment': {'one': {'value': Decimal('1.00')}}},
                        {'experiment': {'one': {'value': Decimal('1.01')}}}):
            result, chunks = self.capture(records)
            self.assertEqual(b''.join(chunks), dumps(records).encode('utf-8'))
            self.assertEqual(result, research.digest(records))

    def test_large_document_and_escaped_group_and_identifier_match(self):
        records = {'그룹"\n': {'식별자\\': {'body': '😀é한글}\n' * 10000}},
                   'other': {'next': {'body': 'small'}}}
        result, chunks = self.capture(records)
        expected = dumps(records).encode('utf-8')
        self.assertEqual(b''.join(chunks), expected)
        self.assertEqual(result, hashlib.sha256(expected).hexdigest())
        with self.assertRaises(UnicodeEncodeError):
            self.capture({'experiment': {'x': {'v': '\ud800'}}})

    def test_invalid_keys_and_numbers_are_still_rejected(self):
        for records in ({1: {}}, {'experiment': {1: {}}},
                        {'experiment': {'x': {'v': Decimal('NaN')}}},
                        {'experiment': {'x': {'v': float('inf')}}}):
            with self.subTest(records=records), self.assertRaises(ValueError):
                self.capture(records)
