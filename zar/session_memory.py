"""Deterministic provenance for proposed session lessons, not causal validation."""
from copy import deepcopy
import hashlib
from .codec import dumps
from .comparisons import compare_pair

VERSION = 1
EFFECTS = ('helped', 'hurt', 'no_observed_effect', 'confounded', 'insufficient_evidence')


def identity(doc):
    return hashlib.sha256(dumps(doc).encode('utf-8')).hexdigest()


def source_identity(doc, identities=None):
    # The caller owns this memo for exactly one validated records snapshot.
    if identities is None:
        return identity(doc)
    if doc['id'] not in identities:
        identities[doc['id']]=identity(doc)
    return identities[doc['id']]


def build_evidence(session, experiments, *, superseded=None, identities=None):
    """Project only the actual pair. Never accept model-supplied identities."""
    observation=experiments.get(session.get('experiment_id'))
    baseline=experiments.get(observation.get('baseline_id')) if observation else None
    provenance={};handles={}
    for label,doc in (('experiment',observation),('baseline',baseline)):
        if doc is None:
            provenance[label]=None
            continue
        sha=source_identity(doc,identities)
        provenance[label]=dict(id=doc['id'],revision=doc['revision'],sha256=sha,
            comparison=deepcopy(doc['comparison']),environment=deepcopy(doc['environment']),
            run_context=deepcopy(doc.get('run_context')))
        handle=f"experiment:{doc['id']}:{sha}:/execution/score"
        handles[handle]=dict(record_id=doc['id'],revision=doc['revision'],sha256=sha,
            pointer='/execution/score',score=doc['execution']['score'],status=doc['execution']['status'])
    comparison=None;reasons=[]
    if observation is None:reasons.append('missing_experiment')
    if baseline is None:reasons.append('missing_baseline')
    if observation and baseline:
        if any(doc['execution']['score'] is None for doc in (observation,baseline)):
            reasons.append('missing_score')
        else:
            comparison=compare_pair(baseline,observation,experiments,superseded=superseded)
            reasons.extend(comparison['reasons'])
    return dict(version=VERSION,session_id=session['id'],provenance=provenance,
                handles=handles,comparison=comparison,reasons=reasons,evidence_files_checked=False,
                changed_paths=[c['path'] for c in session.get('outputs',{}).get('implementation',{}).get('changes',[])])


def assess(proposal,evidence):
    """Validate citations and report observed direction separately from attribution.

    This first version deliberately never certifies a reusable causal lesson:
    a single pair cannot establish intervention isolation or generalization.
    """
    contrast=proposal.get('contrast');reasons=list(evidence['reasons'])
    claim=contrast['effect'] if contrast else None
    if contrast:
        if not set(contrast['evidence'])<=set(evidence['handles']):
            raise ValueError('Memory referenced evidence outside the supplied contrast handles.')
        if not evidence['handles'] or set(contrast['evidence'])!=set(evidence['handles']):
            reasons.append('incomplete_pair_citations')
    else:reasons.append('missing_contrast')
    comparison=evidence['comparison'];observed=None
    if comparison and comparison['comparable']:
        improvement=comparison['improvement']
        observed='helped' if improvement>0 else 'hurt' if improvement<0 else 'no_observed_effect'
        reasons.append('single_comparison_not_causal_evidence')
    if claim=='confounded':reasons.append('model_reports_confounding')
    if claim=='insufficient_evidence':reasons.append('model_reports_insufficient_evidence')
    if observed and claim in EFFECTS[:3] and claim!=observed:
        reasons.append('claim_disagrees_with_observation')
    reasons.append('intervention_isolation_unverified')
    return dict(version=VERSION,status='hold',claim_effect=claim,observed_effect=observed,evidence_files_checked=False,
                reasons=list(dict.fromkeys(reasons)),provenance=deepcopy(evidence['provenance']),
                comparison=deepcopy(comparison),
                limitation='Recorded score direction only; no verified causal or transferable lesson. Approval is still required.')


def project(session,experiments=None, *, superseded=None, identities=None):
    """Keep the proposal verbatim, recheck saved provenance against current records."""
    saved=session.get('memory_assessment')
    if not isinstance(saved,dict) or saved.get('version')!=VERSION or not isinstance(saved.get('provenance'),dict):
        saved=None
    assessment=deepcopy(saved) if saved else dict(version=VERSION,status='unassessed',
        claim_effect=None,observed_effect=None,reasons=['legacy_or_missing_assessment'])
    if saved:
        assessment['status']='hold'
    if saved and experiments is not None:
        changed=False
        if superseded is None:
            superseded={doc['correction']['supersedes_id'] for doc in experiments.values() if doc.get('correction')}
        for source in saved['provenance'].values():
            if source:
                current=experiments.get(source['id'])
                if current is None or source_identity(current,identities)!=source['sha256'] or source['id'] in superseded:
                    changed=True
        evidence=build_evidence(session,experiments,superseded=superseded,identities=identities)
        try:
            assessment=assess(session['outputs']['memory'],evidence)
        except (ValueError,KeyError,TypeError):
            # An old proposal may cite a replaced record. Preserve it verbatim,
            # but never carry a formerly computed score direction forward.
            assessment=assess({},evidence)
            changed=True
        if changed:
            assessment.update(status='hold',observed_effect=None,comparison=None)
            assessment['reasons']=list(dict.fromkeys(assessment['reasons']+['source_changed']))
    return dict(session_id=session['id'],experiment_id=session['experiment_id'],
                proposal=deepcopy(session['outputs']['memory']),created_at=session['created_at'],assessment=assessment)
