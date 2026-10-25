"""Pinned single-role response comparisons; never experiment evidence or approval.

Lifecycle, transmission consent, call budgets and parent freshness belong to the
research controller. This module owns only the bounded, inspectable request pair.
"""
from copy import deepcopy
import hashlib
import json

from .roles import RoleError, role_instructions, role_messages, validate_response

MAX_INSTRUCTION_BYTES = 65_536
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
ARMS = ('original', 'variant')
_FIELDS = {'version', 'role', 'profile', 'context', 'original_instructions',
           'variant_instructions', 'instruction_hashes', 'messages', 'input_hash',
           'profile_hash', 'bundle_hash'}


class VariantError(RoleError):
    """Invalid or changed pinned single-role comparison."""


def _bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise VariantError('Variant comparison must contain finite UTF-8 JSON') from exc


def _hash(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _instruction_hash(text):
    if not isinstance(text, str) or not text.strip():
        raise VariantError('Role variant instructions must be nonempty text')
    try:
        encoded = text.encode('utf-8')
    except UnicodeError as exc:
        raise VariantError('Role instructions must be valid UTF-8') from exc
    if len(encoded) > MAX_INSTRUCTION_BYTES:
        raise VariantError('Role instructions exceed 65536 UTF-8 bytes')
    return hashlib.sha256(encoded).hexdigest()


def prepare(role, context, profile, variant_text):
    """Freeze one context/profile and replace only the role-specific text."""
    if not isinstance(context, dict) or not isinstance(profile, dict):
        raise VariantError('Context and profile must be objects')
    try:
        original = role_instructions(role)
        hashes = dict(original=_instruction_hash(original),
                      variant=_instruction_hash(variant_text))
        b = dict(version=1, role=role, profile=deepcopy(profile), context=deepcopy(context),
                 original_instructions=original, variant_instructions=variant_text,
                 instruction_hashes=hashes,
                 messages={arm: role_messages(role, context, instructions=text)
                           for arm, text in zip(ARMS, (original, variant_text))},
                 input_hash=_hash(context), profile_hash=_hash(profile))
        b['bundle_hash'] = _hash(b)
        if len(_bytes(b)) >= MAX_BUNDLE_BYTES:
            raise VariantError('Variant comparison must be smaller than 2 MiB')
        return b
    except RoleError as exc:
        raise VariantError(str(exc)) from exc


def validate(bundle):
    """Recheck pins and current shared/role instructions before using either arm."""
    if not isinstance(bundle, dict) or set(bundle) != _FIELDS:
        raise VariantError('Invalid variant comparison fields')
    if type(bundle['version']) is not int or bundle['version'] != 1:
        raise VariantError('Unsupported variant comparison version')
    if len(_bytes(bundle)) >= MAX_BUNDLE_BYTES:
        raise VariantError('Variant comparison must be smaller than 2 MiB')
    expected = prepare(bundle['role'], bundle['context'], bundle['profile'],
                       bundle['variant_instructions'])
    if bundle != expected:
        raise VariantError('Pinned comparison or current role instructions changed')


def messages(bundle, arm):
    """Return a fresh transmission copy after checking all immutable pins."""
    if arm not in ARMS:
        raise VariantError('Unknown comparison arm')
    validate(bundle)
    return deepcopy(bundle['messages'][arm])


def compare(bundle, outputs, measurements=None):
    """Describe response differences without choosing or applying a winner."""
    validate(bundle)
    if not isinstance(outputs, dict) or set(outputs) != set(ARMS):
        raise VariantError('A comparison requires both original and variant outputs')
    try:
        checked = {arm: validate_response(bundle['role'], outputs[arm],
                    memory_version=bundle['context'].get('memory_contract_version'))
                   for arm in ARMS}
    except RoleError as exc:
        raise VariantError(str(exc)) from exc
    if measurements is None:
        measurements = {}
    _bytes(measurements)
    original, variant = checked['original'], checked['variant']
    return dict(status='hold', automatic_selection=False,
                reason='response_comparison_is_not_experiment_evidence',
                outputs=checked, measurements=deepcopy(measurements),
                outputs_equal=original == variant,
                changed_fields=sorted(k for k in set(original) | set(variant)
                                      if original.get(k) != variant.get(k)))
