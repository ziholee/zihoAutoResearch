"""Explicit, non-executing paired role calls with the parent's existing budget."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import time
from uuid import uuid4

from . import research as r
from . import skill_variant as variant
from .codec import dumps, loads
from .storage import atomic_write, project_lock
from .call_metrics import new_measurement, measure_messages, measure_input_components, record_answer


def path(root, identifier):
    r.require(isinstance(identifier,str) and re.fullmatch(r'variant-[a-f0-9]{32}',identifier),'Invalid comparison ID.')
    return r.safe_path(root,'.autoresearch/variants/'+identifier+'.json',metadata=True)


def load(root, identifier):
    p=path(root,identifier)
    r.require(p.is_file() and p.stat().st_size<=4_000_000,'Comparison missing or too large.')
    return json.loads(p.read_text(encoding='utf-8'))


def save(root, comparison):
    text=dumps(comparison)
    r.require(len(text.encode('utf-8'))<=4_000_000,'Comparison exceeds size limit.')
    atomic_write(path(root,comparison['id']),text)


def parent_identity(s):
    return r.digest({k:v for k,v in s.items() if k not in ('state','calls','trace','active_comparison')})


def approval(c):
    return r.digest({k:c[k] for k in ('id','parent_id','parent_hash','return_state','bundle','variant_file','variant_sha256','deadline','max_calls')})


def text_file(root,name):
    p=r.safe_path(root,name)
    r.require(p.is_file() and p.stat().st_size<=65536,'Variant must be a UTF-8 file of at most 65536 bytes.')
    raw=p.read_bytes()
    r.require(len(raw)<=65536,'Variant exceeds byte limit.')
    return raw.decode('utf-8'),r.digest(raw)


def payload(root,s,role,checked):
    return r.compact_context(role,json.loads(dumps(r.context(root,s,role,checked=checked))))


def owned_parent(root,c):
    s=r.load(root,c['parent_id'])
    r.require(s['state']=='comparing' and s.get('active_comparison')==c['id'],'Parent is not suspended for this comparison.')
    r.require(parent_identity(s)==c['parent_hash'],'Parent session changed.')
    return s


def fresh(root,c):
    s=owned_parent(root,c)
    r.require(approval(c)==c['approval_token'],'Comparison approval inputs changed.')
    variant.validate(c['bundle'])
    _,sha=text_file(root,c['variant_file'])
    r.require(sha==c['variant_sha256'],'Variant file changed; cancel and prepare a new comparison.')
    checked=r.assert_fresh(root,s)
    current=payload(root,s,c['bundle']['role'],checked)
    r.require(current==c['bundle']['context'],'Role context or session history changed.')
    r.require(json.loads(dumps(s['profile']))==c['bundle']['profile'] and float(s['deadline'])==c['deadline'] and s['max_calls']==c['max_calls'],'Profile or budget changed.')
    return s


def view(c):
    return dict(deepcopy(c),view='role_variant_comparison')


def prepare(root,identifier,filename):
    with project_lock(root/'.autoresearch'):
        s=r.load(root,identifier)
        r.require(s['state'] in ('planning','observed','remembering'),'Comparison requires a pending role, not an approved or running experiment.')
        r.require(s['max_calls']-s['calls']>=2,'Comparison needs two remaining parent calls.')
        r.require(time.time()<s['deadline'],'Session deadline reached.')
        checked=r.assert_fresh(root,s)
        sequence=r.PRE if s['state']=='planning' else ('memory',) if s['state']=='remembering' else r.POST
        role=next((x for x in sequence if x not in s['outputs']),None)
        r.require(role is not None,'No pending role.')
        text,sha=text_file(root,filename)
        bundle=variant.prepare(role,payload(root,s,role,checked),json.loads(dumps(s['profile'])),text)
        c=dict(version=1,id='variant-'+uuid4().hex,state='awaiting_approval',parent_id=identifier,
               parent_hash=parent_identity(s),return_state=s['state'],bundle=bundle,
               variant_file=filename,variant_sha256=sha,deadline=s['deadline'],max_calls=s['max_calls'],
               arms={arm:dict(state='pending') for arm in variant.ARMS},summary=None,error=None)
        c['approval_token']=approval(c)
        r.safe_path(root,'.autoresearch/variants',metadata=True).mkdir(exist_ok=True)
        save(root,c)
        s['state']='comparing';s['active_comparison']=c['id'];r.save(root,s)
        return view(c)


def status(root,identifier):
    with project_lock(root/'.autoresearch'):return view(load(root,identifier))


def approve(root,identifier,token):
    with project_lock(root/'.autoresearch'):
        c=load(root,identifier)
        r.require(c['state']=='awaiting_approval','Comparison is not awaiting approval.')
        r.require(token==c['approval_token']==approval(c),'Comparison token changed.')
        fresh(root,c)
        c['state']='approved';save(root,c);return view(c)


def release(root,c):
    s=r.load(root,c['parent_id'])
    if s.get('active_comparison')==c['id']:
        r.require(s['state']=='comparing','Unexpected parent state; inspect before recovery.')
        s['state']=c['return_state'];s.pop('active_comparison',None);r.save(root,s)


def finish(root,c):
    valid=all(c['arms'][a]['state']=='validated' for a in variant.ARMS)
    if valid:
        c['summary']=variant.compare(c['bundle'],{a:c['arms'][a]['output'] for a in variant.ARMS},
                                    {a:c['arms'][a]['measurement'] for a in variant.ARMS})
    else:
        c['summary']=dict(status='hold',automatic_selection=False,reason='incomplete_or_invalid_pair')
    c['state']='complete';save(root,c);release(root,c)


def validate_output(root,s,c,answer):
    role=c['bundle']['role'];context=c['bundle']['context']
    output=r.validate_response(role,loads(answer['content']),memory_version=s.get('memory_contract_version'))
    refs=set(s['sources'])|set(s['outputs'])|{'project','records'}|{v['session_id'] for v in context['prior_lessons']}
    if s.get('next_context'):refs.update(('next_context',s['next_context']['parent_id'],s['next_context']['experiment']['id']))
    if s.get('revision_context'):refs.update(('revision_context',s['revision_context']['parent_id']))
    refs.update(v for v in (s.get('baseline_id'),s.get('experiment_id')) if v)
    r.require(set(output['evidence'])<=refs,'Response references unavailable evidence.')
    if role in ('evaluation','review') and output['verdict']=='pass':r.require(output['evidence'],'Pass needs evidence.')
    if role=='implementation':
        r.require(s.get('experiment_mode')!='baseline' or not output['changes'],'Baseline cannot change source.')
        editable=r.get_project(root)['editable_paths'];proposed={k:v['content'] for k,v in s['sources'].items()}
        for change in output['changes']:
            r.require(change['path'] in editable and change['path'] in s['sources'],'Change outside allowed source.')
            r.require(change['before_sha256']==s['sources'][change['path']]['sha256'],'Stale proposed change.')
            r.require(len(change['content'].encode('utf-8'))<=100000,'Proposed source too large.')
            proposed[change['path']]=change['content']
        r.require(sum(len(v.encode('utf-8')) for v in proposed.values())<=200000,'Proposed context too large.')
    if role=='interpretation' and output['decision']=='keep':
        r.require(context['observation']['execution']['status']=='succeeded','Unknown or failed run cannot be kept.')
        r.require(context['comparison'] is None or context['comparison']['comparable'],'Incomparable results cannot be kept.')
    if role=='memory' and s.get('memory_contract_version')==1:
        from .session_memory import assess, build_evidence
        from .records import load_records
        # Retain canonical Decimal precision rather than transport floats.
        evidence=build_evidence(s,load_records(root,r.get_project(root)).records['experiment'])
        assessment=assess(output,evidence)
    else:assessment=None
    return output,assessment


def advance(root,identifier,*,send=False):
    r.require(send,'Use --send to transmit the approved request pair.')
    while True:
        with project_lock(root/'.autoresearch'):
            c=load(root,identifier)
            r.require(c['state']=='approved','Comparison needs approval or explicit recovery.')
            s=fresh(root,c)
            arm=next((a for a in variant.ARMS if c['arms'][a]['state']=='pending'),None)
            if arm is None:finish(root,c);return view(c)
            r.require(s['calls']<s['max_calls'],'Parent call budget exhausted.')
            remaining=float(s['deadline'])-time.time()
            timeout=float(s['profile'].get('timeout_seconds',60))
            r.require(remaining>=timeout,'Insufficient remaining time for the pinned per-call timeout.')
            messages=variant.messages(c['bundle'],arm)
            measurement=new_measurement();measurement['input_message_bytes']=measure_messages(messages)
            measurement['input_components_bytes']=measure_input_components(messages)
            # Charge before launch; crashes may conservatively consume an unused slot.
            s['calls']+=1;r.save(root,s)
            c['state']='calling';c['active_arm']=arm
            c['arms'][arm]=dict(state='calling',measurement=measurement)
            save(root,c)
        started=time.perf_counter()
        try:
            answer=r.call_api(deepcopy(c['bundle']['profile']),messages,remaining)
            measurement['call_seconds']=max(0.0,time.perf_counter()-started)
            record_answer(measurement,answer,s['profile'].get('provider','api'))
        except (ValueError,OSError,r.LLMError,KeyboardInterrupt) as exc:
            measurement['call_seconds']=max(0.0,time.perf_counter()-started)
            with project_lock(root/'.autoresearch'):
                c=load(root,identifier)
                c['state']='unknown';c['error']=getattr(exc,'code','provider_outcome_unknown')
                c['arms'][arm].update(state='unknown',measurement=measurement)
                save(root,c)
            raise r.ResearchError('Comparison call outcome may be unknown; confirm stopped before recovery. No automatic retry.') from None
        with project_lock(root/'.autoresearch'):
            c=load(root,identifier)
            r.require(c['state']=='calling' and c.get('active_arm')==arm,'Comparison changed during call.')
            try:s=fresh(root,c)
            except (ValueError,OSError):
                c['state']='blocked';c['error']='inputs_changed';c['arms'][arm].update(state='invalid',measurement=measurement)
                save(root,c)
                raise r.ResearchError('Comparison inputs changed; cancel and prepare again.') from None
            try:
                output,assessment=validate_output(root,s,c,answer)
                result=dict(state='validated',output=output,measurement=measurement)
                if assessment is not None:result['assessment']=assessment
            except (ValueError,OSError,KeyError,TypeError):
                result=dict(state='invalid',error='invalid_role_response',measurement=measurement)
            c['arms'][arm]=result;c['state']='approved';c.pop('active_arm',None)
            s['trace'].append(dict(role=c['bundle']['role'],version=r.ROLE_VERSION,comparison_id=c['id'],arm=arm,
                                  result='variant_'+result['state'],measurement=measurement))
            r.save(root,s)
            if time.time()>=float(c['deadline']):
                c['state']='blocked';c['error']='deadline_exceeded'
                c['summary']=dict(status='hold',automatic_selection=False,reason='deadline_exceeded')
                save(root,c)
                raise r.ResearchError('Comparison deadline reached; inspect and cancel without extending the parent budget.')
            save(root,c)
            if all(c['arms'][a]['state']!='pending' for a in variant.ARMS):finish(root,c);return view(c)


def recover(root,identifier,*,confirm_stopped=False):
    r.require(confirm_stopped,'Confirm the previous comparison CLI and provider process have stopped.')
    with project_lock(root/'.autoresearch'):
        c=load(root,identifier)
        if c['state'] in ('complete','cancelled'):
            release(root,c);return view(c)
        r.require(c['state'] in ('calling','unknown'),'Only an interrupted comparison call needs recovery.')
        owned_parent(root,c)
        arm=c['active_arm'];c['arms'][arm]['state']='unknown'
        c['state']='approved';c['error']='previous_api_outcome_unknown';c.pop('active_arm',None)
        # Never resend the attempted arm. Any other pending arm needs explicit send.
        save(root,c)
        return view(c)


def cancel(root,identifier):
    with project_lock(root/'.autoresearch'):
        c=load(root,identifier)
        r.require(c['state'] in ('awaiting_approval','approved','blocked'),'Confirm stopped before cancelling an unknown/calling comparison.')
        owned_parent(root,c)
        c['state']='cancelled';c['summary']=dict(status='hold',automatic_selection=False,reason='cancelled')
        save(root,c);release(root,c);return view(c)
