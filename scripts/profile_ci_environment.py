#!/usr/bin/env python3
"""Small local-only CI diagnostics; times are observations, never speed gates."""
import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import urllib.request


def measure(repeats=3):
    # Child startup includes waiting/capture and process exit. No network requests.
    operations = {
        'python_child': lambda: subprocess.run([sys.executable, '-c', 'pass'], check=True, capture_output=True, timeout=30),
        'python_import_child': lambda: subprocess.run([sys.executable, '-c', 'import zar.cli'], check=True, capture_output=True, timeout=30),
        'opener_construction': urllib.request.build_opener,
    }
    samples = {}
    for name, operation in operations.items():
        rows = []
        for _ in range(repeats):
            started = time.perf_counter()
            operation()
            rows.append(time.perf_counter() - started)
        samples[name] = dict(seconds=rows, median_seconds=statistics.median(rows))
    return dict(version=1, python=platform.python_version(), platform=platform.system(),
                machine=platform.machine(), samples=samples,
                limitations=['No network request or real API.',
                             'Uncontrolled filesystem caches; three diagnostic samples, not a performance guarantee.',
                             'Opener construction includes default handlers and platform proxy discovery.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = measure()
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
