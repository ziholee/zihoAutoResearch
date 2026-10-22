"""Declared-condition recall, independent of lesson validity or execution consent."""
from .session_memory import VERSION, source_identity

COMPARISON = ('id','dataset_ref','split_ref','metric','direction','evaluation_ref','min_delta')
ENVIRONMENT = ('os','runtime','device')


def _match(left,right,keys):
    left=left or {};right=right or {}
    if any(left.get(k) is not None and right.get(k) is not None and left[k]!=right[k] for k in keys):
        return 'mismatch'
    if any(left.get(k) is None or right.get(k) is None for k in keys):
        return 'unknown'
    return 'matched'


def classify(lesson,session,project,experiments,superseded,identities):
    """Use only recorded provenance, never the model's applicability prose.

    Identifiable missing/corrected sources are excluded even for old memories.
    Legacy memories cannot establish original conditions from today's records.
    """
    identifier=lesson.get('experiment_id')
    if identifier and (identifier not in experiments or identifier in superseded):
        return None,'source_changed'
    assessment=lesson['assessment']
    provenance=assessment.get('provenance') if assessment.get('version')==VERSION else None
    provenance=provenance if isinstance(provenance,dict) else {}
    for source in provenance.values():
        if not source:continue
        current=experiments.get(source.get('id'))
        if current is None or current['id'] in superseded or source_identity(current,identities)!=source.get('sha256'):
            return None,'source_changed'
    # Reprojection rejects stale/invented citations. Check before top-k so a
    # rejected newest proposal cannot displace a usable older memory.
    contrast=lesson['proposal'].get('contrast')
    if 'provenance' in assessment and contrast:
        observation=experiments.get(identifier)
        baseline=experiments.get(observation.get('baseline_id')) if observation else None
        handles={f"experiment:{doc['id']}:{source_identity(doc,identities)}:/execution/score"
                 for doc in (observation,baseline) if doc is not None}
        try:
            contrast['effect']  # Required by the same conservative reassessment.
            valid=set(contrast['evidence'])<=handles
        except (KeyError,TypeError):
            valid=False
        if not valid:return None,'source_changed'
    source=provenance.get('experiment') or {}
    # The provenance must refer to the session's actual observation.
    if source and source.get('id')!=identifier:
        return None,'source_changed'
    # Hash-validated current records are authoritative; saved condition copies
    # cannot override them if history metadata was edited.
    source=experiments[identifier] if source else {}
    context=source.get('run_context') or {}
    target=session.get('run_context') or {}
    matches=dict(comparison=_match(source.get('comparison'),project.get('comparison'),COMPARISON),
                 environment=_match(source.get('environment'),project.get('environment'),ENVIRONMENT),
                 scope=_match(context,target,('scope',)),budget_ref=_match(context,target,('budget_ref',)))
    if 'mismatch' in matches.values():return None,'mismatch'
    relevance='matched' if all(v=='matched' for v in matches.values()) else 'unknown'
    reasons=[key+'_'+value for key,value in matches.items()]
    if not source:reasons.append('original_conditions_unavailable')
    reasons.append('relevance_does_not_validate_effect_or_grant_approval')
    differences={}
    if context.get('seed') is not None and target.get('seed') is not None and context['seed']!=target['seed']:
        differences['seed']=dict(source=context['seed'],current=target['seed'])
    original=experiments.get(identifier) if source else None
    current=experiments.get(session.get('experiment_id')) or experiments.get(session.get('baseline_id'))
    if original and current:
        for key in ('code_ref','config_ref'):
            if key in original and key in current and original[key]!=current[key]:
                differences[key]=dict(source=original[key],current=current[key])
    return dict(relevance=relevance,condition_matches=matches,selection_reasons=reasons,differences=differences),None


def rank(lesson):
    return (lesson['relevance']=='matched',lesson['created_at'],lesson['session_id'])
