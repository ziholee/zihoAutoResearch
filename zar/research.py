"""Bounded API research sessions. LLM proposals never directly execute tools."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import difflib
import hashlib
import json
from itertools import islice
import os
from pathlib import Path, PureWindowsPath
import re
import queue
import threading
import time
import stat
from types import SimpleNamespace
from uuid import uuid4

from .call_metrics import new_measurement, measure_messages, measure_input_components, record_answer, summarize
from .codec import dumps, loads
from .llm import chat, validate_profile, LLMError
from .roles import compact_context, role_messages, validate_response, RoleError, ROLE_VERSION
from .runner import run
from .research_arguments import add_arguments
from .storage import atomic_write, project_lock

class ResearchError(ValueError):
    pass

PRE = ('analysis','evaluation','planning','implementation','review')
POST = ('interpretation',)

def require(value, message):
    if not value: raise ResearchError(message)

def digest(value):
    return hashlib.sha256(value if isinstance(value,bytes) else dumps(value).encode()).hexdigest()

def records_digest(records):
    """Hash legacy JSON bytes in record batches, without a whole-store string.

    Keep insertion order and the codec's exact separators/newline. Batches hold
    at most 64 document references; a single large document still costs memory.
    No parsed records or serialized bytes survive this call.
    """
    if not isinstance(records, dict) or not all(isinstance(k, str) for k in records):
        raise ValueError('Record groups must be a mapping with string keys')
    result = hashlib.sha256(b'{')
    for group_index, (kind, group) in enumerate(records.items()):
        if not isinstance(group, dict):
            raise ValueError('Record groups must contain mappings')
        if group_index:
            result.update(b', ')
        result.update((dumps(kind)[:-1] + ': {').encode('utf-8'))
        items = iter(group.items())
        first = True
        while batch := dict(islice(items, 64)):
            if not first:
                result.update(b', ')
            # Strip only the outer braces and the codec's final newline.
            result.update(dumps(batch)[1:-2].encode('utf-8'))
            first = False
        result.update(b'}')
    result.update(b'}\n')
    return result.hexdigest()


def safe_path(root, name, *, metadata=False):
    require(isinstance(name,str) and name and '\\' not in name and not PureWindowsPath(name).drive,
            'Expected a project-relative path.')
    path=Path(name)
    require(not path.is_absolute() and '..' not in path.parts, 'Path escapes project.')
    require(metadata or not any(part.startswith('.') for part in path.parts), 'Hidden paths are not available to research tools.')
    current=root
    for part in path.parts:
        current=current/part
        if current.exists() or current.is_symlink():
            mode=current.lstat()
            require(not stat.S_ISLNK(mode.st_mode) and not getattr(mode,'st_file_attributes',0)&0x400,
                    'Redirected paths are not allowed.')
    require(current.resolve().is_relative_to(root), 'Path escapes project.')
    return current

def get_project(root):
    from . import cli
    cli.safe_layout(root/'.autoresearch')
    p=cli.read_document(root/'.autoresearch/project.json')
    cli.enforce(cli.validate_document(p,'project'))
    return p

def session_path(root,identifier):
    require(isinstance(identifier,str) and re.fullmatch(r'session-[a-f0-9]{32}',identifier), 'Invalid session ID.')
    return safe_path(root,f'.autoresearch/sessions/{identifier}.json',metadata=True)

def _read_session(root,identifier):
    p=session_path(root,identifier)
    require(p.is_file(),'Session does not exist.')
    require(p.stat().st_size<=2_000_000,'Session exceeds size limit.')
    return p.read_text(encoding='utf-8')

def load(root,identifier):
    return loads(_read_session(root,identifier))

def save(root,s):
    atomic_write(session_path(root,s['id']),dumps(s))

def snapshot(root,paths):
    out={};total=0
    for name in paths:
        path=safe_path(root,name)
        require(not path.exists() or path.is_file(),'Expected an ordinary file.')
        if path.exists():
            require(path.stat().st_size<=100_000,'Source file exceeds 100 KB.')
            data=path.read_bytes();total+=len(data)
            require(total<=200_000,'Source context exceeds 200 KB.')
            try:content=data.decode('utf-8')
            except UnicodeDecodeError:
                raise ResearchError('Source files must be UTF-8 text: '+name) from None
            out[name]=dict(sha256=digest(data),content=content)
        else:out[name]=dict(sha256=None,content=None)
    return out

def execution_environment(profile):
    allowed=('PATH','SYSTEMROOT','WINDIR','HOME','USERPROFILE','TMP','TEMP','TMPDIR','LANG','LC_ALL','VIRTUAL_ENV','CUDA_VISIBLE_DEVICES')
    env={key:value for key,value in os.environ.items() if key in allowed}
    env.pop(profile.get('api_key_env'),None)
    return env

def assert_fresh(root,s):
    # One snapshot per check; callers may reuse it only within this lock phase.
    from .records import load_records
    project=get_project(root)
    snap=load_records(root,project)
    if s.get('next_context'):
        require(digest(s['next_context'])==s.get('next_context_hash'),'Next context changed; start a new session.')
        require(digest(load(root,s['next_context']['parent_id']))==s['next_context']['parent_hash'],'Parent session changed; start a new session.')
        prior=s['next_context']['experiment']
        require(snap.records['experiment'].get(prior['id'])==prior,'Parent experiment evidence changed; start a new session.')
    if s.get('revision_context'):
        require(digest(s['revision_context'])==s.get('revision_context_hash'),'Revision context changed; create a new revision.')
    require(digest(execution_environment(s['profile']))==s['environment_hash'],'Execution environment changed; start a new session.')
    require(digest(project)==s['project_hash'],'Project settings changed; start a new session.')
    require(snapshot(root,list(s['sources']))==s['sources'],'Source inputs changed; start a new session.')
    require(records_digest(snap.records)==s['records_hash'],'Research records changed; start a new session.')
    return project,snap

def records_identity(root):
    from .records import load_records
    return records_digest(load_records(root,get_project(root)).records)

def token(s):
    return digest(dict({k:s[k] for k in ('id','goal','profile','project_hash','records_hash','sources','command','metric_file','metric_key','outputs','experiment_id','run_context','deadline','max_calls','environment_hash')}, **{k:s[k] for k in ('revision_context','next_context','experiment_mode','baseline_id','memory_contract_version','memory_selection_version') if k in s}))

def next_actions(s):
    """Suggestions only: never infer a stopped process or grant consent."""
    identifier=s['id'];state=s['state'];actions=[]
    def add(action,reason,suffix=''):
        actions.append(dict(action=action,command=f'zar research {action} {identifier}'+suffix,reason=reason))
    if s.get('superseded_by'):
        return [dict(action='status',command='zar research status '+s['superseded_by'],reason='Continue the replacement session; the old approval is invalid.')]
    if state in ('planning','observed','remembering') and s['calls']<s['max_calls'] and datetime.now(timezone.utc).timestamp()<s['deadline']:
        add('advance','Review transmission scope and remaining call/time budget; explicitly consent to the model request.',' --send')
    elif state=='awaiting_approval':
        add('approve','Review the diff and use the current approval_token; approval does not execute.',' --token <approval_token>')
        add('reject','Reject this proposal without executing.')
    elif state=='approved':add('run','Explicitly execute the approved proposal once; inspect its diff first.')
    elif state=='awaiting_decision':add('decide','Review measured evidence and decision; use the current approval_token.',' --token <approval_token>')
    elif state in ('calling','applying','deciding'):
        add('recover','Inspect the previous CLI and child processes first; only confirm after verifying they have stopped. Provider outcome may remain unknown.',' --confirm-stopped')
    elif state in ('executing','unknown'):
        add('reconcile','Inspect actual process/logs and update canonical terminal execution evidence first. Never rerun an unknown launch.')
    if state in ('planning','blocked','rejected','awaiting_approval','approved') and s['experiment_id'] is None and s.get('error')!='inspect_partial_changes_and_records_before_new_session':
        add('revise','Answer missing questions or change settings and create a new plan; saving invalidates the old approval.')
    if state=='complete':add('next','Review retained working files and create a new session; each transmission and execution needs fresh consent.')
    if not actions:
        actions.append(dict(action='inspect',command=f'zar research status {identifier}',reason='Inspect source changes, records and execution evidence before any new session; no automatic retry or next experiment.'))
    return actions

def view(s):
    result=deepcopy(s);result['view']='research_session'
    result['next_actions']=next_actions(s)
    result['transmission']=dict(server=s['profile'].get('base_url'),model=s['profile']['model'],
        files=list(s['sources']), includes='goal, project settings, bounded records, role outputs, revision answers and prior proposal summaries, linked parent experiment and memory proposal if present; no raw logs')
    if s['profile'].get('provider') == 'codex':
        result['transmission'].update(provider='codex', command=s['profile']['command'],
            destination='Service authenticated by the installed Codex CLI; may incur charges')
    return result

def status(root,identifier):
    with project_lock(root/'.autoresearch'):return view(load(root,identifier))

def metrics(root,identifier):
    with project_lock(root/'.autoresearch'):
        s=load(root,identifier)
        return dict(view='research_metrics',session_id=s['id'],state=s['state'],**summarize(s))

def experiment_target(project,records,run_context,mode=None):
    """Resolve an explicit immutable comparator using canonical recorded conditions."""
    selected=project['selected_experiment_id']
    mode=mode or ('candidate' if selected else 'baseline')
    require(mode in ('baseline','candidate'),'Choose baseline or candidate mode.')
    if mode=='baseline':return mode,None
    from .experiments import superseded_ids
    base=records['experiment'].get(selected)
    require(base is not None,'Candidate needs a selected baseline; acquire, keep and select a baseline first.')
    require(base['execution']['status']=='succeeded' and base.get('decision') and base['decision']['status']=='keep' and base['decision']['validity']=='valid','Selected baseline must be succeeded and validly kept.')
    superseded=superseded_ids(records['experiment'].values())
    require(selected not in superseded and base['baseline_id'] not in superseded,'Selected baseline or its baseline is superseded.')
    require(base['comparison']==project['comparison'] and base['environment']==project['environment'] and all(v is not None for v in base['environment'].values()),'Selected baseline comparison/environment is incompatible.')
    require(base.get('run_context') and all(base['run_context'][k]==run_context[k] for k in ('scope','budget_ref')),'Selected baseline run context is incompatible.')
    return mode,selected


def start(root,*,profile,goal,read_paths,command,metric_file,metric_key,max_calls=9,session_seconds=1800,scope='full',seed=None,budget_ref='local-session',mode=None):
    from . import cli
    profile=validate_profile(profile)
    require(isinstance(goal,str) and 0<len(goal.strip())<=10000,'Goal must be 1..10000 characters.')
    require(type(max_calls) is int and 1<=max_calls<=100,'max_calls must be 1..100.')
    require(type(session_seconds) is int and 1<=session_seconds<=86400,'session_seconds must be 1..86400.')
    require(scope in ('proxy','full') and (seed is None or type(seed) is int),'Invalid run context.')
    require(isinstance(budget_ref,str) and bool(budget_ref.strip()),'A budget protocol is required.')
    require(isinstance(metric_key,str) and 0<len(metric_key)<=200,'A top-level JSON metric key is required.')
    with project_lock(root/'.autoresearch'):
        return _start_locked(root,profile=profile,goal=goal,read_paths=read_paths,command=command,metric_file=metric_file,metric_key=metric_key,max_calls=max_calls,session_seconds=session_seconds,scope=scope,seed=seed,budget_ref=budget_ref,mode=mode)

def _start_locked(root,*,profile,goal,read_paths,command,metric_file,metric_key,max_calls,session_seconds,scope,seed,budget_ref,revision_context=None,next_context=None,mode=None):
    from . import cli
    p=get_project(root)
    require(not cli.readiness_missing(p),'Configure project settings first (zar project set).')
    snap=cli.load_records(root,p);cli.enforce(cli.inspect_project(root,p,snapshot=snap))
    require(not any(e['execution']['status'] in ('running','unknown') for e in snap.records['experiment'].values()),'Resolve running/unknown experiments before starting.')
    mode,baseline=experiment_target(p,snap.records,dict(scope=scope,seed=seed,budget_ref=budget_ref),mode)
    commands=[c for c in p['commands'] if c['name']==command]
    require(len(commands)==1,'Choose a unique configured command name.')
    require(safe_path(root,commands[0]['cwd']).is_dir(),'Command cwd is not a directory.')
    require(0<len(read_paths)<=30,'Select 1..30 source files for transmission.')
    sources=snapshot(root,list(dict.fromkeys(read_paths)))
    require(all(v['content'] is not None for v in sources.values()),'Read files must exist.')
    for name in p['editable_paths']:
        safe_path(root,name)
    metric=safe_path(root,metric_file)
    require(metric.parent.is_dir() and not metric.exists(),'Metric destination must be new with an existing parent.')
    require(metric_file not in sources,'Metric output cannot be an input.')
    directory=safe_path(root,'.autoresearch/sessions',metadata=True);directory.mkdir(exist_ok=True)
    s=dict(schema_version=1,id='session-'+uuid4().hex,state='planning',created_at=cli.now(),
           deadline=datetime.now(timezone.utc).timestamp()+session_seconds,session_seconds=session_seconds,goal=goal,profile=profile,
           max_calls=max_calls,calls=0,outputs={},trace=[],sources=sources,project_hash=digest(p),
           records_hash=records_digest(snap.records),command=commands[0],metric_file=metric_file,metric_key=metric_key,
           run_context=dict(scope=scope,seed=seed,budget_ref=budget_ref),experiment_id=None,
           approval_token=None,error=None,environment_hash=digest(execution_environment(profile)))
    s.update(experiment_mode=mode,baseline_id=baseline,memory_contract_version=1,memory_selection_version=1)
    if next_context is not None:
        s['next_context']=deepcopy(next_context);s['next_context_hash']=digest(next_context)
    if revision_context is not None:
        s['revision_context']=deepcopy(revision_context)
        s['revision_context_hash']=digest(revision_context)
    save(root,s);return view(s)

# Bound retained input coverage, not total Python RSS. No full session bodies
# survive a scan; only their digest and the projected memory are retained.
HISTORY_CACHE_MAX_ENTRIES = 2048
HISTORY_CACHE_MAX_BYTES = 8 * 1024 * 1024

def _prior_lessons(root,s,cache=None,*,project=None,experiments=None):
    require('memory_selection_version' not in s or (type(s['memory_selection_version']) is int and s['memory_selection_version']==1),'Unsupported memory selection version.')
    relevant=s.get('memory_selection_version')==1
    if relevant:
        from .memory_selection import classify, rank
        require(project is not None and experiments is not None,'Relevant memory selection requires a current records snapshot.')
        superseded={d['correction']['supersedes_id'] for d in experiments.values() if d.get('correction')}
        identities={}
        counts=dict(eligible=0,matched=0,unknown=0,mismatch=0,source_changed=0,limit=0)
    lessons=[];updated={};retained_bytes=0
    paths=sorted((root/'.autoresearch/sessions').glob('*.json'),key=lambda p:p.name)
    for path in paths:
        if path.stem==s['id']:continue
        # Never trust mtime/size: preserve path checks and reread every role.
        text=_read_session(root,path.stem)
        raw=text.encode('utf-8')
        identity=digest(raw) if cache is not None else None
        prior=cache.get(path.stem) if cache is not None else None
        if prior is not None and prior[0]==identity:
            lesson=prior[1]
        else:
            old=loads(text)
            lesson=None
            if old['state']=='complete' and 'memory' in old['outputs']:
                from .session_memory import project as project_memory
                lesson=project_memory(old)
        if lesson is not None:
            # Retain only selected memories outside the bounded parsing cache.
            # Stable sorting preserves filename order for equal timestamps.
            if relevant:
                counts['eligible']+=1
                selection,excluded=classify(lesson,s,project,experiments,superseded,identities)
                if excluded:
                    counts[excluded]+=1
                else:
                    counts[selection['relevance']]+=1
                    candidate=dict(lesson,**selection)
                    lessons.append(candidate)
                    lessons=sorted(lessons,key=rank,reverse=True)[:5]
            else:
                lessons.append(lesson)
                lessons=sorted(lessons,key=lambda x:x['created_at'])[-5:]
        if cache is not None and len(updated)<HISTORY_CACHE_MAX_ENTRIES and retained_bytes+len(raw)<=HISTORY_CACHE_MAX_BYTES:
            updated[path.stem]=(identity,lesson,len(raw));retained_bytes+=len(raw)
    if cache is not None:
        cache.clear();cache.update(updated)
    if relevant:
        from .session_memory import project as project_memory
        projected=[]
        for item in lessons:
            fresh=project_memory(dict(id=item['session_id'],experiment_id=item['experiment_id'],
                outputs={'memory':item['proposal']},created_at=item['created_at'],
                memory_assessment=item['assessment']),experiments,superseded=superseded,identities=identities)
            fresh.update({key:item[key] for key in ('relevance','condition_matches','selection_reasons','differences')})
            projected.append(fresh)
        counts['limit']=counts['matched']+counts['unknown']-len(projected)
        return projected,dict(version=1,limit=5,counts=counts)
    return deepcopy(sorted(lessons,key=lambda x:x['created_at'])[-5:])

def context(root,s,role,*,checked=None,record_context=None,history_cache=None):
    from . import cli
    if checked is None:
        p=get_project(root);snap=cli.load_records(root,p)
    else:
        p,snap=checked
    if record_context is None:
        data,_=cli.build_context(p,snap.records,[],max_bytes=16384)
    else:
        data=deepcopy(record_context)
    observation=snap.records['experiment'].get(s['experiment_id'])
    comparison=None
    if observation and observation['baseline_id']:
        comparison=cli.compare(snap.records['experiment'][observation['baseline_id']],observation,snap.records['experiment'])
    selected=_prior_lessons(root,s,history_cache,project=p,experiments=snap.records['experiment'])
    selection=None
    if s.get('memory_selection_version')==1:lessons,selection=selected
    else:lessons=selected
    from .session_memory import project as project_memory, build_evidence
    if selection is None:
        superseded={doc['correction']['supersedes_id'] for doc in snap.records['experiment'].values() if doc.get('correction')} if any('provenance' in item['assessment'] for item in lessons) else set()
        lessons=[project_memory(dict(id=item['session_id'],experiment_id=item['experiment_id'],
                    outputs={'memory':item['proposal']},created_at=item['created_at'],
                    memory_assessment=item['assessment']),snap.records['experiment'],superseded=superseded) for item in lessons]
    result=dict(experiment_mode=s.get('experiment_mode','legacy'),baseline_id=s.get('baseline_id'),next_context=s.get('next_context'),revision_context=s.get('revision_context'),prior_lessons=lessons,observation=observation,comparison=comparison,role=role,role_version=ROLE_VERSION,session_id=s['id'],goal=s['goal'],
                project=p,records=data,sources=s['sources'],command=s['command'],
                metric_file=s['metric_file'],metric_key=s['metric_key'],run_context=s['run_context'],
                outputs=s['outputs'],experiment_id=s['experiment_id'],allowed_tools=[])
    if selection is not None:result['memory_selection']=selection
    if s.get('memory_contract_version') == 1:
        result['memory_contract_version']=1
        if role=='memory':result['memory_evidence']=build_evidence(s,snap.records['experiment'])
    return result

def call_api(profile,messages,remaining):
    """Bound local waiting even if DNS/headers exceed a socket timeout.

    A remote request may still finish or be billed; never retry automatically.
    The daemon performs transport only and cannot mutate session/experiment state.
    """
    if profile.get('provider') == 'codex':
        # Own the subprocess in this thread so cancellation waits for cleanup.
        if remaining <= 0:
            raise LLMError('deadline_exceeded','Session deadline reached before agent launch.')
        bounded=deepcopy(profile)
        bounded['timeout_seconds']=min(float(profile.get('timeout_seconds',60)),remaining)
        return chat(bounded,messages)
    result=queue.Queue(maxsize=1)
    def worker():
        try:result.put((True,chat(profile,messages)))
        except BaseException as exc:result.put((False,exc))
    threading.Thread(target=worker,daemon=True).start()
    try:ok,value=result.get(timeout=max(0.001,remaining))
    except queue.Empty:
        raise LLMError('deadline_exceeded','Local wait ended; provider may still process the request.') from None
    if not ok:raise value
    return value

def advance(root,identifier,*,send=False):
    require(send,'Use --send after reviewing session transmission scope; no model request sent.')
    from . import cli
    # Only the bounded projection survives a lock phase, never a reusable snapshot.
    # Each role still rereads/checks records before and after its model call.
    projection_key=None;record_context=None;history_cache={}
    while True:
        with project_lock(root/'.autoresearch'):
            s=load(root,identifier)
            require(s['state'] in ('planning','observed','remembering'),'Session cannot advance in this state.')
            require(s['calls']<s['max_calls'],'Model call budget exhausted.')
            require(datetime.now(timezone.utc).timestamp()<s['deadline'],'Session deadline reached.')
            checked=assert_fresh(root,s)
            sequence=PRE if s['state']=='planning' else ('memory',) if s['state']=='remembering' else POST
            role=next((r for r in sequence if r not in s['outputs']),None)
            require(role is not None,'No pending role.')
            prior=s['state'];s['state']='calling';s['active_role']=role;s['return_state']=prior
            s['calls']+=1;s['error']=None
            key=(s['project_hash'],s['records_hash'])
            if key!=projection_key:
                record_context,_=cli.build_context(checked[0],checked[1].records,[],max_bytes=16384)
                projection_key=key
            payload=context(root,s,role,checked=checked,record_context=record_context,history_cache=history_cache);save(root,s)
            # The payload owns its bounded evidence; release full records before
            # the provider wait and the next independent freshness snapshot.
            del checked
        measurement=new_measurement()
        try:
            profile=deepcopy(s['profile'])
            profile['timeout_seconds']=min(float(profile.get('timeout_seconds',60)),max(0.1,float(s['deadline'])-datetime.now(timezone.utc).timestamp()))
            # Transport JSON uses floats; causal guardrails must retain the
            # exact Decimal comparison derived from the bounded canonical pair.
            memory_evidence=payload.get('memory_evidence')
            payload=compact_context(role,json.loads(dumps(payload)))
            messages=role_messages(role,payload)
            measurement['input_message_bytes']=measure_messages(messages)
            measurement['input_components_bytes']=measure_input_components(messages)
            started=time.perf_counter()
            try:
                answer=call_api(profile,messages,float(s['deadline'])-datetime.now(timezone.utc).timestamp())
            finally:
                measurement['call_seconds']=max(0.0,time.perf_counter()-started)
            record_answer(measurement,answer,profile.get('provider','api'))
            output=validate_response(role,loads(answer['content']),memory_version=s.get('memory_contract_version'))
            assessment=None
            if role=='memory' and s.get('memory_contract_version') == 1:
                from .session_memory import assess
                assessment=assess(output,memory_evidence)
            valid_refs=set(s['sources']) | set(s['outputs']) | {'project','records'} | {v['session_id'] for v in payload['prior_lessons']}
            if s.get('next_context'):valid_refs.update(('next_context',s['next_context']['parent_id'],s['next_context']['experiment']['id']))
            if s.get('baseline_id'):valid_refs.add(s['baseline_id'])
            if s.get('revision_context'):valid_refs.update(('revision_context',s['revision_context']['parent_id']))
            if s['experiment_id']:valid_refs.add(s['experiment_id'])
            require(set(output['evidence'])<=valid_refs,'Role referenced evidence outside the supplied context.')
            if role in ('evaluation','review') and output['verdict']=='pass':
                require(bool(output['evidence']),'A pass needs explicit source references.')
            if role=='implementation':
                require(s.get('experiment_mode')!='baseline' or not output['changes'],'Baseline must execute unchanged source; changes are forbidden.')
                editable=get_project(root)['editable_paths']
                for change in output['changes']:
                    require(change['path'] in editable,'Change must target an exact configured editable file.')
                    require(change['path'] in s['sources'],'Only explicitly transmitted source files can be edited.')
                    require(change['before_sha256']==s['sources'][change['path']]['sha256'],'Change has stale source identity.')
                    require(len(change['content'].encode('utf-8'))<=100_000,'Proposed source exceeds byte limit.')
                proposed={k:v['content'] for k,v in s['sources'].items()}
                proposed.update({c['path']:c['content'] for c in output['changes']})
                require(sum(len(v.encode('utf-8')) for v in proposed.values())<=200_000,'Proposed source context exceeds byte limit.')
            if role=='interpretation' and output['decision']=='keep':
                require(payload['observation']['execution']['status']=='succeeded','A failed or unknown execution cannot be kept.')
                if payload['comparison'] is not None:
                    require(payload['comparison']['comparable'],'Incomparable experiments cannot be kept.')
        except (ValueError,LLMError,OSError,KeyboardInterrupt) as exc:
            with project_lock(root/'.autoresearch'):
                current=load(root,identifier)
                require(current['state']=='calling','Session changed during model call.')
                current['error']=getattr(exc,'code','invalid_role_response')
                # An unconfirmed agent process must not become retryable.
                if current['error']!='agent_cleanup_unconfirmed':current['state']=prior
                current['trace'].append(dict(role=role,version=ROLE_VERSION,result=current['error'],measurement=measurement))
                save(root,current)
            raise ResearchError('Model/role call failed; inspect session error; retry consumes another call.') from None
        with project_lock(root/'.autoresearch'):
            current=load(root,identifier)
            require(current['state']=='calling','Session changed during model call.')
            try:assert_fresh(root,s)
            except ResearchError:
                current['state']='blocked';current['error']='inputs_changed'
                current['trace'].append(dict(role=role,version=ROLE_VERSION,result='inputs_changed',measurement=measurement))
                save(root,current);raise
            s=current;s['state']=prior
            s['outputs'][role]=output
            s['trace'].append(dict(role=role,version=ROLE_VERSION,input_hash=digest(payload),result='validated',usage=answer['usage'],measurement=measurement))
            if role=='analysis' and output['missing']:s['state']='blocked'
            if role in ('evaluation','review') and output['verdict']!='pass':s['state']='blocked'
            if role=='review':
                if s['state']!='blocked':s['state']='awaiting_approval'
                s['diff']=''.join(''.join(difflib.unified_diff(s['sources'][c['path']]['content'].splitlines(True),c['content'].splitlines(True),fromfile=c['path'],tofile=c['path'])) for c in s['outputs']['implementation']['changes'])
            if role=='interpretation':s['state']='awaiting_decision'
            if role=='memory':
                s['state']='complete'
                if assessment is not None:s['memory_assessment']=assessment
            if datetime.now(timezone.utc).timestamp()>s['deadline']:
                s['state']='blocked';s['error']='deadline_exceeded'
            if s['state'] in ('awaiting_approval','awaiting_decision'):s['approval_token']=token(s)
            save(root,s)
            if s['state'] not in ('planning','observed','remembering'):return view(s)

def approve(root,identifier,approval_token):
    with project_lock(root/'.autoresearch'):
        s=load(root,identifier);require(s['state']=='awaiting_approval','No execution approval pending.')
        require(approval_token==s['approval_token']==token(s),'Approval token does not match reviewed proposal.')
        assert_fresh(root,s)
        s['state']='approved';save(root,s);return view(s)

def reject(root,identifier):
    with project_lock(root/'.autoresearch'):
        s=load(root,identifier)
        require(s['state'] in ('planning','blocked','awaiting_approval','approved','observed','awaiting_decision'),'Cannot reject an active/finished session.')
        s['state']='rejected';save(root,s);return view(s)

def artifact_dir(root,s):
    parent=safe_path(root,'.autoresearch/session-artifacts',metadata=True);parent.mkdir(exist_ok=True)
    path=safe_path(root,f'.autoresearch/session-artifacts/{s["id"]}',metadata=True);path.mkdir(exist_ok=True)
    return path

def evidence(root,path):
    return dict(kind='file',ref=path.relative_to(root).as_posix(),locator=None,sha256=digest(path.read_bytes()))

def record(root,p,s,action,body):
    """Use canonical CLI validators while the caller holds the project lock."""
    from . import cli
    path=artifact_dir(root,s)/'record-input.json'
    atomic_write(path,dumps(body))
    args=SimpleNamespace(action=action,file=str(path),id=s['experiment_id'],git_head=False)
    result,_=cli.save_experiment(args,root,p,cli.load_records(root,p))
    return result['experiment']

def run_session(root,identifier):
    from . import cli
    with project_lock(root/'.autoresearch'):
        s=load(root,identifier);require(s['state']=='approved','Execution needs a fresh approval; an attempted launch cannot be repeated.')
        require(s['approval_token']==token(s),'Stored plan changed after approval; obtain a new approval.')
        assert_fresh(root,s)
        require(datetime.now(timezone.utc).timestamp()<s['deadline'],'Session deadline reached.')
        p=get_project(root);snap=cli.load_records(root,p)
        require(cli.budget_used(snap.records['experiment'].values())<p['budget']['max_experiments'],'Experiment budget exhausted.')
        require(not any(e['execution']['status'] in ('running','unknown') for e in snap.records['experiment'].values()),'Resolve running/unknown work first.')
        metric=safe_path(root,s['metric_file']);require(not metric.exists(),'Metric output already exists; use a fresh destination in a new session.')
        cwd=safe_path(root,s['command']['cwd']);require(cwd.is_dir(),'Execution cwd unavailable.')
        changes=s['outputs']['implementation']['changes']
        require(s.get('experiment_mode')!='baseline' or not changes,'Baseline must execute unchanged source; changes are forbidden.')
        if 'experiment_mode' in s:
            _,selected=experiment_target(p,snap.records,s['run_context'],s['experiment_mode'])
            require(selected==s['baseline_id'],'Selected baseline changed.')
        s['state']='applying';save(root,s)  # Crash here requires human inspection, never automatic reapplication.
        for c in changes:atomic_write(safe_path(root,c['path']),c['content'])
        s['sources']=snapshot(root,list(s['sources']))
        s['experiment_id']='exp-'+uuid4().hex
        baseline=s['baseline_id'] if 'experiment_mode' in s else p['selected_experiment_id']
        plan=dict(id=s['experiment_id'],kind='performance' if baseline else 'baseline',
                  hypothesis=s['outputs']['planning']['hypothesis'],parent_id=baseline,baseline_id=baseline,
                  code_ref='source-sha256:'+digest(s['sources']),config_ref='project-sha256:'+s['project_hash'],
                  command=s['command'],review_ids=[],run_context=s['run_context'])
        review_path=artifact_dir(root,s)/'review.json'
        atomic_write(review_path,dumps(dict(evaluation=s['outputs']['evaluation'],review=s['outputs']['review'],
                                           source_hash=digest(s['sources']),role_version=ROLE_VERSION)))
        review_body=dict(id=s['experiment_id']+'-review',supersedes_id=None,code_ref=plan['code_ref'],
            data_ref=p['comparison']['dataset_ref'],items=[dict(id='role-review',topic='API role assessment',
            applicability='Only explicitly transmitted source files and declared comparison settings',
            observation=s['outputs']['review']['summary'],assessment='unverifiable',
            evidence=[evidence(root,review_path)],limitation='Model assessment is not independent ML validity verification.',
            next_action='User inspects proposed changes and observed execution evidence.')])
        review_input=artifact_dir(root,s)/'review-input.json';atomic_write(review_input,dumps(review_body))
        result,_=cli.save_observation(SimpleNamespace(command='review',file=str(review_input)),root,p,cli.load_records(root,p))
        plan['review_ids']=[result['review']['id']]
        exp=record(root,p,s,'create',plan)
        adir=artifact_dir(root,s);intent=adir/'intent.json'
        atomic_write(intent,dumps(dict(session_id=s['id'],experiment_id=s['experiment_id'],command=s['command'],source_hash=digest(s['sources']))))
        exp['execution'].update(status='unknown',note='Launch intent persisted; completion not yet confirmed.',evidence=[evidence(root,intent)])
        record(root,p,s,'update',exp)
        s['state']='executing';save(root,s)
        timeout=min(p['budget']['max_run_seconds'],max(0.1,float(s['deadline'])-datetime.now(timezone.utc).timestamp()))
        # Explicit small environment: do not forward API credentials or unrelated secrets to training.
        env=execution_environment(s['profile'])
    observed=run(s['command']['argv'],cwd,adir/'run.log',timeout,env=env)
    with project_lock(root/'.autoresearch'):
        s=load(root,identifier);require(s['state']=='executing','Execution session changed unexpectedly.')
        p=get_project(root);exp=cli.load_records(root,p).records['experiment'][s['experiment_id']]
        observation=deepcopy(exp)
        execution=observation['execution'];execution.update(observed);execution['score']=None
        execution['note']=execution['note'] or None
        log=adir/'run.log'
        if log.is_file():execution['evidence'].append(evidence(root,log))
        if observed['status']=='succeeded' and (snapshot(root,list(s['sources']))!=s['sources'] or digest(p)!=s['project_hash']):
            execution.update(status='failed',note='Source or project settings changed during execution; provenance is unverified.')
        if execution['status']=='succeeded':
            try:
                metric=safe_path(root,s['metric_file'])
                require(metric.is_file() and metric.stat().st_size<=65536,'Metric JSON missing or too large.')
                data=metric.read_bytes();value=loads(data.decode('utf-8'))[s['metric_key']]
                require(type(value) in (int,float,Decimal) and Decimal(str(value)).is_finite(),'Metric must be a finite number.')
                saved=adir/'metric.json';atomic_write(saved,data.decode('utf-8'))
                execution['score']=value;execution['evidence'].append(evidence(root,saved))
            except (ValueError,OSError,KeyError,TypeError):
                execution.update(status='failed',score=None,note='Command exited zero but configured metric is unavailable or invalid.')
        receipt=adir/'receipt.json';atomic_write(receipt,dumps(execution))
        execution['evidence'].append(evidence(root,receipt))
        exp=record(root,p,s,'update',observation)
        s['state']='unknown' if exp['execution']['status']=='unknown' else 'observed'
        s['sources']=snapshot(root,list(s['sources']))
        s['project_hash']=digest(p);s['records_hash']=records_identity(root)
        save(root,s);return view(s)

def decide(root,identifier,approval_token,*,select=False):
    from . import cli
    with project_lock(root/'.autoresearch'):
        s=load(root,identifier);require(s['state']=='awaiting_decision','No decision pending.')
        require(approval_token==s['approval_token']==token(s),'Decision token changed.')
        assert_fresh(root,s)
        p=get_project(root);snap=cli.load_records(root,p);exp=snap.records['experiment'][s['experiment_id']]
        diagnostics=cli.inspect_project(root,p,snapshot=snap)
        cli.enforce(diagnostics)
        require(not any(d['code'] in ('evidence_missing','evidence_changed','evidence_unhashed') for d in diagnostics),'Evidence must be available and hash-verified before a decision.')
        proposal=s['outputs']['interpretation']
        # Canonical keep rules and evidence checks remain authoritative.
        decision=dict(status=proposal['decision'],reason=proposal['reason'],validity='valid' if exp['execution']['status']=='succeeded' else 'invalid',evidence=exp['execution']['evidence'],next_action='Review observations and decide the next bounded experiment.')
        require(not select or decision['status']=='keep','Only a kept experiment can be selected.')
        after=deepcopy(p)
        if select:
            after['selected_experiment_id']=s['experiment_id'];after['revision']+=1;after['updated_at']=cli.now()
        s['state']='deciding';s['decision_intent']=dict(decision=decision,select=select,revision=exp['revision'],project_after=after)
        save(root,s)
        finish_decision(root,s)
        save(root,s);return view(s)


def finish_decision(root,s):
    from . import cli
    p=get_project(root);snap=cli.load_records(root,p);exp=snap.records['experiment'][s['experiment_id']]
    intent=s['decision_intent']
    require(digest(execution_environment(s['profile']))==s['environment_hash'],'Execution environment changed during decision recovery.')
    require(digest(p) in (s['project_hash'],digest(intent['project_after'])),'Project changed during decision recovery.')
    diagnostics=cli.inspect_project(root,p,snapshot=snap)
    cli.enforce(diagnostics)
    require(not any(d['code'] in ('evidence_missing','evidence_changed','evidence_unhashed') for d in diagnostics),'Evidence must remain hash-verified during decision recovery.')
    require(snapshot(root,list(s['sources']))==s['sources'],'Sources changed during decision recovery; inspect manually.')
    if exp['decision']!=intent['decision']:
        require(exp['revision']==intent['revision'],'Experiment changed during decision; inspect manually.')
        record(root,p,s,'decide',dict(revision=exp['revision'],decision=intent['decision']))
    if intent['select'] and p['selected_experiment_id']!=s['experiment_id']:
        require(digest(p)==s['project_hash'],'Project changed during selection; inspect manually.')
        p=deepcopy(intent['project_after'])
        cli.enforce(cli.inspect_project(root,p))
        atomic_write(root/'.autoresearch/project.json',dumps(p))
    s['project_hash']=digest(p);s['records_hash']=records_identity(root);s['state']='remembering'


def reconcile(root,identifier):
    """Resume only after canonical execution evidence has been reconciled explicitly."""
    from . import cli
    with project_lock(root/'.autoresearch'):
        s=load(root,identifier);require(s['state'] in ('executing','unknown'),'Only an attempted launch can be reconciled.')
        p=get_project(root);snap=cli.load_records(root,p);cli.enforce(cli.inspect_project(root,p,snapshot=snap))
        exp=snap.records['experiment'].get(s['experiment_id'])
        require(exp is not None and exp['execution']['status'] in ('succeeded','failed','interrupted'),'Verify actual process/logs, then update the canonical experiment with new evidence first.')
        s['state']='observed';s['sources']=snapshot(root,list(s['sources']));s['project_hash']=digest(p);s['records_hash']=records_identity(root)
        save(root,s);return view(s)



def recover(root,identifier,*,confirm_stopped=False):
    require(confirm_stopped,'Confirm the previous CLI process is stopped before recovery.')
    with project_lock(root/'.autoresearch'):
        s=load(root,identifier)
        require(s['state'] in ('calling','applying','deciding'),'Use reconcile for an attempted experiment launch.')
        if s['state']=='calling':
            s['state']=s['return_state'];s['error']='previous_api_outcome_unknown'
        elif s['state']=='applying':
            s['state']='blocked';s['error']='inspect_partial_changes_and_records_before_new_session'
        else:
            finish_decision(root,s)
        save(root,s);return view(s)


def dispatch(root,args):
    from . import cli
    if args.action in ('setup','revise','next'):
        import sys
        from .setup import setup
        require(root.is_dir(), 'Project root must be an existing directory.')
        require(sys.stdin.isatty(), 'Interactive setup requires a terminal; use project set and research start for automation.')
        def ask(prompt):
            cli.emit_text(prompt,stream=sys.stderr)
            line=sys.stdin.readline()
            if not line:raise EOFError
            return line.rstrip('\r\n')
        if args.action=='next':
            from .continuation import next_session
            return next_session(root,args.id,ask=ask,emit=lambda message:cli.emit_text(message,stream=sys.stderr))
        if args.action=='revise':
            from .revision import revise
            return revise(root,args.id,ask=ask,emit=lambda message:cli.emit_text(message,stream=sys.stderr))
        return setup(root,ask=ask,emit=lambda message:cli.emit_text(message,stream=sys.stderr))
    cli.safe_layout(root/'.autoresearch')
    if args.action=='start':
        require(not(args.profile and any((args.base_url,args.model,args.api_key_env,args.provider,args.codex_command))), 'Choose a profile file or connection flags, not both.')
        if args.profile:
            profile=cli.read_document(Path(args.profile))
        elif args.provider=='codex':
            require(not(args.base_url or args.api_key_env),'Codex uses its own authentication; omit API connection flags.')
            profile=dict(provider='codex',command=args.codex_command or 'codex',model=args.model)
        else:
            require(not args.codex_command,'--codex-command requires --provider codex.')
            profile=dict(base_url=args.base_url,model=args.model,api_key_env=args.api_key_env)
        return start(root,profile=profile,goal=args.goal,read_paths=args.read,command=args.run_command,
                     metric_file=args.metric_file,metric_key=args.metric_key,max_calls=args.max_calls,
                     session_seconds=args.session_seconds,scope=args.scope,seed=args.seed,budget_ref=args.budget_ref,mode=args.mode)
    if args.action=='recover':return recover(root,args.id,confirm_stopped=args.confirm_stopped)
    if args.action=='advance':return advance(root,args.id,send=args.send)
    if args.action=='approve':return approve(root,args.id,args.token)
    if args.action=='decide':return decide(root,args.id,args.token,select=args.select)
    return {'status':status,'metrics':metrics,'reject':reject,'run':run_session,'reconcile':reconcile}[args.action](root,args.id)
