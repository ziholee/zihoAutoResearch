"""Pure experiment creation and update rules; never execute a command."""
from copy import deepcopy

from .validation import Validator, diagnostic, validate_document

CREATE_FIELDS = 'id kind hypothesis parent_id baseline_id code_ref config_ref command review_ids'
TERMINAL = {'succeeded', 'failed', 'interrupted'}
TRANSITIONS = {
    'planned': {'planned', 'running', 'unknown', 'cancelled', *TERMINAL},
    'running': {'running', 'unknown', *TERMINAL},
    'unknown': {'unknown', 'running', 'cancelled', *TERMINAL},
    **{state: {state} for state in TERMINAL},
    'cancelled': {'cancelled'},
}


def prepare_create(body, project, stamp):
    validator = Validator()
    validator.obj(body, CREATE_FIELDS, '$')
    if validator.errors:
        return None, validator.errors
    candidate = deepcopy(body)
    candidate.update(schema_version=1, revision=1, created_at=stamp, updated_at=stamp,
                     comparison=deepcopy(project['comparison']), environment=deepcopy(project['environment']),
                     execution=dict(status='planned', started_at=None, finished_at=None, exit_code=None,
                                    score=None, evidence=[], artifacts=[], note=None),
                     decision=None, decision_history=[], correction=None)
    return candidate, validate_document(candidate, 'experiment')


def validate_update(current, candidate):
    errors = validate_document(candidate, 'experiment')
    if errors:
        return errors

    def conflict(path, message):
        errors.append(diagnostic('conflict', path, message))

    # Only execution is caller-editable; revision is an optimistic concurrency token.
    for field in current:
        if field not in ('execution', 'updated_at', 'correction') and candidate[field] != current[field]:
            conflict(field, f'{field} must match the stored record.')
    if candidate.get('correction') != current.get('correction'):
        conflict('correction', 'Correction lineage cannot be changed by update.')
    old, new = current['execution'], candidate['execution']
    if new['status'] not in TRANSITIONS[old['status']]:
        conflict('execution.status', 'Invalid execution state transition.')
    for field in ('started_at', 'finished_at'):
        if old[field] is not None and old[field] != new[field]:
            conflict('execution.' + field, 'An observed timestamp cannot be changed.')
    if old['status'] in TERMINAL | {'cancelled'}:
        for field in old:
            if field != 'artifacts' and old[field] != new[field]:
                conflict('execution.' + field, 'Completed execution results are immutable.')
    if old['status'] == 'planned' and new['status'] in TERMINAL | {'unknown'} and not new['evidence']:
        conflict('execution.evidence', 'Recording a completed run requires observation evidence.')
    if old['status'] == 'unknown' and new['status'] != 'unknown':
        if not any(item not in old['evidence'] for item in new['evidence']):
            conflict('execution.evidence', 'Resolving unknown requires new confirmation evidence.')
    previous_evidence = old['evidence']
    if new['evidence'][:len(previous_evidence)] != previous_evidence:
        conflict('execution.evidence', 'Existing evidence cannot be removed, reordered or changed.')
    previous = old['artifacts']
    if new['artifacts'][:len(previous)] != previous:
        conflict('execution.artifacts', 'Existing artifacts cannot be removed, reordered or changed.')
    paths = [artifact['path'] for artifact in new['artifacts']]
    if len(paths) != len(set(paths)):
        conflict('execution.artifacts', 'Each artifact version requires a distinct path.')
    return errors


def superseded_ids(records):
    return {doc['correction']['supersedes_id'] for doc in records if doc.get('correction')}


def budget_used(records):
    return sum(not doc.get('correction') and doc['execution']['status'] != 'cancelled' for doc in records)


def prepare_correction(current, body, stamp):
    validator = Validator()
    if validator.obj(body, 'id revision execution reason evidence', '$'):
        validator.scalar(body['id'], 'id', '$.id')
        validator.scalar(body['revision'], 'positive', '$.revision')
        validator.scalar(body['reason'], 'str', '$.reason')
        validator.array(body['evidence'], validator.evidence, '$.evidence', True)
        validator.execution(body['execution'], '$.execution')
    if validator.errors:
        return None, validator.errors
    errors = []
    for condition, message in (
        (body['revision'] != current['revision'], 'Revision must match the original record.'),
        (body['id'] == current['id'], 'Correction requires a new ID.'),
        (current['execution']['status'] not in TERMINAL, 'Only completed executions can be corrected.'),
        (body['execution']['status'] not in TERMINAL, 'A correction must describe a completed execution.'),
        (body['execution']['artifacts'] != current['execution']['artifacts'], 'Correction cannot change artifacts; append new artifacts after correction.'),
    ):
        if condition:
            errors.append(diagnostic('conflict', '$', message))
    candidate = deepcopy(current)
    candidate.update(id=body['id'], revision=1, created_at=stamp, updated_at=stamp,
                     execution=deepcopy(body['execution']), decision=None, decision_history=[],
                     correction=dict(supersedes_id=current['id'], reason=body['reason'], evidence=deepcopy(body['evidence'])))
    return candidate, errors + validate_document(candidate, 'experiment')
