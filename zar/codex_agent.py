"""Proposal-only Codex CLI transport with bounded POSIX process ownership.

The executable and machine-level Codex policy are trusted. A scratch directory,
read-only sandbox and disabled tool surfaces reduce access; this is not an OS
security boundary for a malicious executable or administrator configuration.
"""
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import selectors
import time
from decimal import Decimal


def _error(code, message):
    from .llm import LLMError
    return LLMError(code, message)


def validate_codex_profile(profile):
    allowed = {'provider', 'command', 'model', 'timeout_seconds', 'max_response_bytes'}
    if not isinstance(profile, dict) or set(profile) - allowed or profile.get('provider') != 'codex':
        raise _error('invalid_profile', 'Invalid Codex profile fields.')
    command = profile.get('command', 'codex')
    model = profile.get('model')
    for name, value in (('command', command), ('model', model)):
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise _error('invalid_profile', f'Invalid {name}.')
    # A single executable, never shell text. Absolute paths may contain spaces.
    if command.startswith('-') or (not os.path.isabs(command) and any(c.isspace() for c in command)):
        raise _error('invalid_profile', 'command must name one executable without arguments.')
    value = profile.get('timeout_seconds', 60)
    try: timeout = float(value) if not isinstance(value, bool) and isinstance(value, (int, float, Decimal)) else float('nan')
    except (ValueError, OverflowError): timeout = float('nan')
    if not math.isfinite(timeout) or not 0 < timeout <= 300:
        raise _error('invalid_profile', 'timeout_seconds must be finite and between 0 (exclusive) and 300.')
    limit = profile.get('max_response_bytes', 1048576)
    if type(limit) is not int or not 1 <= limit <= 16777216:
        raise _error('invalid_profile', 'max_response_bytes must be a positive bounded integer.')
    return {'provider':'codex', 'command':command, 'model':model,
            'timeout_seconds':timeout, 'max_response_bytes':limit}


def _process(argv, payload, cwd, deadline, limit):
    """Bound all I/O and cleanup; uncertain process ownership blocks retries."""
    # Allocate the selector before spawning so allocation failure owns no child.
    selector = selectors.DefaultSelector()
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd, start_new_session=True,
                                bufsize=0)
    except OSError:
        selector.close()
        raise _error('agent_unavailable', 'Codex executable could not be started.') from None
    chunks = [bytearray(), bytearray()]
    sent = 0
    open_readers = {proc.stdout, proc.stderr}
    def drain(events, collecting=True):
        nonlocal sent
        for key, _ in events:
            pipe = key.fileobj
            if key.data == 'stdin':
                try: sent += os.write(pipe.fileno(), payload[sent:sent + 8192])
                except (BrokenPipeError, ConnectionResetError): sent = len(payload)
                except BlockingIOError: continue
                if sent == len(payload): selector.unregister(pipe); pipe.close()
            else:
                try: data = os.read(pipe.fileno(), 8192)
                except BlockingIOError: continue
                if not data:
                    selector.unregister(pipe); open_readers.discard(pipe)
                elif collecting:
                    remaining = limit - len(chunks[key.data])
                    if len(data) > remaining:
                        raise _error('agent_output_too_large', 'Codex output exceeded the configured limit.')
                    chunks[key.data].extend(data)
    try:
        for index, pipe in enumerate((proc.stdout, proc.stderr)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, index)
        os.set_blocking(proc.stdin.fileno(), False)
        if payload: selector.register(proc.stdin, selectors.EVENT_WRITE, 'stdin')
        else: proc.stdin.close()
        while proc.poll() is None or open_readers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _error('agent_timeout', 'Codex exceeded the call deadline.')
            drain(selector.select(min(.05, remaining)))
        if proc.returncode != 0:
            raise _error('agent_failed', 'Codex failed; check local CLI installation and authentication separately.')
        return bytes(chunks[0])
    finally:
        cleanup_deadline = time.monotonic() + 1
        confirmed = True
        try:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            except OSError: confirmed = False
            try: proc.wait(timeout=max(.001, cleanup_deadline - time.monotonic()))
            except (subprocess.TimeoutExpired, OSError): confirmed = False
            # An escaped child retaining pipes is evidence that cleanup is unknown.
            while open_readers and time.monotonic() < cleanup_deadline:
                try: drain(selector.select(min(.05, max(0, cleanup_deadline - time.monotonic()))), False)
                except OSError:
                    confirmed = False
                    break
            if open_readers: confirmed = False
        finally:
            selector.close()
            # Unbuffered, nonblocking pipes have no worker locks or flush waits.
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                try: pipe.close()
                except OSError: confirmed = False
        if not confirmed:
            raise _error('agent_cleanup_unconfirmed', 'Codex process cleanup could not be confirmed; inspect local processes before recovering this session.') from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError


