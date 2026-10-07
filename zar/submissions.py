"""Prepare observed external results; never submit or retrieve external scores."""
from copy import deepcopy

from .validation import Validator, validate_document


def prepare_add(body, stamp):
    validator = Validator()
    validator.obj(body, 'id supersedes_id experiment_id competition external_id artifact '
                  'leaderboard metric direction score submitted_at observed_at evidence', '$')
    if validator.errors:
        return None, validator.errors
    candidate = deepcopy(body)
    candidate.update(schema_version=1, revision=1, created_at=stamp, updated_at=stamp)
    return candidate, validate_document(candidate, 'submission')
