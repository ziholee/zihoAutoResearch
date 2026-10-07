"""Bounded, deterministic projections of canonical records, never a new memory store."""
from collections import Counter
from datetime import datetime
import hashlib

from .codec import dumps
from .experiments import budget_used, superseded_ids
from .validation import readiness_missing


class ContextError(Exception):
    def __init__(self, code, message, exit_code=3):
        self.code, self.message, self.exit_code = code, message, exit_code
        super().__init__(message)


def snapshot_identity(project, records):
    digest = hashlib.sha256(dumps(project).encode('utf-8'))
    for kind, group in sorted(records.items()):
        digest.update(kind.encode('ascii'))
        for identifier, doc in sorted(group.items()):
            digest.update(identifier.encode('ascii'))
            digest.update(dumps(doc).encode('utf-8'))
    return digest.hexdigest()


def preview(value, field, truncated, limit=160):
    if isinstance(value, str) and len(value) > limit:
        truncated.append(field)
        return value[:limit] + '…'
    return value


def card(doc, corrected):
    truncated = []
    out = {key:doc[key] for key in ('id', 'revision', 'kind', 'parent_id', 'baseline_id')}
    out.update(source=f".autoresearch/experiments/{doc['id']}.json",
               status=doc['execution']['status'], score=doc['execution']['score'],
               comparison_id=preview(doc['comparison']['id'], 'comparison_id', truncated),
               corrected_by=corrected.get(doc['id']))
    for key in ('hypothesis','code_ref','config_ref'):
        out[key] = preview(doc[key], key, truncated)
    out['note'] = preview(doc['execution']['note'], 'note', truncated)
    out['run_context'] = doc.get('run_context')
    if out['run_context']:
        out['run_context'] = dict(out['run_context'])
        out['run_context']['budget_ref'] = preview(out['run_context']['budget_ref'], 'run_context.budget_ref', truncated)
    decision = doc['decision']
    out['decision'] = None if decision is None else {
        key:preview(decision[key], 'decision.'+key, truncated)
        for key in ('status','validity','reason','next_action')}
    # Handles target current evidence, not duplicated historical decisions.
    sources = [('/execution/evidence', doc['execution']['evidence'])]
    if decision: sources.append(('/decision/evidence', decision['evidence']))
    if doc.get('correction'): sources.append(('/correction/evidence', doc['correction']['evidence']))
    evidence = []
    count = sum(len(items) for _, items in sources)
    for prefix, items in sources:
        for index, item in enumerate(items):
            if len(evidence) == 3: break
            pointer = prefix + '/' + str(index)
            evidence.append(dict(record_kind='experiment', record_id=doc['id'], record_revision=doc['revision'], pointer=pointer,
                                 kind=item['kind'], sha256=item['sha256'],
                                 ref_preview=preview(item['ref'], pointer+'.ref', truncated)))
    out.update(evidence=evidence, evidence_omitted=count-len(evidence), truncated_fields=truncated)
    return out


