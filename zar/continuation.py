"""A completed session supplies bounded evidence to a new consent-gated session."""
from copy import deepcopy
from . import research, cli
from .codec import dumps
from .storage import project_lock
from .setup import setup


def next_session(root,identifier,*,ask,emit):
    root=root.resolve();cli.safe_layout(root/'.autoresearch')
    with project_lock(root/'.autoresearch'):
        parent=research.load(root,identifier)
        research.require(parent['state']=='complete','Only a complete session can seed the next experiment; finish or reconcile it first.')
        project=research.get_project(root);records=cli.load_records(root,project)
        diagnostics=cli.inspect_project(root,project,snapshot=records);cli.enforce(diagnostics)
        research.require(not any(d['code'] in ('evidence_missing','evidence_changed','evidence_unhashed') for d in diagnostics),'Verify recorded evidence before continuing.')
        experiment=records.records['experiment'].get(parent['experiment_id'])
        research.require(experiment is not None and experiment.get('decision') and experiment['execution']['status'] in ('succeeded','failed','interrupted'),'Parent needs a terminal canonical experiment and decision.')
        context=dict(records_hash=research.records_digest(records.records),parent_id=identifier,parent_hash=research.digest(parent),experiment=deepcopy(experiment),memory_proposal=deepcopy(parent['outputs'].get('memory')))
        from .session_memory import project as project_memory
        if 'memory' in parent['outputs']:
            context['memory_assessment']=project_memory(parent,records.records['experiment'])['assessment']
        research.require(len(dumps(context).encode())<=32768,'Next context exceeds 32 KB; start a separate session.')
    emit(dumps(dict(parent_session_id=identifier,experiment_id=experiment['id'],decision=experiment['decision'],score=experiment['execution']['score'],selected_baseline=project['selected_experiment_id'])))
    if not project['selected_experiment_id']:emit('No selected baseline: acquire an unchanged baseline, then explicitly keep and select it before candidate comparison.')
    return setup(root,ask=ask,emit=emit,_next=dict(parent=parent,context=context))
