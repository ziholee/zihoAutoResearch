"""Supervised runner contracts, using only short local Python children."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

from zar.runner import run


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.log = self.root / 'run.log'

    def execute(self, code, **kwargs):
        return run([sys.executable, '-c', code], self.root, self.log,
                   kwargs.pop('timeout_seconds', 3), **kwargs)

    def test_collects_output_exit_and_explicit_environment(self):
        result = self.execute("import os,sys; print(os.environ['RUNNER_TEST']); print('err',file=sys.stderr)",
                              env={**os.environ, 'RUNNER_TEST': 'hello'})
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['exit_code'], 0)
        self.assertIn('hello', self.log.read_text())
        self.assertIn('err', self.log.read_text())
        self.assertLessEqual(result['started_at'], result['finished_at'])

    def test_nonzero_exit_is_failed(self):
        self.assertEqual(self.execute('raise SystemExit(7)')['status'], 'failed')

    def test_timeout_is_bounded_and_stops_direct_child(self):
        start = time.monotonic()
        result = self.execute('import time; time.sleep(60)', timeout_seconds=.1)
        self.assertLess(time.monotonic() - start, 4)
        self.assertEqual(result['status'], 'interrupted' if os.name == 'posix' else 'unknown')
        self.assertIsNotNone(result['exit_code'])

    def test_output_is_drained_but_bounded_with_marker(self):
        result = self.execute("import sys; sys.stdout.write('x'*2000000)", max_log_bytes=1024)
        self.assertEqual(result['status'], 'succeeded')
        self.assertLessEqual(self.log.stat().st_size, 1024)
        self.assertIn(b'truncated', self.log.read_bytes())

    def test_existing_log_and_symlink_are_never_overwritten(self):
        self.log.write_text('keep')
        with self.assertRaises(FileExistsError):
            self.execute('print(1)')
        self.assertEqual(self.log.read_text(), 'keep')
        self.log.unlink()
        target = self.root / 'target'
        target.write_text('keep')
        self.log.symlink_to(target)
        with self.assertRaises((ValueError, OSError)):
            self.execute('print(1)')
        self.assertEqual(target.read_text(), 'keep')

    @unittest.skipUnless(os.name == 'posix', 'POSIX process groups')
    def test_descendant_inheriting_pipe_does_not_hang_runner(self):
        start = time.monotonic()
        result = self.execute("import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])", timeout_seconds=.2)
        self.assertLess(time.monotonic() - start, 4)
        self.assertIn(result['status'], ('interrupted', 'unknown'))

    def test_missing_executable_records_failure(self):
        result = run([str(self.root / 'missing')], self.root, self.log, 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['exit_code'])

    def test_invalid_limits_do_not_create_log(self):
        for limit in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.execute('print(1)', timeout_seconds=limit)
        self.assertFalse(self.log.exists())

    def test_shell_metacharacters_are_literal_arguments(self):
        result = run([sys.executable, '-c', 'import sys; print(sys.argv[1])',
                      'hello; echo should-not-execute'], self.root, self.log, 3)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.log.read_text().strip(), 'hello; echo should-not-execute')

    def test_symlink_parent_is_rejected(self):
        directory = self.root / 'real'
        directory.mkdir()
        alias = self.root / 'alias'
        alias.symlink_to(directory, target_is_directory=True)
        with self.assertRaises(ValueError):
            run([sys.executable, '-c', 'print(1)'], self.root, alias / 'run.log', 3)
        self.assertEqual(list(directory.iterdir()), [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX signals')
    def test_termination_escalates_for_child_ignoring_term(self):
        result = self.execute('import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(60)', timeout_seconds=.3)
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(result['exit_code'], -9)

    @unittest.skipUnless(os.name == 'posix', 'POSIX signals')
    def test_keyboard_interrupt_cleans_up_running_command(self):
        from unittest.mock import patch
        original_sleep = time.sleep
        first = True

        def interrupt_once(seconds):
            nonlocal first
            if first:
                first = False
                raise KeyboardInterrupt
            original_sleep(seconds)

        with patch('zar.runner.time.sleep', side_effect=interrupt_once):
            result = self.execute('import time; time.sleep(60)')
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(result['note'], 'Interrupted by user')
