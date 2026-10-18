"""Connection dispatch and bounded OpenAI-compatible Chat Completions transport.

No retries, tool calls, provider body logging, or credential-bearing redirects.
A caller must explicitly choose an endpoint and authorize sending its messages.
"""
import http.client
import ipaddress
import json
import math
import os
import re
import socket
import time
from decimal import Decimal
from urllib import error, parse, request


class LLMError(Exception):
    """Safe diagnostic; provider bodies and credential values are never included."""
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def validate_profile(profile):
    """Validate configuration without reading credentials or making requests."""
    if not isinstance(profile, dict):
        raise LLMError('invalid_profile', 'LLM profile must be an object.')
    if profile.get('provider') == 'codex':
        from .codex_agent import validate_codex_profile
        return validate_codex_profile(profile)
    if set(profile) - {'base_url', 'model', 'api_key_env', 'timeout_seconds', 'max_output_tokens', 'max_response_bytes'}:
        raise LLMError('invalid_profile', 'LLM profile contains unsupported fields; credentials must use the named environment variable.')
    for field in ('base_url', 'model', 'api_key_env'):
        value = profile.get(field)
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise LLMError('invalid_profile', f'Invalid {field}.')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', profile['api_key_env']):
        raise LLMError('invalid_profile', 'api_key_env must name an environment variable.')
    try:
        url = parse.urlsplit(profile['base_url'])
        port = url.port
        host = url.hostname
        local = host == 'localhost'
        if host and not local:
            try: local = ipaddress.ip_address(host).is_loopback
            except ValueError: pass
        if (not host or url.username is not None or url.password is not None or url.query or url.fragment
                or '?' in profile['base_url'] or '#' in profile['base_url']
                or any(c.isspace() for c in profile['base_url']) or '\\' in profile['base_url']
                or (port is not None and port < 1)
                or not (url.scheme == 'https' or (url.scheme == 'http' and local))):
            raise ValueError
    except ValueError:
        raise LLMError('invalid_profile', 'Endpoint must be HTTPS or loopback HTTP without credentials, query, or fragment.') from None
    timeout = profile.get('timeout_seconds', 60)
    try: timeout = float(timeout) if not isinstance(timeout, bool) and isinstance(timeout, (int, float, Decimal)) else float('nan')
    except (ValueError, OverflowError): timeout = float('nan')
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise LLMError('invalid_profile', 'timeout_seconds must be finite and between 0 (exclusive) and 300.')
    for field, default, maximum in (('max_output_tokens', 2048, 1000000), ('max_response_bytes', 1048576, 16777216)):
        value = profile.get(field, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise LLMError('invalid_profile', f'{field} must be a positive bounded integer.')
    return {**profile, 'timeout_seconds': timeout, 'max_output_tokens': profile.get('max_output_tokens', 2048),
            'max_response_bytes': profile.get('max_response_bytes', 1048576)}


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def chat(profile, messages):
    """Return {content: str, usage: dict | None}; errors are safe LLMError values.

    timeout_seconds bounds socket waits and body reading by a monotonic deadline.
    DNS resolution and trickling HTTP headers are subject to OS/urllib behavior;
    this is not a hard process-wide deadline or a provider billing guarantee.
    The orchestrator must separately enforce its call/token budget.
    """
    profile = validate_profile(profile)
    if profile.get('provider') == 'codex':
        from .codex_agent import chat_codex
        return chat_codex(profile, messages)
    if not isinstance(messages, list) or not messages or any(
        not isinstance(m, dict) or set(m) != {'role', 'content'}
        or m['role'] not in ('system', 'user', 'assistant') or not isinstance(m['content'], str)
        for m in messages
    ):
        raise LLMError('invalid_messages', 'Messages must contain only role and text content.')
    key = os.environ.get(profile['api_key_env'], '')
    if not key.strip():
        raise LLMError('missing_api_key', 'Configured API key environment variable is empty or missing.')
    if any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise LLMError('invalid_api_key', 'API key must contain printable ASCII without whitespace.')
    payload = {'model': profile['model'], 'messages': messages, 'stream': False,
               'max_completion_tokens': profile.get('max_output_tokens', 2048),
               'response_format': {'type': 'json_object'}}
    try:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (ValueError, UnicodeError):
        raise LLMError('invalid_messages', 'Messages cannot be encoded as JSON.') from None
    if len(body) > 1048576:
        raise LLMError('request_too_large', 'LLM request exceeds 1 MiB.')
    req = request.Request(profile['base_url'].rstrip('/') + '/chat/completions', data=body,
                          headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                                   'Accept': 'application/json', 'User-Agent': 'ziho-autoresearch'}, method='POST')
    limit = profile.get('max_response_bytes', 1048576)
    deadline = time.monotonic() + profile['timeout_seconds']
    try:
        with request.build_opener(_NoRedirect()).open(req, timeout=profile['timeout_seconds']) as response:
            chunks = []
            size = 0
            # read1 performs at most one raw socket read: trickling bytes cannot
            # reset the entire body timeout as they can with read(limit).
            while size <= limit and not response.isclosed():
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError
                response.fp.raw._sock.settimeout(remaining)
                chunk = response.read1(min(65536, limit + 1 - size))
                if time.monotonic() >= deadline: raise TimeoutError
                if not chunk: break
                chunks.append(chunk)
                size += len(chunk)
            raw = b''.join(chunks)
    except error.HTTPError as exc:
        status = exc.code
        exc.close()
        raise LLMError('http_error', f'LLM endpoint returned HTTP {status}; response body omitted.') from None
    except (TimeoutError, socket.timeout):
        raise LLMError('timeout', 'LLM request timed out; provider may still have processed it. No retry performed.') from None
    except (error.URLError, OSError, ValueError, http.client.HTTPException):
        raise LLMError('transport_error', 'LLM transport failed; provider may still have processed it. No retry performed.') from None
    if len(raw) > limit:
        raise LLMError('response_too_large', 'LLM response exceeds the configured byte limit.')
    try:
        data = json.loads(raw.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        choices = data['choices']
        if not isinstance(choices, list) or len(choices) != 1: raise ValueError
        choice = choices[0]
        message = choice['message']
        content = message['content']
        if (not isinstance(content, str) or not content.strip() or choice.get('finish_reason') != 'stop'
                or message.get('tool_calls') or message.get('function_call') or message.get('refusal')): raise ValueError
        usage = data.get('usage')
        if usage is not None:
            if not isinstance(usage, dict): raise ValueError
            # Store only numerical accounting fields, never arbitrary provider metadata.
            usage = {name: usage[name] for name in ('prompt_tokens', 'completion_tokens', 'total_tokens') if name in usage}
            if any(type(v) is not int or v < 0 for v in usage.values()): raise ValueError
            if not usage: usage = None
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, RecursionError):
        raise LLMError('invalid_response', 'LLM response is malformed, refused, truncated, or contains unsupported tool calls.') from None
    return {'content': content, 'usage': usage}
