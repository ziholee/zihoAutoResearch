"""Public next-session parser and consent surface."""
import io
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr
import tempfile
import unittest
from unittest.mock import patch
from zar import cli
from zar.codec import loads

class NextCLITests(unittest.TestCase):
    def test_parser_exposes_next_session(self):
        args=cli.parse(['research','next','session-'+'a'*32,'--json'])
        self.assertEqual((args.command,args.action,args.id),('research','next','session-'+'a'*32))
    def test_nonterminal_returns_structured_diagnostic(self):
        with tempfile.TemporaryDirectory() as folder:
            cli.initialize(Path(folder));out,err=io.StringIO(),io.StringIO()
            with patch('sys.stdin',io.StringIO()),redirect_stdout(out),redirect_stderr(err):
                code=cli.main(['research','next','session-'+'a'*32,'--project',folder,'--json'])
            self.assertNotEqual(code,0)
            self.assertIn('terminal',loads(out.getvalue())['diagnostics'][0]['message'].lower())
    def test_cancellation_keeps_completed_parent_and_outputs(self):
        from tests import test_research as fixture
        from zar import research
        h=fixture.ResearchTests();h.setUp();self.addCleanup(h.doCleanups)
        with patch('zar.research.chat',side_effect=h.respond):
            s=h.planned();research.approve(h.root,s['id'],s['approval_token'])
            research.run_session(h.root,s['id']);s=research.advance(h.root,s['id'],send=True)
            research.decide(h.root,s['id'],s['approval_token'],select=True)
            s=research.advance(h.root,s['id'],send=True)
        parent=h.root/'.autoresearch/sessions'/ (s['id']+'.json')
        before=parent.read_bytes();metric=(h.root/'metric.json').read_bytes()
        class Terminal(io.StringIO):
            def isatty(self):return True
        out,err=io.StringIO(),io.StringIO()
        with patch('sys.stdin',Terminal(':cancel\n')),redirect_stdout(out),redirect_stderr(err):
            code=cli.main(['research','next',s['id'],'--project',str(h.root),'--json'])
        self.assertEqual(code,0,out.getvalue())
        self.assertTrue(loads(out.getvalue())['data']['cancelled'])
        self.assertEqual(parent.read_bytes(),before)
        self.assertEqual((h.root/'metric.json').read_bytes(),metric)
        self.assertEqual(len(list(parent.parent.glob('*.json'))),1)
