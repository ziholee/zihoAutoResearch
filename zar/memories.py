"""Immutable author-authored failure memories with explicit recorded provenance."""
from copy import deepcopy
from datetime import datetime

AUTHOR = 'id supersedes_id status cause remedy limitation evidence failure_experiment_id resolution_experiment_id'
CONDITIONS = ('environment', 'comparison', 'code_ref', 'config_ref')


def validate_memory(doc):
    from .validation import Validator, META
    v = Validator()
    if not v.obj(doc, META + ' ' + AUTHOR + ' conditions', '$'):
        return v.errors
    for key in ('schema_version', 'revision'):
        if type(doc[key]) is not int or doc[key] != 1:
            v.error('$.' + key, 'Immutable memory requires ' + key + ' 1')
    for key in ('id', 'failure_experiment_id'):
        v.scalar(doc[key], 'id', '$.' + key)
    for key in ('supersedes_id', 'resolution_experiment_id'):
        v.scalar(doc[key], 'id', '$.' + key, True)
    for key in ('created_at', 'updated_at'):
        v.scalar(doc[key], 'time', '$.' + key)
    if doc['created_at'] != doc['updated_at']:
        v.error('$', 'Immutable memory timestamps must match', 'conflict')
    v.enum(doc['status'], 'active retired', '$.status')
    for key in ('cause', 'limitation'):
        v.scalar(doc[key], 'str', '$.' + key)
    v.scalar(doc['remedy'], 'str', '$.remedy', True)
    if doc['status'] == 'active' and doc['resolution_experiment_id'] is not None and not doc['remedy']:
        v.error('$.remedy', 'Recorded resolution requires an author remedy', 'conflict')
    v.array(doc['evidence'], v.evidence, '$.evidence', True)
    if v.obj(doc['conditions'], ' '.join(CONDITIONS), '$.conditions'):
        v.environment(doc['conditions']['environment'], '$.conditions.environment')
        v.comparison(doc['conditions']['comparison'], '$.conditions.comparison')
        for key in ('code_ref', 'config_ref'):
            v.scalar(doc['conditions'][key], 'str', '$.conditions.' + key)
    return v.errors


def prepare_add(body, stamp, experiments):
    from .validation import Validator
    v = Validator()
    v.obj(body, AUTHOR, '$')
    if v.errors:
        return None, v.errors
    v.scalar(body['failure_experiment_id'], 'id', '$.failure_experiment_id')
    if v.errors:
        return None, v.errors
    failed = experiments.get(body['failure_experiment_id'])
    if failed is None:
        v.error('$.failure_experiment_id', 'Failure experiment does not exist', 'conflict')
        return None, v.errors
    candidate = deepcopy(body)
    candidate.update(schema_version=1, revision=1, created_at=stamp, updated_at=stamp,
                     conditions={key: deepcopy(failed[key]) for key in CONDITIONS})
    return candidate, validate_memory(candidate)


def _resolution_scope(failed, resolution):
    """Compare declared scope/budget only; different random seeds are allowed."""
    left = (failed or {}).get('run_context') or {}
    right = (resolution or {}).get('run_context') or {}
    keys = ('scope', 'budget_ref')
    if any(left.get(key) is not None and right.get(key) is not None and
           left[key] != right[key] for key in keys):
        return 'mismatch'
    if any(left.get(key) is None or right.get(key) is None for key in keys):
        return 'unknown'
    return 'matched'


