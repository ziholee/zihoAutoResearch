"""Explicit human clarification creates a fresh, linked pre-execution plan."""
from copy import deepcopy
from . import research, cli
from .codec import dumps
from .storage import project_lock
from .setup import setup, Cancelled

ALLOWED=('planning','blocked','rejected','awaiting_approval','approved')

def eligible(parent):
    research.require(parent['state'] in ALLOWED and parent['experiment_id'] is None,
        'Only pre-execution sessions can be revised; inspect process/evidence and recover or reconcile first.')
    research.require(parent.get('error')!='inspect_partial_changes_and_records_before_new_session',
        'Inspect partial source changes and records before starting a separate session; this session cannot be revised.')
    research.require(not parent.get('superseded_by'), 'This session already has a revision; continue its child session.')

def revise(root,identifier,*,ask,emit):
    root=root.resolve()
    cli.safe_layout(root/'.autoresearch')
    with project_lock(root/'.autoresearch'):
        parent=research.load(root,identifier);eligible(parent)
        parent_hash=research.digest(parent)
    emit('Answers and feedback are stored locally and sent only after API consent. Do not enter secret values. :cancel cancels before saving.')
    outputs=parent['outputs']
    missing=outputs.get('analysis',{}).get('missing',[])
    prior={role:{k:v for k,v in output.items() if k in ('summary','verdict','missing','hypothesis','uncertainties')}
           for role,output in outputs.items()}
    emit(dumps(dict(parent_session_id=identifier,state=parent['state'],prior_proposal=prior,error=parent.get('error'))))
    result=dict(view='research_setup',parent_session_id=identifier,cancelled=True,saved=False,session=None)
    def text(key,hint,required=False):
        while True:
            value=ask(key+': '+hint+' ')
            if value.strip()==':cancel':raise Cancelled
            if len(value)>4000:emit('Use at most 4000 characters.');continue
            if required and not value.strip():emit('An answer is required.');continue
            return value
    try:
        answers=[dict(question=q,answer=text('answer_'+str(i),q,True)) for i,q in enumerate(missing)]
        feedback=text('feedback','Revision instructions (optional if answers supplied)',not answers)
        context=dict(parent_id=identifier,parent_hash=parent_hash,prior_proposal=prior,answers=answers,feedback=feedback)
        research.require(len(dumps(context).encode())<=32768,'Revision context exceeds 32 KB; use shorter answers or start a separate session.')
        return setup(root,ask=ask,emit=emit,_revision=dict(parent=parent,context=context))
    except (Cancelled,EOFError,KeyboardInterrupt):return result
