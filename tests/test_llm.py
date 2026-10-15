"""Exercise the API boundary with a real local HTTP server; never paid requests."""
import json
import threading
import socket
import time
from decimal import Decimal
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from zar.llm import LLMError, chat, validate_profile


class LLMTests(unittest.TestCase):
    def setUp(self):
        outer = self
        self.requests = []
        self.status = 200
        self.trickle = False
        self.content_length = False
        self.payload = json.dumps({'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                                   'usage': {'prompt_tokens': 8, 'completion_tokens': 3, 'total_tokens': 11}}).encode()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                outer.requests.append((self.path, self.headers.get('Authorization'),
                                       json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(outer.status)
                if outer.status == 307: self.send_header('Location', '/stolen')
                if outer.content_length: self.send_header('Content-Length', str(len(outer.payload)))
                self.end_headers()
                if outer.trickle:
                    for byte in outer.payload:
                        try: self.wfile.write(bytes([byte])); self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError): break
                        time.sleep(0.04)
                else: self.wfile.write(outer.payload)
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.profile = dict(base_url=f'http://127.0.0.1:{self.server.server_port}/v1', model='mock',
                            api_key_env='ZAR_TEST_KEY', timeout_seconds=2, max_output_tokens=64)
        self.env = patch.dict('os.environ', {'ZAR_TEST_KEY': 'secret-test-token'})
        self.env.start()
    def tearDown(self):
        self.env.stop(); self.server.shutdown(); self.server.server_close(); self.thread.join()
    def invoke(self, **changes):
        return chat(dict(self.profile, **changes), [{'role': 'system', 'content': 'Return JSON.'}])
    def test_success_wire_format_and_usage(self):
        self.assertEqual(self.invoke(), {'content': '{"ok":true}', 'usage': {'prompt_tokens': 8, 'completion_tokens': 3, 'total_tokens': 11}})
        path, auth, body = self.requests[0]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertEqual(auth, 'Bearer secret-test-token')
        self.assertEqual(body['max_completion_tokens'], 64)
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertFalse(body['stream'])
        self.assertNotIn('tools', body)
    def test_content_length_response_closes_cleanly(self):
        self.content_length = True
        self.assertEqual(self.invoke()['content'], '{"ok":true}')
    def test_http_errors_are_redacted_and_never_retried(self):
        self.status = 429; self.payload = b'secret-test-token private prompt'
        with self.assertRaises(LLMError) as caught: self.invoke()
        self.assertEqual(caught.exception.code, 'http_error')
        self.assertNotIn('secret-test-token', str(caught.exception))
        self.assertNotIn('private prompt', str(caught.exception))
        self.assertEqual(len(self.requests), 1)
    def test_redirect_does_not_forward_credentials(self):
        self.status = 307
        with self.assertRaises(LLMError): self.invoke()
        self.assertEqual(len(self.requests), 1)
    def test_oversize_and_malformed_response(self):
        with self.assertRaises(LLMError) as caught: self.invoke(max_response_bytes=32)
        self.assertEqual(caught.exception.code, 'response_too_large')
        for value in (b'bad JSON', b'[]', b'{"choices":[]}', b'{"choices":[{"message":{"content":null}}]}',
                      b'{"choices":[{"message":{"content":"{}"},"finish_reason":"length"}]}'):
            self.payload = value
            with self.subTest(value=value), self.assertRaises(LLMError): self.invoke()
    def test_key_required_before_request(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(LLMError) as caught: self.invoke()
        self.assertEqual(caught.exception.code, 'missing_api_key'); self.assertFalse(self.requests)
    def test_invalid_profiles_rejected_without_network(self):
        for changes in ({'base_url': 'http://example.com/v1'}, {'base_url': 'https://user:secret@example.com'},
                        {'base_url': 'https://example.com?secret=x'}, {'base_url': 'https://example.com#x'},
                        {'base_url': 'https://example.com\n'}, {'timeout_seconds': float('nan')},
                        {'timeout_seconds': 0}, {'max_output_tokens': True}, {'max_response_bytes': -1},
                        {'api_key_env': 'bad\nkey'}, {'model': ''}):
            with self.subTest(changes=changes), self.assertRaises(LLMError): self.invoke(**changes)
        self.assertFalse(self.requests)
    def test_usage_absent_stays_unknown(self):
        self.payload = b'{"choices":[{"message":{"content":"{}"},"finish_reason":"stop"}]}'
        self.assertIsNone(self.invoke()['usage'])
    def test_tool_calls_refusal_and_invalid_usage_rejected(self):
        for message, usage in (({'content': '{}', 'tool_calls': [{'id': 'call'}]}, None),
                               ({'content': '{}', 'refusal': 'refused'}, None),
                               ({'content': '{}'}, {'total_tokens': True}),
                               ({'content': '{}'}, {'total_tokens': -1})):
            self.payload = json.dumps({'choices': [{'message': message, 'finish_reason': 'stop'}], 'usage': usage}).encode()
            with self.subTest(message=message, usage=usage), self.assertRaises(LLMError): self.invoke()
    def test_timeout_does_not_expose_exception_text(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=socket.timeout('secret-test-token')):
            with self.assertRaises(LLMError) as caught: self.invoke()
        self.assertEqual(caught.exception.code, 'timeout')
        self.assertNotIn('secret-test-token', str(caught.exception))
    def test_invalid_messages_and_header_secret_rejected_before_network(self):
        for messages in ([], [{'role': 'tool', 'content': '{}'}], [{'role': 'user', 'content': {}, 'extra': 'x'}]):
            with self.subTest(messages=messages), self.assertRaises(LLMError): chat(self.profile, messages)
        with patch.dict('os.environ', {'ZAR_TEST_KEY': 'secret\r\nX-Injected: value'}):
            with self.assertRaises(LLMError): self.invoke()
        self.assertFalse(self.requests)
    def test_unknown_credential_field_is_rejected(self):
        with self.assertRaises(LLMError) as caught:
            validate_profile(dict(self.profile, api_key='secret-test-token'))
        self.assertNotIn('secret-test-token', str(caught.exception))
    def test_decimal_timeout_normalized_and_defaults_explicit(self):
        normalized = validate_profile(dict(self.profile, timeout_seconds=Decimal('1.25')))
        self.assertIs(type(normalized['timeout_seconds']), float)
        self.assertEqual(normalized['timeout_seconds'], 1.25)
        self.assertEqual(normalized['max_response_bytes'], 1048576)
        self.assertEqual(self.invoke(timeout_seconds=Decimal('1.25'))['content'], '{"ok":true}')
    def test_trickling_body_cannot_extend_read_deadline(self):
        self.trickle = True
        started = time.monotonic()
        with self.assertRaises(LLMError) as caught: self.invoke(timeout_seconds=0.15)
        self.assertEqual(caught.exception.code, 'timeout')
        self.assertLess(time.monotonic() - started, 1.0)
    def test_profile_validation_does_not_require_secret(self):
        with patch.dict('os.environ', {}, clear=True): validate_profile(self.profile)


if __name__ == '__main__': unittest.main()
