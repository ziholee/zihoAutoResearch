#!/usr/bin/env python3
"""Small local-only CI diagnostics; times are observations, never speed gates."""
import argparse
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import socket
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import urllib.request


def measure(repeats=3, *, hostname_probe=False):
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
    if hostname_probe:
        # HTTPServer.server_bind resolves its server name even for a loopback-only
        # mock. Attribute that lookup separately without changing its behavior.
        lookup = []
        original = socket.getfqdn
        def timed_lookup(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                lookup.append(time.perf_counter() - started)
        socket.getfqdn = timed_lookup
        started = time.perf_counter()
        try:
            server = HTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
            server.server_close()
        finally:
            socket.getfqdn = original
        elapsed = time.perf_counter() - started
        samples['loopback_server_construction'] = dict(seconds=[elapsed],
            hostname_lookup_seconds=lookup, other_seconds=elapsed-sum(lookup))
    return dict(version=1, python=platform.python_version(), platform=platform.system(),
                machine=platform.machine(), samples=samples,
                limitations=['No HTTP request or real API; server construction may invoke the OS hostname resolver.',
                             'Uncontrolled filesystem caches; three diagnostic samples, not a performance guarantee.',
                             'Opener construction includes default handlers and platform proxy discovery.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--hostname-probe', action='store_true',
                        help='Also time the standard server hostname lookup; may wait on OS DNS')
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = measure(hostname_probe=args.hostname_probe)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