def _parse(raw):
    content = None
    usage = None
    completed = False
    try:
        lines = raw.decode('utf-8').splitlines()
        for line in lines:
            event = json.loads(line, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if not isinstance(event, dict) or completed: raise ValueError
            kind = event.get('type')
            if kind in ('thread.started', 'turn.started'): continue
            if kind in ('item.started', 'item.updated', 'item.completed'):
                item = event.get('item')
                if not isinstance(item, dict) or item.get('type') not in ('agent_message', 'reasoning'): raise ValueError
                if kind == 'item.completed' and item['type'] == 'agent_message':
                    if not isinstance(item.get('text'), str): raise ValueError
                    content = item['text']
            elif kind == 'turn.completed':
                completed = True
                data = event.get('usage')
                if data is not None:
                    if not isinstance(data, dict): raise ValueError
                    usage = {key:data[key] for key in ('input_tokens', 'cached_input_tokens', 'output_tokens') if key in data}
                    if any(type(v) is not int or v < 0 for v in usage.values()): raise ValueError
                    usage = usage or None
            else: raise ValueError
        if not completed or not content: raise ValueError
    except (ValueError, UnicodeError, RecursionError):
        raise _error('agent_protocol_error', 'Codex returned an incomplete, invalid, or tool-bearing response.') from None
    return {'content':content, 'usage':usage}


def chat_codex(profile, messages):
    """Return text and usage; never approve or execute experiment proposals."""
    profile = validate_codex_profile(profile)
    if os.name != 'posix':
        raise _error('unsupported_agent_platform', 'Codex adapter requires POSIX process-group containment; use the API provider on this platform.')
    if not isinstance(messages, list) or not messages or any(
        not isinstance(m, dict) or set(m) != {'role','content'}
        or m['role'] not in ('system','user','assistant') or not isinstance(m['content'], str) for m in messages
    ):
        raise _error('invalid_messages', 'Messages must contain only role and text content.')
    try:
        payload = ('Return only the requested JSON proposal. Do not use tools or execute commands.\n'
                   + json.dumps(messages, ensure_ascii=False, allow_nan=False, separators=(',', ':'))).encode('utf-8')
    except (ValueError, UnicodeError, RecursionError):
        raise _error('invalid_messages', 'Messages cannot be encoded as JSON.') from None
    if len(payload) > 1048576:
        raise _error('request_too_large', 'LLM request exceeds 1 MiB.')
    executable = shutil.which(profile['command'])
    if not executable:
        raise _error('agent_unavailable', 'Codex executable was not found.')
    executable = str(Path(executable).resolve())
    deadline = time.monotonic() + profile['timeout_seconds']
    with tempfile.TemporaryDirectory(prefix='zar-codex-') as scratch:
        version = _process([executable, '--version'], b'', scratch, deadline, 4096)
        match = re.fullmatch(rb'codex-cli (\d+)\.(\d+)\.(\d+)\s*', version)
        if not match or tuple(map(int, match.groups())) < (0,162,1):
            raise _error('unsupported_agent_version', 'Codex CLI 0.162.1 or newer stable version is required.')
        settings = ['features.shell_tool=false', 'features.shell_snapshot=false',
                    'features.multi_agent=false', 'features.hooks=false',
                    'features.remote_plugin=false', 'features.skill_mcp_dependency_install=false',
                    'apps._default.enabled=false', 'web_search="disabled"', 'project_doc_max_bytes=0']
        argv = [executable, '--no-daemon', '-a', 'never', 'exec', '--sandbox', 'read-only',
                '--ephemeral', '--ignore-user-config', '--ignore-rules', '--strict-config',
                '--skip-git-repo-check', '--json', '--color', 'never', '-m', profile['model']]
        for setting in settings: argv.extend(['-c', setting])
        argv.append('-')
        return _parse(_process(argv, payload, scratch, deadline, profile['max_response_bytes']))
