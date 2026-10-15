"""Bounded local command execution; approval and durable invocation state live upstream.

Commands run without a shell, but this is not a sandbox. Callers must approve the
exact command and provide a sanitized environment (``env=None`` inherits it).
POSIX process groups cannot contain descendants which deliberately detach.
"""
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import signal
import subprocess
import threading
import time


_MARKER = b'\n[output truncated]\n'


def _now():
    return datetime.now(timezone.utc).isoformat()


def _group_alive(process):
    if os.name != 'posix':
        return process.poll() is None
    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stop(process):
    """Bounded cleanup; False means descendant termination is unconfirmed."""
    for sig in (signal.SIGTERM, signal.SIGKILL if os.name == 'posix' else None):
        try:
            if os.name == 'posix':
                os.killpg(process.pid, sig)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass
        except OSError:
            return False
        until = time.monotonic() + .5
        while time.monotonic() < until:
            process.poll()  # reap before testing the group
            if not _group_alive(process):
                return os.name == 'posix'
            time.sleep(.01)
    process.poll()
    return os.name == 'posix' and not _group_alive(process)


def run(argv: list[str], cwd: Path, log: Path, timeout_seconds: float,
        max_log_bytes: int = 1048576, env: dict | None = None) -> dict:
    """Run one approved command, writing a new bounded log and returning its state.

    Log and argument errors raise before launch. Launch errors return ``failed``.
    Timeout / Ctrl-C returns ``interrupted`` only if group cleanup was confirmed;
    Windows cleanup is best effort and returns ``unknown``. Parent symlinks are
    rejected as well as a preexisting final log. Trusted local directories are
    required: this check does not protect against concurrent parent replacement.
    """
    if (not isinstance(argv, list) or not argv or
            any(not isinstance(arg, str) or '\0' in arg for arg in argv) or not argv[0]):
        raise ValueError('argv must be a nonempty list of strings')
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise ValueError('timeout_seconds must be finite and positive')
    if isinstance(max_log_bytes, bool) or not isinstance(max_log_bytes, int) or max_log_bytes < len(_MARKER):
        raise ValueError(f'max_log_bytes must be at least {len(_MARKER)}')
    log = Path(os.path.abspath(log))
    for path in (log, *log.parents):
        # macOS /tmp and /var aliases are common; callers should pass resolved paths.
        if path.is_symlink():
            raise ValueError('log path must not contain symlinks')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(log, flags, 0o600)
    started = _now()
    result = dict(status='failed', started_at=started, finished_at=None, exit_code=None, note='')
    with os.fdopen(fd, 'wb') as output:
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       shell=False, start_new_session=os.name == 'posix')
        except OSError as exc:
            result.update(finished_at=_now(), note=f'Unable to start command: {type(exc).__name__}')
            return result
        buffer = bytearray()
        lock = threading.Lock()
        truncated = False
        read_error = False

        def drain():
            nonlocal truncated, read_error
            try:
                while True:
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    with lock:
                        space = max_log_bytes - len(buffer)
                        buffer.extend(chunk[:space])
                        truncated = truncated or len(chunk) > space
            except OSError:
                read_error = True
            finally:
                process.stdout.close()

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout_seconds
        reason = None
        try:
            while process.poll() is None or reader.is_alive():
                if time.monotonic() >= deadline:
                    reason = 'Command timed out'
                    break
                time.sleep(min(.02, max(0, deadline - time.monotonic())))
            if reason is None and _group_alive(process):
                reason = 'Command left running descendants'
        except KeyboardInterrupt:
            reason = 'Interrupted by user'
        if reason:
            confirmed = _stop(process)
            reader.join(timeout=.2)
            result['status'] = 'interrupted' if confirmed and not reader.is_alive() else 'unknown'
            result['note'] = reason + ('' if result['status'] == 'interrupted' else '; termination unconfirmed')
        else:
            result['status'] = 'succeeded' if process.returncode == 0 else 'failed'
            if read_error:
                result.update(status='unknown', note='Output capture failed')
        with lock:
            if truncated:
                buffer[max_log_bytes - len(_MARKER):] = _MARKER
            output.write(buffer)
        result.update(exit_code=process.poll(), finished_at=_now())
    return result
