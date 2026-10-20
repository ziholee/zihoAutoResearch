"""Command discovery must not initialize model execution dependencies."""
import json
from pathlib import Path
import subprocess
import sys
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StartupImportTests(unittest.TestCase):
    def test_parsing_keeps_provider_runtime_unloaded(self):
        script = '''
import json, sys
from zar.cli import parse
for argv in (['status'], ['research', 'status', 'session-example'],
             ['research', 'approve', 'session-example', '--token', 'reviewed']):
    parse(argv)
print(json.dumps(sorted(name for name in sys.modules if name in
    ('zar.research', 'zar.llm', 'zar.runner', 'urllib.request', 'ssl'))))
'''
        proc = subprocess.run([sys.executable, '-c', script], cwd=ROOT,
                              capture_output=True, text=True, check=True, timeout=15)
        self.assertEqual(json.loads(proc.stdout), [])

    def test_research_argument_api_remains_available(self):
        from zar import research
        from zar.cli import Parser
        parser = Parser()
        research.add_arguments(parser, Parser)
        args = parser.parse_args(['recover', 'session-example', '--confirm-stopped'])
        self.assertEqual(args.action, 'recover')
        self.assertTrue(args.confirm_stopped)


class StartupMeasurementTests(unittest.TestCase):
    def test_nested_imports_are_counted_once_even_on_failure(self):
        module = runpy.run_path(str(ROOT / 'scripts/profile_cli_startup.py'))
        clock = iter([1.0, 4.0])
        observer = module['Imports'](clock=lambda: next(clock))

        def nested(name, *args):
            if name == 'parent':
                return observer('child')
            raise ImportError('original error')

        observer.original = nested
        with self.assertRaisesRegex(ImportError, 'original error'):
            observer('parent')
        self.assertEqual(observer.seconds, {'cli_import': 3.0})
        self.assertEqual(observer.calls, {'cli_import': 1})
        self.assertEqual(observer.depth, 0)

    def test_real_control_matches_profile_and_partitions_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            for mode in ('warm', 'disabled'):
                output = Path(temporary) / (mode + '.json')
                command = [sys.executable, str(ROOT / 'scripts/benchmark_cli_startup.py'),
                           '--source', str(ROOT), '--output', str(output),
                           '--repeats', '1', '--bytecode', mode]
                result = subprocess.run(command, cwd=temporary, capture_output=True,
                                        text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads(output.read_text())
                self.assertEqual(report, json.loads(result.stdout))
                self.assertEqual(report['bytecode'], mode)
                for name, row in report['trials'][0]['cases'].items():
                    self.assertTrue(row['outputs_equal'])
                    profile = row['results']['profiled']
                    self.assertAlmostEqual(sum(profile['partition_seconds'].values()),
                                           profile['total_seconds'])
                    self.assertEqual(profile['returncode'],
                                     3 if name == 'research_status_missing' else 0)
                    self.assertEqual(profile['parse_calls'], 1)
                previous = output.read_bytes()
                retry = subprocess.run(command, capture_output=True, timeout=10)
                self.assertNotEqual(retry.returncode, 0)
                self.assertEqual(output.read_bytes(), previous)


if __name__ == '__main__':
    unittest.main()
