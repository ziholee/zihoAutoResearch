"""Revision entrypoint preserves the public terminal and JSON contracts."""
import io
from contextlib import redirect_stderr, redirect_stdout
import tempfile
import unittest
from unittest.mock import patch
from zar import cli
from zar.codec import loads

class RevisionCLITests(unittest.TestCase):
    def test_parser_accepts_revision_parent(self):
        args=cli.parse(['research','revise','session-'+'a'*32,'--json'])
        self.assertEqual(args.action,'revise')
        self.assertEqual(args.id,'session-'+'a'*32)

    def test_nonterminal_is_a_structured_error(self):
        with tempfile.TemporaryDirectory() as folder:
            cli.initialize(__import__('pathlib').Path(folder))
            out,err=io.StringIO(),io.StringIO()
            with patch('sys.stdin',io.StringIO()),redirect_stdout(out),redirect_stderr(err):
                code=cli.main(['research','revise','session-'+'a'*32,'--project',folder,'--json'])
            self.assertNotEqual(code,0)
            result=loads(out.getvalue())
            self.assertIn('terminal',result['diagnostics'][0]['message'].lower())

    def test_cancel_keeps_old_session_and_stdout_is_json(self):
        from tests import test_research as fixture
        harness=fixture.ResearchTests();harness.setUp();self.addCleanup(harness.doCleanups)
        session=harness.planned()
        before=(harness.root/'.autoresearch/sessions'/ (session['id']+'.json')).read_bytes()
        class Terminal(io.StringIO):
            def isatty(self):return True
        out,err=io.StringIO(),io.StringIO()
        with patch('sys.stdin',Terminal(':cancel\n')),redirect_stdout(out),redirect_stderr(err):
            code=cli.main(['research','revise',session['id'],'--project',str(harness.root),'--json'])
        self.assertEqual(code,0,out.getvalue())
        self.assertTrue(loads(out.getvalue())['data']['cancelled'])
        self.assertTrue(err.getvalue())
        self.assertEqual((harness.root/'.autoresearch/sessions'/ (session['id']+'.json')).read_bytes(),before)
