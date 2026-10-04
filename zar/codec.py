"""Strict JSON with lossless decimal numbers and no runtime dependencies."""

import json
import math
from decimal import Decimal


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def loads(text):
    """Parse one JSON object, preserving fractional/exponent tokens as Decimal."""
    try:
        value = json.loads(text, parse_float=Decimal, parse_constant=_constant,
                           object_pairs_hook=_pairs)
        def check(item):
            if isinstance(item, str):
                item.encode('utf-8')
            elif isinstance(item, dict):
                for key, child in item.items():
                    check(key)
                    check(child)
            elif isinstance(item, list):
                for child in item:
                    check(child)
        check(value)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('JSON must contain valid Unicode and supported nesting depth') from exc
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    return value


def dumps(value, *, ensure_ascii=False):
    """Serialize JSON without rounding Decimal values through binary floats."""
    def encode(item):
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, Decimal):
            if not item.is_finite():
                raise ValueError("Non-finite decimal")
            return str(item)
        if isinstance(item, int):
            return str(item)
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Non-finite float")
            return json.dumps(item, allow_nan=False)
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=ensure_ascii)
        if isinstance(item, list):
            return "[" + ", ".join(map(encode, item)) + "]"
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError("JSON keys must be strings")
            return "{" + ", ".join(encode(k) + ": " + encode(v) for k, v in item.items()) + "}"
        raise ValueError(f"Unsupported JSON value: {type(item).__name__}")
    return encode(value) + "\n"
