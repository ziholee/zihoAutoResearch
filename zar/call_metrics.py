"""Local call observations, without estimates or provider metadata retention.

Message bytes count UTF-8 message content prepared for a call, not network
traffic. Token counts are independently reported counters; missing is not zero.
"""
import math
from decimal import Decimal


TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens')
COUNT_LIMIT = 2**63 - 1


def _count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        if not 0 <= value <= COUNT_LIMIT or value != int(value):
            return None
        return int(value)
    except (ValueError, OverflowError, ArithmeticError):
        return None


def _seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, OverflowError):
        return None


def new_measurement():
    return {'version': 1, 'call_seconds': None, 'input_message_bytes': None,
            'output_text_bytes': None, 'tokens': dict.fromkeys(TOKEN_FIELDS)}


def measure_messages(messages):
    """Count message content only; the caller supplies validated text messages."""
    return sum(len(message['content'].encode('utf-8')) for message in messages)


def record_answer(measurement, answer, provider):
    """Retain only response text length and recognized, bounded numeric usage."""
    if not isinstance(answer, dict):
        return
    content = answer.get('content')
    measurement['output_text_bytes'] = len(content.encode('utf-8')) if isinstance(content, str) else None
    usage = answer.get('usage')
    usage = usage if isinstance(usage, dict) else {}
    if provider == 'codex':
        fields = {name: name for name in TOKEN_FIELDS}
        cached = usage.get('cached_input_tokens')
    else:
        fields = {'input_tokens': 'prompt_tokens', 'output_tokens': 'completion_tokens',
                  'total_tokens': 'total_tokens'}
        details = usage.get('prompt_tokens_details')
        cached = details.get('cached_tokens') if isinstance(details, dict) else None
    measurement['tokens'] = {name: _count(usage.get(fields.get(name))) for name in TOKEN_FIELDS}
    measurement['tokens']['cached_input_tokens'] = _count(cached)


def _counter():
    return {'value': None, 'observations': 0}


def _bucket():
    return {'attempts': 0, 'measured_attempts': 0, 'unmeasured_attempts': 0,
            'call_seconds': _counter(), 'input_message_bytes': _counter(),
            'output_text_bytes': _counter(), 'tokens': {name: _counter() for name in TOKEN_FIELDS}}


def _add(counter, value):
    if value is not None:
        counter['value'] = (counter['value'] or 0) + value
        counter['observations'] += 1


def _observe(bucket, measurement):
    bucket['measured_attempts'] += 1
    _add(bucket['call_seconds'], _seconds(measurement.get('call_seconds')))
    for name in ('input_message_bytes', 'output_text_bytes'):
        _add(bucket[name], _count(measurement.get(name)))
    tokens = measurement.get('tokens')
    if isinstance(tokens, dict):
        for name in TOKEN_FIELDS:
            _add(bucket['tokens'][name], _count(tokens.get(name)))


def summarize(session):
    """Read-only partial totals. Legacy/crash gaps remain explicitly unmeasured."""
    total, roles = _bucket(), {}
    total['attempts'] = _count(session.get('calls')) or 0
    for entry in session.get('trace', []):
        if not isinstance(entry, dict):
            continue
        role = entry.get('role')
        if not isinstance(role, str):
            continue
        bucket = roles.setdefault(role, _bucket())
        bucket['attempts'] += 1
        measurement = entry.get('measurement')
        if (isinstance(measurement, dict) and type(measurement.get('version')) is int
                and measurement['version'] == 1):
            _observe(bucket, measurement)
            _observe(total, measurement)
    for bucket in [total, *roles.values()]:
        bucket['unmeasured_attempts'] = max(0, bucket['attempts'] - bucket['measured_attempts'])
    return {'version': 1, 'total': total, 'roles': roles}