def build_context(project, records, diagnostics, *, experiment=None, limit=5,
                  offset=0, max_bytes=16384, snapshot=None):
    if not 1 <= limit <= 100 or offset < 0 or not 2048 <= max_bytes <= 1048576:
        raise ContextError('arguments', 'limit: 1..100; offset: >=0; max-bytes: 2048..1048576.', 2)
    experiments = records['experiment']
    if experiment is not None and experiment not in experiments:
        raise ContextError('conflict', 'Focus experiment does not exist.')
    identity = snapshot_identity(project, records)
    if snapshot is not None and identity != snapshot:
        raise ContextError('conflict', 'Records changed since the requested snapshot; restart pagination.')
    selected = project['selected_experiment_id']
    focus = experiment or selected
    anchor = experiments.get(focus)
    ordering, seen = [], set()

    def add(identifier):
        if identifier in experiments and identifier not in seen:
            ordering.append(identifier); seen.add(identifier)

    add(focus); add(selected)
    # Preserve explicit ancestry, including correction ancestors, without redirecting refs.
    cursor = 0
    while cursor < len(ordering):
        doc = experiments[ordering[cursor]]
        add(doc['baseline_id']); add(doc['parent_id'])
        if doc.get('correction'): add(doc['correction']['supersedes_id'])
        cursor += 1
    recent = sorted(experiments.values(), key=lambda d:(
        datetime.fromisoformat(d['created_at'].replace('Z','+00:00')), d['id']), reverse=True)
    for doc in recent:
        if doc['execution']['status'] in ('unknown','running','planned'): add(doc['id'])
    for doc in recent:
        related = anchor is None or (doc['comparison'] == anchor['comparison'] and doc['environment'] == anchor['environment'])
        if related and (doc['execution']['status'] in ('failed','interrupted') or
                        (doc['decision'] and doc['decision']['status'] in ('discard','hold'))): add(doc['id'])
    for doc in recent: add(doc['id'])
    corrected = {d['correction']['supersedes_id']:d['id'] for d in recent if d.get('correction')}
    states = Counter(d['execution']['status'] for d in recent)
    missing = readiness_missing(project)
    fields = []
    counts = dict(experiments=len(recent), unknown=states['unknown'],
                  unfinished=sum(states[s] for s in ('planned','running','unknown')),
                  failed=states['failed'], interrupted=states['interrupted'],
                  superseded=len(superseded_ids(recent)), reviews=len(records['review']),
                  submissions=len(records['submission']))
    counts['unselected_keep'] = sum(d['id'] not in corrected and d['id'] != selected and
        d['decision'] is not None and d['decision']['status'] == 'keep' for d in recent)
    diagnostic_counts = Counter((d['severity'],d['code']) for d in diagnostics)
    compact_diagnostics = [dict(severity=severity, code=code, path='.autoresearch',
                               message=f'{count} occurrence(s); run check for full evidence diagnostics.')
                           for (severity,code),count in sorted(diagnostic_counts.items())]
    cards = [card(experiments[identifier], corrected) for identifier in ordering[offset:offset+limit]]
    data = dict(view='research_context', snapshot_id=identity, project_id=project['id'], revision=project['revision'],
                project_source='.autoresearch/project.json', program_source='.autoresearch/program.md',
                objective=preview(project['objective'],'objective',fields),
                next_action=preview(project['next_action'],'next_action',fields),
                comparison_id=preview(project['comparison']['id'], 'comparison_id', fields) if project['comparison'] else None,
                selected_experiment_id=selected, focus_experiment_id=focus,
                ready=not missing, missing=missing, budget=project['budget'], budget_used=budget_used(recent),
                counts=counts, safeguards=dict(has_unfinished=bool(counts['unfinished']),
                    has_unknown=bool(counts['unknown']), evidence_checked=False, workspace_verified=False,
                    budget_exhausted=project['budget']['max_experiments'] is not None and
                        budget_used(recent) >= project['budget']['max_experiments']),
                cards=cards, truncated_fields=fields,
                diagnostic_counts=[dict(severity=s,code=c,count=n) for (s,c),n in sorted(diagnostic_counts.items())],
                page={}, omissions={})
    while True:
        returned = len(cards)
        next_offset = offset+returned if offset+returned < len(ordering) else None
        data['page'] = dict(offset=offset, returned=returned, total=len(ordering), next_offset=next_offset)
        data['omissions'] = dict(cards=len(ordering)-returned,
                                 fields=len(fields)+sum(len(c['truncated_fields']) for c in cards),
                                 evidence=sum(c['evidence_omitted'] for c in cards),
                                 diagnostic_details=len(diagnostics))
        # cli.main prints dumps() (which already ends with LF), adding another LF.
        size = len(dumps(dict(ok=True,data=data,diagnostics=compact_diagnostics), ensure_ascii=True).encode('ascii'))+1
        if size <= max_bytes: return data, compact_diagnostics
        if len(cards) <= 1:
            raise ContextError('output_budget', 'Required context does not fit max-bytes; increase the budget or request a later offset.')
        cards.pop()
