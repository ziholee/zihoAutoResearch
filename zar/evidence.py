"""Bounded, read-only recall from a recorded local evidence reference.

Hash and excerpt come from one stream. Before/after descriptor metadata checks
are best effort, not a filesystem snapshot: concurrent same-size writes with
restored timestamps cannot reliably be detected. Lines end at LF (CRLF bytes
are retained); a final unterminated line also counts. Reading past EOF returns
empty text, a null end_line and next_line, and truncated=False.
"""
import codecs
import hashlib
import os
from pathlib import Path
import re
import stat


class EvidenceError(Exception):
    def __init__(self, code: str, message: str, exit_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


def _pointer(document, pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise EvidenceError('evidence_pointer', 'Supply a JSON Pointer to an evidence object.', 3)
    value = document
    for token in pointer[1:].split('/'):
        if re.search(r'~(?![01])', token):
            raise EvidenceError('evidence_pointer', 'Invalid JSON Pointer escape.', 3)
        token = token.replace('~1', '/').replace('~0', '~')
        try:
            if isinstance(value, list):
                if not re.fullmatch(r'0|[1-9][0-9]*', token):
                    raise KeyError(token)
                value = value[int(token)]
            elif isinstance(value, dict):
                value = value[token]
            else:
                raise KeyError(token)
        except (KeyError, IndexError, ValueError):
            raise EvidenceError('evidence_pointer', 'JSON Pointer does not identify an evidence object.', 3) from None
    if (not isinstance(value, dict) or set(value) != {'kind', 'ref', 'locator', 'sha256'}
            or value['kind'] not in ('file', 'fixture', 'url', 'user_report')
            or not isinstance(value['ref'], str) or not value['ref']
            or not (value['locator'] is None or isinstance(value['locator'], str))
            or not (value['sha256'] is None or isinstance(value['sha256'], str)
                    and re.fullmatch(r'[0-9a-f]{64}', value['sha256']))):
        raise EvidenceError('evidence_pointer', 'Pointer must select an exact evidence object with kind, ref, locator, sha256.', 3)
    return value


def read_evidence(root: Path, document: dict, pointer: str, *, start_line=1,
                  max_lines=80, max_bytes=16384):
    """Read a page; max_bytes bounds excerpt bytes, not the response envelope."""
    for name, value, cap in (('start_line', start_line, None), ('max_lines', max_lines, 1000),
                             ('max_bytes', max_bytes, 1048576)):
        if type(value) is not int or value < 1 or cap is not None and value > cap:
            raise EvidenceError('evidence_range', f'{name} must be a positive integer' +
                                (f' at most {cap}.' if cap else '.'), 3)
    evidence = _pointer(document, pointer)
    if evidence['kind'] not in ('file', 'fixture'):
        raise EvidenceError('evidence_unsupported', 'Only local file/fixture evidence can be read; external/user evidence is never fetched.', 3)
    path = Path(evidence['ref'])
    if not path.is_absolute():
        path = root / path
    fd = None
    try:
        # O_NONBLOCK prevents a replacement FIFO from hanging between stat/open.
        if not stat.S_ISREG(path.stat().st_mode):
            raise EvidenceError('evidence_not_regular', 'Evidence source must be an ordinary regular file.', 4)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceError('evidence_not_regular', 'Evidence source must be an ordinary regular file.', 4)
        stream = os.fdopen(fd, 'rb')
        fd = None
        with stream:
            digest = hashlib.sha256()
            decoder = codecs.getincrementaldecoder('utf-8')('strict')
            total_bytes = total_lines = current_size = excerpt_size = 0
            current = bytearray()
            excerpt = []
            capturing = True
            too_long = False
            encoding_error = False

            def finish_line():
                nonlocal total_lines, current_size, excerpt_size, capturing, too_long
                total_lines += 1
                if capturing and start_line <= total_lines < start_line + max_lines:
                    if current_size > max_bytes:
                        too_long = True
                        capturing = False
                    elif excerpt_size + current_size <= max_bytes:
                        excerpt.append(bytes(current))
                        excerpt_size += current_size
                    else:
                        capturing = False
                current.clear()
                current_size = 0

            while chunk := stream.read(65536):
                digest.update(chunk)
                total_bytes += len(chunk)
                if b'\x00' in chunk:
                    encoding_error = True
                try:
                    decoder.decode(chunk)
                except UnicodeDecodeError:
                    encoding_error = True
                pieces = chunk.split(b'\n')
                for index, piece in enumerate(pieces):
                    terminated = index < len(pieces) - 1
                    part = piece + (b'\n' if terminated else b'')
                    current_size += len(part)
                    if capturing and start_line <= total_lines + 1 < start_line + max_lines:
                        current.extend(part[:max(0, max_bytes - len(current))])
                    if terminated:
                        finish_line()
            try:
                decoder.decode(b'', final=True)
            except UnicodeDecodeError:
                encoding_error = True
            if current_size:
                finish_line()
            after = os.fstat(stream.fileno())
    except (OSError, ValueError) as exc:
        raise EvidenceError('evidence_missing', f'Evidence source is unavailable: {exc}', 4) from None
    finally:
        if fd is not None:
            os.close(fd)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or total_bytes != after.st_size:
        raise EvidenceError('evidence_changed', 'Evidence source changed while being read; retry from a stable source.', 3)
    actual_sha256 = digest.hexdigest()
    recorded_sha256 = evidence['sha256']
    if recorded_sha256 is not None and actual_sha256 != recorded_sha256:
        raise EvidenceError('evidence_changed', 'Evidence SHA256 differs from the recorded hash; no excerpt returned.', 3)
    if encoding_error:
        raise EvidenceError('evidence_encoding', 'Evidence must be valid UTF-8 text without NUL bytes; no excerpt returned.', 3)
    if too_long:
        raise EvidenceError('evidence_line_too_long', f'A selected line exceeds max_bytes={max_bytes}; increase max_bytes (up to 1048576) or select a different start_line.', 3)
    end_line = start_line + len(excerpt) - 1 if excerpt else None
    next_line = end_line + 1 if end_line is not None and end_line < total_lines else None
    diagnostics = []
    if recorded_sha256 is None:
        diagnostics.append({'severity': 'warning', 'code': 'evidence_unhashed', 'path': pointer,
                            'message': 'No recorded SHA256: this is current source content, not a verified original.'})
    return ({'text': b''.join(excerpt).decode('utf-8'), 'start_line': start_line,
             'end_line': end_line, 'total_lines': total_lines, 'next_line': next_line,
             'truncated': next_line is not None,
             'source': {'kind': evidence['kind'], 'ref': evidence['ref'], 'pointer': pointer,
                        'locator': evidence['locator'], 'recorded_sha256': recorded_sha256,
                        'actual_sha256': actual_sha256, 'byte_count': total_bytes,
                        'hash_state': 'matched' if recorded_sha256 is not None else 'unrecorded'}}, diagnostics)