def validate_links(records, issue):
    """Validate schema-valid records without changing their original references."""
    experiments = records['experiment']
    memories = records.get('memory', {})
    corrected = {d['correction']['supersedes_id'] for d in experiments.values() if d.get('correction')}
    successors = {}
    for doc in memories.values():
        failed = experiments.get(doc['failure_experiment_id'])
        resolution = experiments.get(doc['resolution_experiment_id'])
        if failed is None:
            issue(doc, 'Memory references a missing failure experiment')
        else:
            execution, decision = failed['execution'], failed.get('decision')
            historical_discards = [entry['decision'] for entry in failed.get('decision_history', [])
                                   if entry['decision']['status'] == 'discard']
            if execution['status'] not in ('failed', 'interrupted') and not ((decision and decision['status'] == 'discard') or historical_discards):
                issue(doc, 'Memory source requires failed/interrupted execution or discard decision')
            if any(doc['conditions'][key] != failed[key] for key in CONDITIONS):
                issue(doc, 'Memory conditions differ from the original failure experiment')
            support = (execution['evidence'] + (decision['evidence'] if decision else []) +
                       [item for old_decision in historical_discards for item in old_decision['evidence']])
            if not any(e in doc['evidence'] for e in support):
                issue(doc, 'Memory must retain at least one failure execution or decision evidence item')
        if doc['resolution_experiment_id'] is not None:
            if resolution is None or resolution['execution']['status'] != 'succeeded':
                issue(doc, 'Memory resolution requires a succeeded experiment')
            else:
                if resolution['id'] == doc['failure_experiment_id']:
                    issue(doc, 'Resolution must differ from the failure experiment')
                if failed and any(resolution[key] != failed[key] for key in ('environment', 'comparison')):
                    issue(doc, 'Resolution must retain failure environment and comparison')
                if failed and _resolution_scope(failed, resolution) == 'mismatch':
                    issue(doc, 'Resolution run scope and budget must match the failure experiment')
                if not any(e in doc['evidence'] for e in resolution['execution']['evidence']):
                    issue(doc, 'Memory must retain at least one resolution execution evidence item')
        for ref in (doc['failure_experiment_id'], doc['resolution_experiment_id']):
            if ref in corrected:
                issue(doc, 'Memory retains a superseded experiment reference: ' + ref,
                      'memory_source_superseded', 'warning')
        previous = doc['supersedes_id']
        if previous is None:
            if doc['status'] == 'retired':
                issue(doc, 'Retirement requires a previous active memory')
            continue
        old = memories.get(previous)
        if old is None or previous == doc['id']:
            issue(doc, 'Invalid memory supersedes reference')
        else:
            if old['status'] != 'active':
                issue(doc, 'Retired memory cannot be superseded')
            if any(doc[key] != old[key] for key in ('failure_experiment_id', 'conditions')):
                issue(doc, 'Memory correction changes failure identity or conditions')
            if datetime.fromisoformat(doc['created_at'].replace('Z', '+00:00')) < datetime.fromisoformat(old['updated_at'].replace('Z', '+00:00')):
                issue(doc, 'Memory correction predates its predecessor')
        if previous in successors:
            issue(doc, 'Memory correction history branches')
        successors[previous] = doc['id']
        seen, cursor = {doc['id']}, previous
        while cursor in memories:
            if cursor in seen:
                issue(doc, 'Memory correction history contains a cycle')
                break
            seen.add(cursor)
            cursor = memories[cursor]['supersedes_id']


def memory_card(doc, experiments, anchor, *, corrected=None):
    """Bounded recall hints; matches only declared fields, never workspace truth."""
    truncated = []

    def preview(value, field):
        if isinstance(value, str) and len(value) > 160:
            truncated.append(field)
            return value[:159] + '…'
        return value

    def source(identifier):
        original = experiments.get(identifier)
        return None if original is None else dict(record_kind='experiment', record_id=identifier,
            record_revision=original['revision'], source=f'.autoresearch/experiments/{identifier}.json')

    def match(expected, observed):
        if expected is None or observed is None:
            return 'unknown'
        if isinstance(expected, dict) and isinstance(observed, dict):
            states = [match(expected.get(key), observed.get(key)) for key in expected.keys() | observed.keys()]
            if 'mismatch' in states:
                return 'mismatch'
            return 'unknown' if not states or 'unknown' in states else 'matched'
        return 'matched' if expected == observed else 'mismatch'

    failed = experiments.get(doc['failure_experiment_id'])
    applicability, reasons = {}, []
    resolution_scope = _resolution_scope(failed, experiments.get(doc['resolution_experiment_id']))
    if doc['resolution_experiment_id'] is not None and resolution_scope != 'matched':
        reasons.append('resolution_scope: ' + resolution_scope)
    for key in (*CONDITIONS, 'run_context'):
        expected = (failed or {}).get(key) if key == 'run_context' else doc['conditions'][key]
        observed = (anchor or {}).get(key)
        state = match(expected, observed)
        applicability[key] = state
        if state != 'matched':
            reasons.append(key + ': ' + state)
    if corrected is None:
        corrected = {d['correction']['supersedes_id'] for d in experiments.values() if d.get('correction')}
    stale = any(ref in corrected for ref in (doc['failure_experiment_id'], doc['resolution_experiment_id']))
    if stale:
        reasons.append('source experiment superseded; reassess original observation')
    handles = []
    for index, item in enumerate(doc['evidence'][:3]):
        pointer = '/evidence/' + str(index)
        handles.append(dict(record_kind='memory', record_id=doc['id'], record_revision=doc['revision'],
            pointer=pointer, kind=item['kind'], sha256=item['sha256'],
            ref_preview=preview(item['ref'], pointer + '.ref')))
    return dict(id=doc['id'], revision=doc['revision'], source=f".autoresearch/memories/{doc['id']}.json",
        status=doc['status'], supersedes_id=doc['supersedes_id'],
        author_summary={key: preview(doc[key], 'author_summary.' + key) for key in ('cause', 'remedy', 'limitation')},
        failure_source=source(doc['failure_experiment_id']), resolution_source=source(doc['resolution_experiment_id']),
        resolution_state='recorded' if doc['resolution_experiment_id'] else 'unresolved',
        resolution_scope=resolution_scope,
        applicability=('mismatch' if stale or 'mismatch' in applicability.values() or
                       (doc['resolution_experiment_id'] is not None and resolution_scope == 'mismatch') else
                       'unknown' if 'unknown' in applicability.values() or
                       (doc['resolution_experiment_id'] is not None and resolution_scope == 'unknown') else 'matched'),
        condition_matches=applicability, applicability_reasons=reasons, stale_source=stale,
        evidence_checked=False, workspace_verified=False, evidence=handles,
        evidence_omitted=len(doc['evidence']) - len(handles), truncated_fields=truncated)
