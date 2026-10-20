#!/usr/bin/env python3
"""Benchmark-only CLI launcher; not an installed entry point.

Exclusive categories partition main() wall time. Startup includes Python startup,
imports and launcher setup; launcher setup is also reported as a nested diagnostic.
"""
import time
ENTRY = time.perf_counter()
import functools
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading


class Timer:
    def __init__(self):
        self.owner = threading.get_ident()
        self.stack = []
        self.seconds = {}
        self.calls = {}

    def wrap(self, function, category):
        @functools.wraps(function)
        def measured(*args, **kwargs):
            if threading.get_ident() != self.owner:
                return function(*args, **kwargs)
            frame = [time.perf_counter(), 0.0]
            self.stack.append(frame)
            try:
                return function(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - frame[0]
                self.stack.pop()
                self.seconds[category] = self.seconds.get(category, 0.0) + elapsed - frame[1]
                self.calls[category] = self.calls.get(category, 0) + 1
                if self.stack:
                    self.stack[-1][1] += elapsed
        return measured


def main():
    timer = Timer()
    setup_start = time.perf_counter()
    # Patch definitions before CLI imports aliases. Local imports see the same wrappers.
    targets = {
        'records': ('records', ('load_records',)),
        'validation': ('validation', ('validate_document', 'inspect_project')),
        'storage': ('storage', ('atomic_write',)),
        'roles': ('validation', ('validate_response',)),
        'llm': ('validation', ('validate_profile',)),
    }
    for module_name, (category, names) in targets.items():
        module = importlib.import_module('zar.' + module_name)
        for name in names:
            setattr(module, name, timer.wrap(getattr(module, name), category))
    original_run = subprocess.run
    git_run = timer.wrap(original_run, 'git')

    def run(argv, *args, **kwargs):
        is_git = isinstance(argv, (list, tuple)) and argv and Path(str(argv[0])).name in ('git', 'git.exe')
        return (git_run if is_git else original_run)(argv, *args, **kwargs)

    subprocess.run = run
    from zar.cli import main as cli_main
    setup_seconds = time.perf_counter() - setup_start
    started = time.perf_counter()
    try:
        return timer.wrap(cli_main, 'other')(sys.argv[1:])
    finally:
        finished = time.perf_counter()
        result = dict(startup_seconds=started-float(os.environ['ZAR_BENCH_LAUNCH']),
                      entry_seconds=ENTRY-float(os.environ['ZAR_BENCH_LAUNCH']),
                      launcher_setup_seconds=setup_seconds,
                      body_seconds=finished-started, seconds=timer.seconds, calls=timer.calls)
        Path(os.environ['ZAR_BENCH_PROFILE']).write_text(json.dumps(result), encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
