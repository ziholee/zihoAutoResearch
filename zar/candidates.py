"""Author-authored candidate rationale and factual outcomes; no ranking engine."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal

AUTHOR = ('id supersedes_id status hypothesis parent_id analysis evidence exploratory_reason '
          'expected_effect expected_cost uncertainty decision_reason reconsideration memory_ids')


def validate_candidate(doc):
    from .validation import META, Validator
    v = Validator()
    if not v.obj(doc, META + ' ' + AUTHOR + ' conditions', '$'):
        return v.errors
    for key in ('schema_version', 'revision'):
        if type(doc[key]) is not int or doc[key] != 1:
            v.error('$.' + key, 'Immutable candidate requires ' + key + ' 1')
    v.scalar(doc['id'], 'id', '$.id')
    for key in ('supersedes_id', 'parent_id'):
        v.scalar(doc[key], 'id', '$.' + key, True)
    for key in ('created_at', 'updated_at'):
        v.scalar(doc[key], 'time', '$.' + key)
    if doc['created_at'] != doc['updated_at']:
        v.error('$', 'Immutable candidate timestamps must match', 'conflict')
    v.enum(doc['status'], 'proposed selected deferred retired', '$.status')
    for key in ('hypothesis', 'analysis', 'expected_effect', 'uncertainty', 'decision_reason'):
        v.scalar(doc[key], 'str', '$.' + key)
    v.scalar(doc['exploratory_reason'], 'str', '$.exploratory_reason', True)
    v.array(doc['evidence'], v.evidence, '$.evidence')
    if not doc['evidence'] and not doc['exploratory_reason']:
        v.error('$.evidence', 'Evidence or an explicit exploratory reason is required', 'conflict')
    if v.obj(doc['expected_cost'], 'run_seconds note', '$.expected_cost'):
        value = doc['expected_cost']['run_seconds']
        v.scalar(value, 'number', '$.expected_cost.run_seconds', True)
        if type(value) in (int, float, Decimal):
            try:
                if value < 0:
                    v.error('$.expected_cost.run_seconds', 'Must be nonnegative')
            except ArithmeticError:
                pass
        v.scalar(doc['expected_cost']['note'], 'str', '$.expected_cost.note')
    if v.obj(doc['reconsideration'], 'trigger reason', '$.reconsideration'):
        v.enum(doc['reconsideration']['trigger'], 'initial failure stagnation other', '$.reconsideration.trigger')
        v.scalar(doc['reconsideration']['reason'], 'str', '$.reconsideration.reason')
    v.array(doc['memory_ids'], lambda value, path: v.scalar(value, 'id', path), '$.memory_ids')
    if isinstance(doc['memory_ids'], list):
        valid_ids = [value for value in doc['memory_ids'] if isinstance(value, str)]
        if len(set(valid_ids)) != len(valid_ids):
            v.error('$.memory_ids', 'Memory references must be unique')
    if v.obj(doc['conditions'], 'environment comparison', '$.conditions'):
        v.environment(doc['conditions']['environment'], '$.conditions.environment')
        if doc['conditions']['comparison'] is not None:
            v.comparison(doc['conditions']['comparison'], '$.conditions.comparison')
    return v.errors


def prepare_add(body, stamp, project):
    from .validation import Validator
    v = Validator()
    v.obj(body, AUTHOR, '$')
    if v.errors:
        return None, v.errors
    doc = deepcopy(body)
    doc.update(schema_version=1, revision=1, created_at=stamp, updated_at=stamp,
               conditions={key: deepcopy(project[key]) for key in ('environment', 'comparison')})
    return doc, validate_candidate(doc)


def validate_creation(experiment, records):
    from .validation import diagnostic
    identifier = experiment.get('candidate_id')
    if identifier is None:
        return []
    candidates = records.get('candidate', {})
    current = candidates.get(identifier)
    superseded = {doc['supersedes_id'] for doc in candidates.values()}
    if current is None or current['status'] != 'selected' or identifier in superseded:
        return [diagnostic('conflict', 'candidate_id', 'New experiment requires a current selected candidate version')]
    return []


def timestamp_key(value):
    # Schema accepts arbitrary fractional precision; datetime alone truncates it.
    value = value.removesuffix('Z').removesuffix('+00:00')
    seconds, _, fraction = value.partition('.')
    return datetime.fromisoformat(seconds), Decimal('0.' + (fraction or '0'))


def forecast_timing(candidate, experiment):
    """Compare recorded timestamps only; this does not prove forecast authenticity."""
    started = (experiment.get('execution') or {}).get('started_at')
    if candidate is None or started is None:
        return 'unknown'
    return ('recorded_after_execution' if timestamp_key(started) < timestamp_key(candidate['created_at'])
            else 'before_execution')


def validate_links(records, issue):
    """Validate original references; never silently redirect corrected records."""
    candidates, experiments, memories = (records.get(key, {}) for key in ('candidate', 'experiment', 'memory'))
    corrected = {doc['correction']['supersedes_id'] for doc in experiments.values() if doc.get('correction')}
    old_memories = {doc['supersedes_id'] for doc in memories.values()}
    old_candidates = {doc['supersedes_id'] for doc in candidates.values()}
    successors = {}
    for doc in candidates.values():
        parent = doc['parent_id']
        if parent is not None and parent not in experiments:
            issue(doc, 'Candidate references a missing parent experiment')
        if parent in corrected:
            issue(doc, 'Candidate retains a superseded parent experiment', 'candidate_source_superseded', 'warning')
        for identifier in doc['memory_ids']:
            memory = memories.get(identifier)
            if memory is None:
                issue(doc, 'Candidate references a missing memory: ' + identifier)
            elif identifier in old_memories or memory['status'] == 'retired':
                issue(doc, 'Candidate retains a superseded or retired memory: ' + identifier,
                      'candidate_memory_stale', 'warning')
        previous = doc['supersedes_id']
        if previous is None:
            if doc['status'] == 'retired':
                issue(doc, 'Retirement requires a previous candidate')
            continue
        old = candidates.get(previous)
        if old is None or previous == doc['id']:
            issue(doc, 'Invalid candidate supersedes reference')
        else:
            if old['status'] == 'retired':
                issue(doc, 'Retired candidate cannot be superseded')
            if any(doc[key] != old[key] for key in ('hypothesis', 'parent_id')):
                issue(doc, 'Candidate correction changes hypothesis or parent identity')
            if timestamp_key(doc['created_at']) < timestamp_key(old['updated_at']):
                issue(doc, 'Candidate correction predates its predecessor')
        if previous in successors:
            issue(doc, 'Candidate correction history branches')
        successors[previous] = doc['id']
        seen, cursor = {doc['id']}, previous
        while cursor in candidates:
            if cursor in seen:
                issue(doc, 'Candidate correction history contains a cycle')
                break
            seen.add(cursor)
            cursor = candidates[cursor]['supersedes_id']
    for exp in experiments.values():
        identifier = exp.get('candidate_id')
        if identifier is None:
            continue
        candidate = candidates.get(identifier)
        if candidate is None:
            issue(exp, 'Experiment references a missing candidate')
            continue
        if candidate['status'] != 'selected':
            issue(exp, 'Experiment requires a selected candidate version')
        if any(exp[key] != candidate[key] for key in ('hypothesis', 'parent_id')) or any(
                exp[key] != candidate['conditions'][key] for key in ('environment', 'comparison')):
            issue(exp, 'Experiment differs from its selected candidate hypothesis, parent or conditions')
        if forecast_timing(candidate, exp) == 'recorded_after_execution':
            issue(exp, 'Candidate was recorded after execution started; a pre-execution forecast cannot be established',
                  'candidate_forecast_timing', 'warning')
        if identifier in old_candidates:
            issue(exp, 'Experiment retains a superseded selected candidate version', 'candidate_superseded', 'warning')
    # Follow both kinds of ancestry edges with an iterative DFS, including experiment parents.
    nodes = {('candidate', d['id']): [('experiment', d['parent_id'])] if d['parent_id'] else [] for d in candidates.values()}
    nodes.update({('experiment', d['id']): [(kind, value) for kind, value in
                 (('experiment', d.get('parent_id')), ('candidate', d.get('candidate_id'))) if value]
                  for d in experiments.values()})
    done = set()
    for start in nodes:
        if start in done:
            continue
        active, stack = set(), [(start, False)]
        while stack:
            node, leaving = stack.pop()
            if leaving:
                active.discard(node); done.add(node)
            elif node in active:
                kind, identifier = node
                issue(records[kind][identifier], 'Candidate/experiment ancestry contains a cycle')
            elif node not in done and node in nodes:
                active.add(node); stack.append((node, True))
                stack.extend((edge, False) for edge in nodes[node])


def candidate_card(doc, records):
    """Bounded author forecasts beside observed outcomes, without causal scoring."""
    from .comparisons import compare_pair
    truncated = []
    def preview(value, field):
        if isinstance(value, str) and len(value) > 160:
            truncated.append(field)
            return value[:159] + '…'
        return value
    candidates, experiments = records.get('candidate', {}), records.get('experiment', {})
    chain, cursor = {doc['id']}, doc['supersedes_id']
    while cursor in candidates and cursor not in chain:
        chain.add(cursor); cursor = candidates[cursor]['supersedes_id']
    corrected = {d['correction']['supersedes_id'] for d in experiments.values() if d.get('correction')}
    linked = sorted((d for d in experiments.values() if d.get('candidate_id') in chain), key=lambda d:d['id'])
    active = [d for d in linked if d['id'] not in corrected]
    signals = dict(failed=0, interrupted=0, unknown=0, non_improving=0)
    outcomes = []
    for exp in active:
        state = exp['execution']['status']
        if state in ('failed', 'interrupted', 'unknown'):
            signals[state] += 1
        comparison = None
        baseline = experiments.get(exp.get('baseline_id'))
        if baseline is not None:
            comparison = compare_pair(baseline, exp, experiments, superseded=corrected)
            if comparison['comparable'] and comparison['meets_min_delta'] is False:
                signals['non_improving'] += 1
        if len(outcomes) < 3:
            outcomes.append(dict(id=exp['id'], revision=exp['revision'], source=f".autoresearch/experiments/{exp['id']}.json",
                candidate_id=exp['candidate_id'], candidate_pointer='/candidate_id', status=state,
                forecast_timing=forecast_timing(candidates.get(exp['candidate_id']), exp),
                score=exp['execution']['score'], score_pointer='/execution/score', actual_cost_state='unknown',
                comparison=None if comparison is None else {key: comparison[key] for key in
                    ('base_id','comparable','reasons','improvement','meets_min_delta')}))
    evidence = [dict(record_kind='candidate', record_id=doc['id'], record_revision=doc['revision'],
        pointer=f'/evidence/{index}', kind=item['kind'], sha256=item['sha256'],
        ref_preview=preview(item['ref'], f'/evidence/{index}/ref')) for index, item in enumerate(doc['evidence'][:3])]
    memories = records.get('memory', {})
    stale_memories = {item['supersedes_id'] for item in memories.values()}
    stale_refs = []
    if doc['parent_id'] in corrected:
        stale_refs.append(dict(record_kind='experiment', record_id=doc['parent_id'], reason='superseded'))
    memory_sources = []
    for identifier in doc['memory_ids']:
        memory = memories.get(identifier)
        if memory is not None and (identifier in stale_memories or memory['status'] == 'retired'):
            stale_refs.append(dict(record_kind='memory', record_id=identifier,
                                  reason='retired' if memory['status'] == 'retired' else 'superseded'))
        if len(memory_sources) < 3:
            memory_sources.append(dict(record_kind='memory', record_id=identifier,
                record_revision=memory['revision'] if memory else None,
                source=f'.autoresearch/memories/{identifier}.json'))
    return dict(id=doc['id'], revision=doc['revision'], source=f".autoresearch/candidates/{doc['id']}.json",
        status=doc['status'], supersedes_id=doc['supersedes_id'], parent_id=doc['parent_id'],
        author_summary={key: preview(doc[key], 'author_summary.' + key) for key in
            ('hypothesis','analysis','expected_effect','uncertainty','decision_reason','exploratory_reason')},
        expected_cost=dict(run_seconds=doc['expected_cost']['run_seconds'], note=preview(doc['expected_cost']['note'],'expected_cost.note')),
        reconsideration=dict(trigger=doc['reconsideration']['trigger'], reason=preview(doc['reconsideration']['reason'],'reconsideration.reason')),
        memory_sources=memory_sources, stale_refs=stale_refs[:3], stale_refs_omitted=max(0,len(stale_refs)-3),
        memory_ids=doc['memory_ids'][:3], memories_omitted=max(0,len(doc['memory_ids'])-3),
        evidence=evidence, evidence_omitted=len(doc['evidence'])-len(evidence),
        outcomes=outcomes, outcomes_omitted=max(0,len(active)-len(outcomes)), active_outcome_count=len(active),
        superseded_outcome_count=len(linked)-len(active),
        superseded_outcome_sources=[f".autoresearch/experiments/{d['id']}.json" for d in linked if d['id'] in corrected][:3],
        superseded_outcome_sources_omitted=max(0,len(linked)-len(active)-3),
        signals=signals, reconsideration_reminders=[f'{key}: {count} recorded outcome(s); author reassessment needed'
            for key,count in signals.items() if count],
        evidence_checked=False, workspace_verified=False, truncated_fields=truncated)
