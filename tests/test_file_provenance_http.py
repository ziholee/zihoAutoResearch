"""Local-only file hashes across actual CLI and loopback HTTP boundaries."""
import os
import unittest

from zar.codec import dumps, loads
import test_research_http as helpers


class FileProvenanceHTTPTests(unittest.TestCase):
    stop_server = helpers.ResearchHTTPTests.stop_server
    invoke = helpers.ResearchHTTPTests.invoke
    start = helpers.ResearchHTTPTests.start
    assert_no_execution = helpers.ResearchHTTPTests.assert_no_execution

    def setUp(self):
        helpers.ResearchHTTPTests.setUp(self)
        self.private_text = 'LOCAL_ONLY_EVALUATION_SENTINEL_NEVER_TRANSMIT'
        (self.root / 'evaluate.py').write_text(self.private_text, encoding='utf-8')
        (self.root / 'input.bin').write_bytes(b'\x00PRIVATE_BINARY_INPUT\xff')
        path = self.root / '.autoresearch/project.json'
        project = loads(path.read_text(encoding='utf-8'))
        project['file_contract'] = dict(version=1, evaluation_paths=['evaluate.py'], provenance_paths=['input.bin'])
        path.write_text(dumps(project), encoding='utf-8')

    def test_untransmitted_files_never_enter_provider_payload_and_resume_works(self):
        session = self.start()
        self.assertIn('file_manifest', session)
        session = self.invoke('advance', session['id'], '--send')
        for _, _, payload in self.requests:
            text = dumps(payload)
            self.assertNotIn(self.private_text, text)
            self.assertNotIn('PRIVATE_BINARY_INPUT', text)
        self.invoke('approve', session['id'], '--token', session['approval_token'])
        session = self.invoke('run', session['id'])
        self.assertEqual(session['state'], 'observed')
        observed = self.invoke('status', session['id'])
        self.assertEqual(observed['file_manifest'], session['file_manifest'])
        session = self.invoke('advance', session['id'], '--send')
        self.invoke('decide', session['id'], '--token', session['approval_token'])
        session = self.invoke('advance', session['id'], '--send')
        self.assertEqual(session['state'], 'complete')
        self.assertNotIn(self.private_text, dumps(session))
        self.assertNotIn('PRIVATE_BINARY_INPUT', dumps([payload for _, _, payload in self.requests]))

    def test_nontransmitted_change_before_send_is_rejected(self):
        session = self.start()
        (self.root / 'input.bin').write_bytes(b'changed')
        self.invoke('advance', session['id'], '--send', expected=3)
        self.assertEqual(self.requests, [])
        self.assert_no_execution()

    def test_same_size_mtime_change_after_approval_cannot_execute(self):
        session = self.start()
        session = self.invoke('advance', session['id'], '--send')
        self.invoke('approve', session['id'], '--token', session['approval_token'])
        path = self.root / 'evaluate.py'
        before = path.stat()
        path.write_text('X' * len(self.private_text), encoding='utf-8')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.invoke('run', session['id'], expected=3)
        self.assert_no_execution()


if __name__ == '__main__':
    unittest.main()
