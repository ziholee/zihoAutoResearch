#!/usr/bin/env python3
"""Benchmark-only launcher. BENCH_ENTRY is captured before runpy is imported."""
import time
import builtins
import json
import os
from pathlib import Path
import sys


class Imports:
    """Time outermost import calls, including cached lookups, without overlap."""

    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.original = builtins.__import__
        self.depth = 0
        self.phase = 'cli_import'
        self.seconds = {}
        self.calls = {}
        self.roots = {}

    def __call__(self, name, globals=None, locals=None, fromlist=(), level=0):
        outer = self.depth == 0
        if outer:
            started = self.clock()
        self.depth += 1
        try:
            return self.original(name, globals, locals, fromlist, level)
        finally:
            self.depth -= 1
            if outer:
                elapsed = self.clock() - started
                self.seconds[self.phase] = self.seconds.get(self.phase, 0.0) + elapsed
                self.calls[self.phase] = self.calls.get(self.phase, 0) + 1
                label = '.' * level + name
                if fromlist:
                    label += ':' + ','.join(fromlist)
                key = (self.phase, label)
                self.roots[key] = self.roots.get(key, 0.0) + elapsed


def main():
    entry = globals()['BENCH_ENTRY']
    imports = Imports()
    builtins.__import__ = imports
    import_started = time.perf_counter()
    try:
        from zar import cli
        import_finished = time.perf_counter()
        original_parse = cli.parse
        parse_seconds = 0.0
        parse_calls = 0

        def parse(arguments):
            nonlocal parse_seconds, parse_calls
            previous = imports.phase
            imports.phase = 'command_init'
            started = time.perf_counter()
            try:
                return original_parse(arguments)
            finally:
                parse_seconds += time.perf_counter() - started
                parse_calls += 1
                imports.phase = previous

        cli.parse = parse
        imports.phase = 'body'
        main_started = time.perf_counter()
        code = 0
        try:
            code = cli.main(sys.argv[1:])
        except SystemExit as exc:
            code = exc.code
        main_finished = time.perf_counter()
    finally:
        builtins.__import__ = imports.original
    parts = {
        'python_to_entry': entry - float(os.environ['ZAR_STARTUP_LAUNCH']),
        'instrumentation_prepare': import_started - entry + main_started - import_finished,
        'cli_import': import_finished - import_started,
        'command_import': imports.seconds.get('command_init', 0.0),
        'command_initialization': parse_seconds - imports.seconds.get('command_init', 0.0),
        'body_import': imports.seconds.get('body', 0.0),
        'body_other': main_finished - main_started - parse_seconds - imports.seconds.get('body', 0.0),
    }
    result = {
        'partition_seconds': parts,
        'parse_calls': parse_calls,
        'import_calls': imports.calls,
        'root_import_seconds': [
            {'phase': phase, 'name': name, 'seconds': seconds}
            for (phase, name), seconds in sorted(imports.roots.items())],
    }
    Path(os.environ['ZAR_STARTUP_PROFILE']).write_text(json.dumps(result), encoding='utf-8')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
