"""Interactive setup public entrypoint keeps prompts away from JSON output."""
import io
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from zar import cli
from zar.codec import loads

class SetupCLITests(unittest.TestCase):
    def test_parser_exposes_setup_without_existing_project_settings(self):
        args=cli.parse(['research','setup','--project','my-project','--json'])
        self.assertEqual((args.command,args.action,args.project),('research','setup','my-project'))

    def test_noninteractive_input_fails_without_initializing_or_network(self):
        with tempfile.TemporaryDirectory() as folder:
            stdout,stderr=io.StringIO(),io.StringIO()
            with patch('sys.stdin',io.StringIO()),redirect_stdout(stdout),redirect_stderr(stderr):
                code=cli.main(['research','setup','--project',folder,'--json'])
            self.assertNotEqual(code,0)
            result=loads(stdout.getvalue())
            self.assertIn('terminal',result['diagnostics'][0]['message'].lower())
            self.assertFalse((Path(folder)/'.autoresearch').exists())

    def test_tty_cancellation_returns_json_and_preserves_project(self):
        class Terminal(io.StringIO):
            def isatty(self):return True
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'train.py').write_text('print("untouched")\n')
            stdout,stderr=io.StringIO(),io.StringIO()
            with patch('sys.stdin',Terminal(':cancel\n')),redirect_stdout(stdout),redirect_stderr(stderr):
                code=cli.main(['research','setup','--project',folder,'--json'])
            self.assertEqual(code,0,stdout.getvalue())
            data=loads(stdout.getvalue())['data']
            self.assertEqual(data['view'],'research_setup');self.assertTrue(data['cancelled'])
            self.assertFalse((root/'.autoresearch').exists())
            self.assertEqual((root/'train.py').read_text(),'print("untouched")\n')
            self.assertTrue(stderr.getvalue())

    def test_non_utf8_source_returns_diagnostic_without_initialization(self):
        from tests import test_setup
        fixture=test_setup.SetupTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        (fixture.root/'train.py').write_bytes(b'\xff')
        stdout,stderr=io.StringIO(),io.StringIO()
        class Terminal(io.StringIO):
            def isatty(self):return True
            def readline(self):
                key=stderr.getvalue().splitlines()[-1].split(':',1)[0]
                return fixture.answers[key]+'\n'
        with patch('sys.stdin',Terminal()),redirect_stdout(stdout),redirect_stderr(stderr):
            code=cli.main(['research','setup','--project',str(fixture.root),'--json'])
        self.assertNotEqual(code,0)
        result=loads(stdout.getvalue())
        self.assertFalse(result['ok'])
        self.assertIn('UTF-8',result['diagnostics'][0]['message'])
        self.assertFalse((fixture.root/'.autoresearch').exists())
