import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zar.evidence import EvidenceError, read_evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'source.txt'

    def source(self, content, hashed=True, kind='file'):
        self.path.write_bytes(content)
        return {'evidence': [{'kind': kind, 'ref': 'source.txt', 'locator': None,
                             'sha256': hashlib.sha256(content).hexdigest() if hashed else None}]}

    def read(self, doc, **kwargs):
        return read_evidence(self.root, doc, '/evidence/0', **kwargs)

    def fails(self, doc, code, exit_code, **kwargs):
        with self.assertRaises(EvidenceError) as caught:
            self.read(doc, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.exit_code, exit_code)

    def test_exact_crlf_multibyte_and_continuation(self):
        content = '첫째\r\nsecond\r\n끝'.encode()
        doc = self.source(content)
        page, diagnostics = self.read(doc, max_lines=1)
        self.assertEqual(page['text'], '첫째\r\n')
        self.assertEqual((page['start_line'], page['end_line'], page['total_lines']), (1, 1, 3))
        self.assertEqual(page['next_line'], 2)
        self.assertTrue(page['truncated'])
        self.assertEqual(page['source']['actual_sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual(page['source']['byte_count'], len(content))
        self.assertEqual(page['source']['hash_state'], 'matched')
        self.assertEqual(diagnostics, [])
        page, _ = self.read(doc, start_line=2)
        self.assertEqual(page['text'], 'second\r\n끝')
        self.assertIsNone(page['next_line'])

    def test_byte_cap_does_not_cut_line(self):
        doc = self.source('가\n나\n'.encode())
        page, _ = self.read(doc, max_bytes=5)
        self.assertEqual(page['text'], '가\n')
        self.assertEqual(page['next_line'], 2)

    def test_changed_missing_unhashed(self):
        doc = self.source(b'old\n')
        self.path.write_bytes(b'new\n')
        self.fails(doc, 'evidence_changed', 3)
        self.path.unlink()
        self.fails(doc, 'evidence_missing', 4)
        doc = self.source(b'new\n', hashed=False)
        page, diagnostics = self.read(doc)
        self.assertEqual(page['source']['hash_state'], 'unrecorded')
        self.assertEqual(diagnostics[0]['code'], 'evidence_unhashed')

    def test_external_never_fetched(self):
        for kind in ('url', 'user_report'):
            doc = self.source(b'', kind=kind)
            self.fails(doc, 'evidence_unsupported', 3)

    def test_invalid_pointer_and_ranges(self):
        doc = self.source(b'a\n')
        for pointer in ('evidence/0', '/evidence/00', '/evidence/~2', '/missing', '/evidence/0/ref', ''):
            with self.assertRaises(EvidenceError):
                read_evidence(self.root, doc, pointer)
        for kwargs in ({'start_line': 0}, {'start_line': True}, {'max_lines': 1001}, {'max_bytes': 1048577}, {'max_bytes': 0}):
            self.fails(doc, 'evidence_range', 3, **kwargs)

    def test_long_line_rejected(self):
        self.fails(self.source(b'long line\n'), 'evidence_line_too_long', 3, max_bytes=4)

    def test_invalid_utf8_and_binary_even_outside_excerpt(self):
        for content in (b'ok\n\xff', b'ok\n\x00'):
            self.fails(self.source(content), 'evidence_encoding', 3, max_lines=1)

    def test_regular_file_only_and_symlinks(self):
        doc = self.source(b'a\n')
        self.path.unlink()
        self.path.mkdir()
        self.fails(doc, 'evidence_not_regular', 4)
        self.path.rmdir()
        actual = self.root / 'actual.txt'
        actual.write_bytes(b'a\n')
        self.path.symlink_to(actual)
        self.assertEqual(self.read(doc)[0]['text'], 'a\n')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO creation is unavailable')
    def test_fifo_is_not_regular(self):
        doc = self.source(b'a\n')
        self.path.unlink()
        os.mkfifo(self.path)
        self.fails(doc, 'evidence_not_regular', 4)

    def test_eof_and_empty(self):
        for content in (b'', b'a\n'):
            page, _ = self.read(self.source(content), start_line=20)
            self.assertEqual(page['text'], '')
            self.assertIsNone(page['next_line'])
            self.assertIsNone(page['end_line'])
            self.assertFalse(page['truncated'])

    def test_escaped_pointer(self):
        doc = self.source(b'a')
        evidence = doc['evidence'][0]
        page, _ = read_evidence(self.root, {'a/b~': evidence}, '/a~1b~0')
        self.assertEqual(page['text'], 'a')

    def test_mutation_during_read_is_rejected(self):
        doc = self.source(b'a\n')
        before = self.path.stat()
        changed = SimpleNamespace(st_size=before.st_size, st_mtime_ns=before.st_mtime_ns + 1)
        with patch('zar.evidence.os.fstat', side_effect=[before, changed]):
            self.fails(doc, 'evidence_changed', 3)

    def test_unreadable_source_is_actionable(self):
        doc = self.source(b'a\n')
        with patch('zar.evidence.os.open', side_effect=PermissionError('denied')):
            self.fails(doc, 'evidence_missing', 4)

    def test_large_skipped_line_and_multibyte_chunk_boundary(self):
        content = b'a' * 65535 + '가\nfinal\n'.encode()
        doc = self.source(content)
        page, _ = self.read(doc, start_line=2, max_bytes=6)
        self.assertEqual(page['text'], 'final\n')
        self.assertEqual(page['total_lines'], 2)
        self.assertEqual(page['source']['actual_sha256'], hashlib.sha256(content).hexdigest())
