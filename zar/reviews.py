"""Prepare immutable review records; findings remain scoped observations."""
from copy import deepcopy

from .validation import Validator, validate_document


def prepare_add(body, stamp):
    """Accept author fields only and generate canonical record metadata."""
    validator = Validator()
    validator.obj(body, 'id supersedes_id code_ref data_ref items', '$')
    if validator.errors:
        return None, validator.errors
    candidate = deepcopy(body)
    candidate.update(schema_version=1, revision=1, created_at=stamp, updated_at=stamp)
    return candidate, validate_document(candidate, 'review')
