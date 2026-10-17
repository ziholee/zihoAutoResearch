"""Real subprocess tests using a synthetic agent; never calls Codex/models."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
import unittest
from zar.codex_agent import chat_codex, validate_codex_profile
from zar.llm import LLMError


@unittest.skipUnless(os.name == 'posix', 'POSIX process containment')
class CodexAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.command = Path(self.tmp.name) / 'fake-agent'

    def agent(self, body, version='0.162.1'):
        self.command.write_text('#!' + sys.executable + '\nimport sys,json,time,os\n'
            + f'if "--version" in sys.argv:\n print("codex-cli {version}"); sys.exit()\n' + body)
        self.command.chmod(0o700)
        return {'provider': 'codex', 'command': str(self.command), 'model': 'mock', 'timeout_seconds': 2}

    def test_bounded_proposal_protocol_and_sandbox_flags(self):
        p = self.agent('''
a = sys.argv
assert '--ignore-user-config' in a and '--ignore-rules' in a and '--ephemeral' in a
assert a[a.index('--sandbox')+1] == 'read-only'
assert a[a.index('-a')+1] == 'never'
assert 'features.shell_tool=false' in a
assert os.getcwd() != ''' + repr(os.getcwd()) + '''
prompt = sys.stdin.read()
assert 'private task' in prompt
print(json.dumps({'type':'thread.started','thread_id':'fake'}))
print(json.dumps({'type':'turn.started'}))
print(json.dumps({'type':'item.completed','item':{'id':'1','type':'agent_message','text':'{"summary":"ok"}'}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':3,'cached_input_tokens':1,'output_tokens':4}}))
''')
        self.assertEqual(chat_codex(p, [{'role':'user','content':'private task'}]),
                         {'content':'{"summary":"ok"}', 'usage':{'input_tokens':3,'cached_input_tokens':1,'output_tokens':4}})

    def test_tool_events_are_rejected(self):
        p = self.agent("print(json.dumps({'type':'item.started','item':{'type':'command_execution','command':'secret'}}))")
        with self.assertRaises(LLMError) as cm: chat_codex(p, [{'role':'user','content':'hello'}])
        self.assertEqual(cm.exception.code, 'agent_protocol_error')
        self.assertNotIn('secret', str(cm.exception))

    def test_failure_redacts_provider_output(self):
        p = self.agent("print('SECRET_TOKEN',file=sys.stderr); sys.exit(2)")
        with self.assertRaises(LLMError) as cm: chat_codex(p, [{'role':'user','content':'hello'}])
        self.assertNotIn('SECRET_TOKEN', str(cm.exception))

    def test_timeout(self):
        p = self.agent('time.sleep(10)'); p['timeout_seconds'] = .1
        with self.assertRaises(LLMError) as cm: chat_codex(p, [{'role':'user','content':'hello'}])
        self.assertEqual(cm.exception.code, 'agent_timeout')

    def test_both_streams_bounded(self):
        for stream in ('stdout','stderr'):
            with self.subTest(stream=stream):
                p = self.agent(f'print("x"*10000,file=sys.{stream},flush=True); time.sleep(2)'); p['max_response_bytes']=128
                with self.assertRaises(LLMError) as cm: chat_codex(p, [{'role':'user','content':'hello'}])
                self.assertEqual(cm.exception.code, 'agent_output_too_large')

    def test_old_cli_and_missing_command(self):
        p = self.agent('raise AssertionError("must not run")', '0.100.0')
        with self.assertRaises(LLMError) as cm: chat_codex(p, [{'role':'user','content':'hello'}])
        self.assertEqual(cm.exception.code, 'unsupported_agent_version')
        p['command'] += '-missing'
        with self.assertRaises(LLMError) as cm: chat_codex(p, [{'role':'user','content':'hello'}])
        self.assertEqual(cm.exception.code, 'agent_unavailable')

    def test_incomplete_and_malformed_protocol(self):
        for body in ('print("not json")', "print(json.dumps({'type':'turn.started'}))"):
            with self.subTest(body=body):
                with self.assertRaises(LLMError): chat_codex(self.agent(body), [{'role':'user','content':'hello'}])

    def test_profile_rejects_arguments_and_unknown_flags(self):
        for extra in ({'command':'codex --dangerously-bypass-approvals-and-sandbox'}, {'flags':[]}, {'max_output_tokens':2}):
            with self.assertRaises(LLMError): validate_codex_profile({'provider':'codex','model':'mock',**extra})

    def test_timeout_kills_descendant_process(self):
        marker = Path(self.tmp.name) / 'escaped'
        child = "import time; from pathlib import Path; time.sleep(.4); Path(" + repr(str(marker)) + ").write_text('escaped')"
        p = self.agent("import subprocess\nsubprocess.Popen([sys.executable,'-c'," + repr(child) + "])\ntime.sleep(10)")
        p['timeout_seconds'] = .2
        with self.assertRaises(LLMError): chat_codex(p, [{'role':'user','content':'hello'}])
        time.sleep(.5)
        self.assertFalse(marker.exists())

    def test_unknown_safety_flag_fails_without_retry(self):
        marker = Path(self.tmp.name) / 'calls'
        p = self.agent("from pathlib import Path\np=Path(" + repr(str(marker)) + ")\np.write_text(p.read_text()+'x' if p.exists() else 'x')\nprint('unsupported --ignore-user-config SECRET',file=sys.stderr)\nsys.exit(2)")
        with self.assertRaises(LLMError) as cm: chat_codex(p, [{'role':'user','content':'hello'}])
        self.assertEqual(cm.exception.code, 'agent_failed')
        self.assertEqual(marker.read_text(), 'x')
        self.assertNotIn('SECRET', str(cm.exception))

    def test_non_posix_fails_before_launch(self):
        p = self.agent('raise AssertionError("must not launch")')
        with patch('zar.codex_agent.os.name', 'nt'):
            with self.assertRaises(LLMError) as cm: chat_codex(p, [{'role':'user','content':'hello'}])
        self.assertEqual(cm.exception.code, 'unsupported_agent_platform')

    def test_detached_child_reports_bounded_unconfirmed_cleanup(self):
        import signal
        from zar.codex_agent import _process
        pidfile = Path(self.tmp.name) / 'detached-pid'
        child = "import time; time.sleep(20)"
        code = ('import subprocess,sys,time; from pathlib import Path; '
                + 'p=subprocess.Popen([sys.executable,"-c",' + repr(child) + '],start_new_session=True); '
                + 'Path(' + repr(str(pidfile)) + ').write_text(str(p.pid)); time.sleep(20)')
        started = time.monotonic()
        try:
            with self.assertRaises(LLMError) as cm:
                _process([sys.executable, '-c', code], b'', self.tmp.name, started + .3, 4096)
            self.assertEqual(cm.exception.code, 'agent_cleanup_unconfirmed')
            self.assertLess(time.monotonic() - started, 2)
        finally:
            if pidfile.exists():
                try: os.kill(int(pidfile.read_text()), signal.SIGKILL)
                except ProcessLookupError: pass

    def test_keyboard_interrupt_cleans_owned_process(self):
        import selectors
        import subprocess
        from zar.codex_agent import _process
        original_select = selectors.DefaultSelector.select
        original_popen = subprocess.Popen
        processes = []
        interrupted = False
        def select(instance, timeout=None):
            nonlocal interrupted
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return original_select(instance, timeout)
        def popen(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            processes.append(process)
            return process
        with patch('zar.codex_agent.subprocess.Popen', side_effect=popen), patch.object(selectors.DefaultSelector, 'select', select):
            with self.assertRaises(KeyboardInterrupt):
                _process([sys.executable, '-c', 'import time; time.sleep(20)'], b'', self.tmp.name, time.monotonic()+5, 4096)
        self.assertIsNotNone(processes[0].poll())

    def test_duplicate_fields_and_nonfinite_json_rejected(self):
        from zar.codex_agent import _parse
        for raw in (b'{"type":"turn.completed","type":"turn.started"}',
                    b'{"type":"turn.completed","usage":{"input_tokens":NaN}}'):
            with self.assertRaises(LLMError) as cm: _parse(raw)
            self.assertEqual(cm.exception.code, 'agent_protocol_error')

    def test_wait_timeout_reports_safe_unconfirmed_cleanup(self):
        import subprocess
        from zar.codex_agent import _process
        original_popen = subprocess.Popen
        processes = []
        def popen(*args, **kwargs):
            proc = original_popen(*args, **kwargs)
            processes.append(proc)
            proc.wait = lambda timeout=None: (_ for _ in ()).throw(subprocess.TimeoutExpired('REDACTED_SECRET', timeout))
            return proc
        try:
            with patch('zar.codex_agent.subprocess.Popen', side_effect=popen):
                with self.assertRaises(LLMError) as cm:
                    _process([sys.executable, '-c', 'import time; time.sleep(20)'], b'', self.tmp.name, time.monotonic()+.1, 4096)
            self.assertEqual(cm.exception.code, 'agent_cleanup_unconfirmed')
            self.assertNotIn('REDACTED_SECRET', str(cm.exception))
        finally:
            for proc in processes:
                subprocess.Popen.wait(proc, timeout=2)
