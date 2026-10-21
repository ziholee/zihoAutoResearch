"""Benchmark HTTP transport keeps real binding and restart without reverse DNS."""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import runpy
import socket
import threading
import unittest
from unittest.mock import patch

SERVER = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/benchmark_workflow_utility.py'))['LoopbackServer']


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LoopbackServerTests(unittest.TestCase):
    def test_http_and_same_port_restart_without_reverse_dns(self):
        port = 0
        with patch.object(socket, 'getfqdn', side_effect=AssertionError('Unexpected reverse DNS')) as lookup:
            for _ in range(2):
                server = SERVER(('127.0.0.1', port), Handler)
                self.assertEqual(server.server_name, 'localhost')
                self.assertEqual(server.server_port, server.server_address[1])
                self.assertGreater(server.server_port, 0)
                if port:
                    self.assertEqual(server.server_port, port)
                port = server.server_port
                thread = threading.Thread(target=server.serve_forever,
                                          kwargs={'poll_interval': 0.01}, daemon=True)
                thread.start()
                connection = HTTPConnection('127.0.0.1', port, timeout=5)
                try:
                    body = b'{"role":"analysis"}'
                    connection.request('POST', '/v1/chat/completions', body,
                                       {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), body)
                finally:
                    connection.close()
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            lookup.assert_not_called()

    def test_non_numeric_loopback_and_external_bind_are_rejected(self):
        for host in ('0.0.0.0', '192.0.2.1', 'localhost', ''):
            with self.subTest(host=host), \
                    patch.object(socket.socket, 'bind', side_effect=AssertionError('Unexpected bind')) as bind, \
                    patch.object(socket, 'getfqdn', side_effect=AssertionError('Unexpected reverse DNS')) as lookup:
                with self.assertRaisesRegex(RuntimeError, 'must bind to 127.0.0.1'):
                    SERVER((host, 0), Handler)
                bind.assert_not_called()
                lookup.assert_not_called()
