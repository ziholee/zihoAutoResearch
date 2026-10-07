"""Recorded-condition comparison and explicit decisions; no ML execution."""
from copy import deepcopy
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
from fractions import Fraction

from .experiments import superseded_ids
from .validation import Validator, diagnostic, validate_document


def exact_difference(candidate, base):
    # Align all decimal places, including values exceeding the default precision 28.
    a, b = Decimal(candidate), Decimal(base)
    exponent = min(a.as_tuple().exponent, b.as_tuple().exponent)
    precision = max(a.adjusted(), b.adjusted()) - exponent + 3
    with localcontext() as context:
        context.prec = max(precision, 1)
        context.Emax, context.Emin = MAX_EMAX, MIN_EMIN
        return a - b


def pair_reasons(base, candidate, records):
    reasons = []
    superseded = superseded_ids(records.values())
    if base['id'] == candidate['id']: reasons.append('same_experiment')
    for label, doc in (('base', base), ('candidate', candidate)):
        if doc['id'] in superseded: reasons.append(label + '_superseded')
        if doc['baseline_id'] in superseded: reasons.append('baseline_superseded')
        if doc['execution']['status'] != 'succeeded': reasons.append(label + '_not_succeeded')
        if doc['decision'] and doc['decision']['validity'] != 'valid': reasons.append(label + '_invalid_decision')
    if base['comparison'] != candidate['comparison']: reasons.append('comparison_mismatch')
    if base['environment'] != candidate['environment']: reasons.append('environment_mismatch')
    if any(v is None for doc in (base,candidate) for v in doc['environment'].values()):
        reasons.append('environment_unknown')
    left, right = base.get('run_context'), candidate.get('run_context')
    if left is None or right is None:
        reasons.append('run_context_unknown')
    else:
        if left['scope'] != right['scope']: reasons.append('scope_mismatch')
        if left['budget_ref'] != right['budget_ref']: reasons.append('budget_mismatch')
    return list(dict.fromkeys(reasons))


def ratio(value):
    return dict(numerator=value.numerator, denominator=value.denominator)


def repeat_summary(anchor, records):
    superseded = superseded_ids(records.values())
    members, excluded = [], []
    anchor_ids = {anchor['id']}
    cursor = anchor
    while cursor.get('correction'):
        previous = cursor['correction']['supersedes_id']
        if previous in anchor_ids or previous not in records: break
        anchor_ids.add(previous)
        cursor = records[previous]
    for doc in sorted(records.values(), key=lambda d:d['id']):
        if doc['id'] != anchor['id'] and not (doc['kind'] == 'confirmation' and doc['parent_id'] in anchor_ids):
            continue
        same_plan = (all(doc[key] == anchor[key] for key in ('code_ref','config_ref','comparison','environment','command'))
                     and all(value is not None for value in doc['environment'].values()))
        context, expected = doc.get('run_context'), anchor.get('run_context')
        known = context is not None and expected is not None
        compatible = known and all(context[key] == expected[key] for key in ('scope','budget_ref'))
        valid = doc['execution']['status'] == 'succeeded' and (not doc['decision'] or doc['decision']['validity'] == 'valid')
        if doc['id'] in superseded or doc['baseline_id'] in superseded or not (same_plan and compatible and valid):
            excluded.append(doc['id']); continue
        members.append(doc)
    scores = [Fraction(d['execution']['score']) for d in members]
    n = len(scores)
    mean = sum(scores, Fraction()) / n if n else None
    variance = sum(((x-mean)**2 for x in scores), Fraction()) / (n-1) if n > 1 else None
    seeds = [d['run_context']['seed'] for d in members]
    return dict(count=n, experiment_ids=[d['id'] for d in members], excluded_ids=excluded,
                distinct_known_seeds=len({s for s in seeds if s is not None}),
                unknown_seed_count=seeds.count(None), mean=ratio(mean) if mean is not None else None,
                sample_variance=ratio(variance) if variance is not None else None,
                limitation='Recorded runs only; seed independence and evidence truth are not verified.')


def compare(base, candidate, records):
    reasons = pair_reasons(base, candidate, records)
    raw = improvement = meets = None
    if not reasons:
        raw = exact_difference(candidate['execution']['score'], base['execution']['score'])
        improvement = raw if base['comparison']['direction'] == 'maximize' else raw.copy_negate()
        meets = improvement > 0 and improvement >= base['comparison']['min_delta']
    return dict(base_id=base['id'], candidate_id=candidate['id'], comparable=not reasons,
                reasons=reasons, raw_delta=raw, improvement=improvement,
                min_delta=base['comparison']['min_delta'], meets_min_delta=meets,
                repeats=dict(base=repeat_summary(base,records), candidate=repeat_summary(candidate,records)))


def prepare_decision(current, body, records, stamp):
    v = Validator()
    if v.obj(body, 'revision decision', '$'):
        v.scalar(body['revision'], 'positive', '$.revision')
        v.decision(body['decision'], '$.decision')
    if v.errors: return None, v.errors
    if body['revision'] != current['revision']:
        return None, [diagnostic('conflict','revision','Revision must match stored experiment.')]
    candidate = deepcopy(current)
    candidate['decision'] = deepcopy(body['decision'])
    candidate['decision_history'].append(dict(decided_at=stamp,decision=deepcopy(body['decision'])))
    candidate['revision'] += 1
    candidate['updated_at'] = stamp
    errors = validate_document(candidate, 'experiment')
    if not errors and candidate['decision']['status'] == 'keep':
        if candidate['baseline_id'] is not None:
            # Evaluate the proposed decision, so a prior invalid assessment can be revised.
            overlay = dict(records); overlay[candidate['id']] = candidate
            reasons = pair_reasons(records[candidate['baseline_id']], candidate, overlay)
        else:
            reasons = []
            if candidate.get('run_context') is None: reasons.append('run_context_unknown')
            if any(v is None for v in candidate['environment'].values()): reasons.append('environment_unknown')
        if reasons:
            errors.append(diagnostic('conflict','decision','Keep requires comparable recorded conditions: ' + ', '.join(reasons)))
    return candidate, errors
