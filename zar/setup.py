"""Consent-gated questionnaire for one configured LLM research session."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from . import cli, research
from .codec import dumps
from .llm import validate_profile
from .storage import atomic_write, project_lock


class Cancelled(Exception):
    pass


def setup(root, *, ask, emit, _revision=None, _next=None):
    """Collect settings without writes; save and transmission are separate consent."""
    root=root.resolve()
    research.require(root.is_dir(),'Project root must already exist.')
    store=root/'.autoresearch'
    existing=store.exists() or store.is_symlink()
    if existing:
        cli.safe_layout(store)
        with project_lock(store):
            original=research.get_project(root)
            original_hash=research.digest(original)
            records_hash=research.records_identity(root)
            if _next:research.require(records_hash==_next['context']['records_hash'],'Research records changed before next setup; start again.')
    else:
        stamp=cli.now()
        original=dict(schema_version=1,id='project-'+str(uuid4()),revision=1,created_at=stamp,updated_at=stamp,
            name=None,objective=None,comparison=None,environment=dict(os=None,runtime=None,device=None),
            commands=[],budget=dict(max_experiments=None,max_run_seconds=None),editable_paths=[],
            selected_experiment_id=None,next_action=None)
    defaults=(_revision or _next or {}).get('parent',{})
    result=dict(view='research_setup',cancelled=False,saved=False,session=None)

    linked_save_started=False
    revision_save_started=False
    revision_save_complete=False
    if _revision or _next:result['parent_session_id']=defaults['id']

    def field(key, default=None, *, choices=None, integer=None, number=False, optional=False, hint=''):
        while True:
            raw=ask(f'{key}: {hint}'+(f' [{default}]' if default is not None else '')+' ')
            if raw.strip()==':cancel':raise Cancelled
            value=raw if raw else default
            try:
                if value is None or value=='':
                    if optional:return None
                    raise ValueError('A value is required.')
                if integer is not None:
                    value=int(value)
                    if not integer[0]<=value<=integer[1]:raise ValueError('Value is outside the allowed range.')
                elif number:
                    value=Decimal(str(value))
                    if not value.is_finite() or value<0:raise ValueError('Use a finite nonnegative number.')
                elif choices:
                    if value not in choices:raise ValueError('Choose '+', '.join(choices)+'.')
                elif not str(value).strip():raise ValueError('A value is required.')
                return value
            except (ValueError, InvalidOperation) as exc:emit(str(exc))

    def yes(key,hint):return field(key,'no',choices=('yes','no'),hint=hint)=='yes'

    try:
        emit('Project setup: :cancel or Ctrl-C cancels. No API key value is requested. Settings are written only after save consent.')
        p=deepcopy(original)
        for key in ('name','objective'):p[key]=field(key,defaults.get('goal',p[key]) if key=='objective' else p[key],hint='Project '+key)
        comp=deepcopy(p['comparison'] or {})
        for key in ('id','dataset_ref','split_ref','metric','direction','evaluation_ref','min_delta'):
            comp[key]=field('comparison_id' if key=='id' else key,comp.get(key,0 if key=='min_delta' else None),
                choices=('minimize','maximize') if key=='direction' else None,number=key=='min_delta',hint='Evaluation comparison '+key)
        p['comparison']=comp
        for key in ('os','runtime','device'):
            p['environment'][key]=field(key,p['environment'][key],choices=('windows','linux','macos','other') if key=='os' else None,hint='Execution environment')
        for key in ('max_experiments','max_run_seconds'):
            p['budget'][key]=field(key,p['budget'][key],integer=(1,2147483647),hint='Positive project budget')
        name=field('command',defaults.get('command',{}).get('name',p['commands'][0]['name'] if p['commands'] else 'train'),hint='Configured command name')
        old=next((c for c in p['commands'] if c['name']==name),dict(argv=[],cwd='.'))
        count=field('argv_count',len(old['argv']) or None,integer=(1,100),hint='Number of argv items, including executable; no shell splitting')
        argv=[field(f'argv_{i}',old['argv'][i] if i<len(old['argv']) else None,hint='One literal executable/argument; do not add shell quoting') for i in range(count)]
        command=dict(name=name,argv=argv,cwd=field('cwd',old['cwd'],hint='Project-relative working directory'))
        p['commands']=[c for c in p['commands'] if c['name']!=name]+[command]
        count=field('editable_count',len(p['editable_paths']) or None,integer=(1,30),hint='Number of editable project paths')
        p['editable_paths']=[field(f'editable_{i}',p['editable_paths'][i] if i<len(p['editable_paths']) else None,hint='Project-relative editable path') for i in range(count)]
        read_defaults=list(defaults['sources']) if defaults else [path for path in p['editable_paths'] if research.safe_path(root,path).is_file()]
        count=field('read_count',len(read_defaults) or None,integer=(1,30),hint='Number of exact source files sent to LLM')
        reads=[field(f'read_{i}',read_defaults[i] if i<len(read_defaults) else None,hint='Exact project-relative source file') for i in range(count)]
        previous_profile=defaults.get('profile',{})
        provider=field('provider',previous_profile.get('provider','api'),choices=('api','codex'),hint='api connects directly; codex uses the installed Codex authenticated service')
        # Backend-specific keys must not cross over when changing providers.
        profile={key:previous_profile[key] for key in ('timeout_seconds','max_response_bytes') if key in previous_profile}
        if provider=='codex':
            profile.update(provider='codex',command=field('codex_command',previous_profile.get('command','codex'),hint='Trusted installed executable name or path, without arguments'),
                model=field('model',previous_profile.get('model'),hint='Codex model'))
        else:
            if previous_profile.get('provider','api')=='api' and 'max_output_tokens' in previous_profile:
                profile['max_output_tokens']=previous_profile['max_output_tokens']
            profile.update({key:field(key,previous_profile.get(key,'ZAR_API_KEY' if key=='api_key_env' else None),hint='Environment variable NAME, never the secret value' if key=='api_key_env' else 'API '+key) for key in ('base_url','model','api_key_env')})
        profile=validate_profile(profile)
        metric_default=defaults.get('metric_file','metric.json')
        if _next:
            from pathlib import PurePosixPath
            old_metric=PurePosixPath(metric_default)
            metric_default=str(old_metric.with_name(old_metric.stem+'-'+uuid4().hex[:12]+old_metric.suffix))
            emit('Working files are retained, including discarded changes. Review command argv and ensure it writes the new metric path; no file or argument is automatically restored or rewritten.')
        metric_file=field('metric_file',metric_default,hint='New project-relative output JSON file')
        metric_key=field('metric_key',defaults.get('metric_key',comp['metric']),hint='Top-level numeric JSON metric key')
        scope=field('scope',defaults.get('run_context',{}).get('scope','full'),choices=('full','proxy'),hint='Evaluation scope')
        seed=field('seed',defaults.get('run_context',{}).get('seed'),optional=True,integer=(-2147483648,2147483647),hint='Optional integer seed')
        budget_ref=field('budget_ref',defaults.get('run_context',{}).get('budget_ref','local-session'),hint='Budget protocol reference')
        mode=field('experiment_mode',defaults.get('experiment_mode') if _revision and defaults.get('experiment_mode') else ('candidate' if p['selected_experiment_id'] else 'baseline'),choices=('baseline','candidate'),hint='baseline executes original source without changes; candidate needs a selected kept baseline')
        max_calls=field('max_calls',defaults.get('max_calls',9),integer=(1,100),hint='LLM call limit; first plan needs 5 calls')
        seconds=field('session_seconds',defaults.get('session_seconds',1800),integer=(1,86400),hint='Session wall-clock budget seconds')
        cli.enforce(cli.validate_document(p,'project'))
        research.require(len(p['objective'].strip())<=10000,'Goal must be 1..10000 characters.')
        research.require(len(metric_key)<=200,'Metric key must be at most 200 characters.')
        research.require(not cli.readiness_missing(p),'Project settings are incomplete.')
        if existing and original['comparison'] and comp['id']==original['comparison']['id'] and comp!=original['comparison']:
            raise research.ResearchError('Changed comparison fields require a new comparison ID.')
        research.require(research.safe_path(root,command['cwd']).is_dir(),'Command cwd is not a directory.')
        sources=research.snapshot(root,list(dict.fromkeys(reads)))
        research.require(all(v['content'] is not None for v in sources.values()),'Read files must exist.')
        metric=research.safe_path(root,metric_file)
        research.require(metric.parent.is_dir() and not metric.exists(),'Metric destination must be new with an existing parent.')
        research.require(metric_file not in sources,'Metric output cannot be an input.')
        for path in p['editable_paths']:research.safe_path(root,path)
        if existing:
            with project_lock(store):
                snap=cli.load_records(root,p)
                cli.enforce(cli.inspect_project(root,p,snapshot=snap))
                research.require(not any(e['execution']['status'] in ('running','unknown') for e in snap.records['experiment'].values()),'Resolve running/unknown experiments before starting.')
        mode,baseline=research.experiment_target(p,snap.records if existing else {'experiment':{}},dict(scope=scope,seed=seed,budget_ref=budget_ref),mode)
        emit(dumps(dict(experiment_mode=mode,baseline_id=baseline,project=p,profile=profile,read_paths=reads,metric_file=metric_file,metric_key=metric_key,
            scope=scope,seed=seed,budget_ref=budget_ref,max_calls=max_calls,session_seconds=seconds)))
        if not yes('save','Save these project settings and create a local session?'):
            result['cancelled']=True;return result
        research.require(research.snapshot(root,list(sources))==sources,'Source inputs changed during setup; start again.')
        research.require(metric.parent.is_dir() and not metric.exists(),'Metric destination changed during setup.')
        if not existing:
            research.require(not store.exists() and not store.is_symlink(),'Project appeared during setup; start again.')
            initialized,_=cli.initialize(root)
            research.require(initialized['initialized'],'Project appeared during setup; start again.')
            # Keep the canonical initializer identity, never invent a parallel format.
            for key in ('id','created_at','updated_at','revision'):p[key]=initialized['project'][key]
            original_hash=research.digest(initialized['project'])
            records_hash=research.records_identity(root)
        with project_lock(store):
            if _next:
                current=research.load(root,defaults['id'])
                research.require(research.digest(current)==_next['context']['parent_hash'],'Parent session changed during next setup; start again.')
            if _revision:
                from .revision import eligible
                current=research.load(root,defaults['id']);eligible(current)
                research.require(research.digest(current)==_revision['context']['parent_hash'],'Parent session changed during revision; start again.')
            research.require(research.digest(research.get_project(root))==original_hash,'Project settings changed during setup; start again.')
            research.require(research.records_identity(root)==records_hash,'Research records changed during setup; start again.')
            cli.enforce(cli.inspect_project(root,p,snapshot=cli.load_records(root,p)))
            p['revision']+=1;p['updated_at']=cli.now()
            cli.enforce(cli.validate_document(p,'project'))
            if _revision:
                revision_save_started=True
                current['state']='rejected';current['approval_token']=None
                current['error']='revision_save_started'
                research.save(root,current)
            linked_save_started=bool(_next)
            atomic_write(store/'project.json',dumps(p))
            result['saved']=True
            if _revision or _next:
                result['session']=research._start_locked(root,profile=profile,goal=p['objective'],read_paths=reads,command=name,
                    metric_file=metric_file,metric_key=metric_key,max_calls=max_calls,session_seconds=seconds,
                    scope=scope,seed=seed,budget_ref=budget_ref,mode=mode,revision_context=_revision['context'] if _revision else None,next_context=_next['context'] if _next else defaults.get('next_context') if _revision else None)
            if _revision:
                current['superseded_by']=result['session']['id'];current['error']=None;research.save(root,current)
                revision_save_complete=True
        result['saved']=True
        try:
            if not (_revision or _next):result['session']=research.start(root,profile=profile,goal=p['objective'],read_paths=reads,command=name,
                metric_file=metric_file,metric_key=metric_key,max_calls=max_calls,session_seconds=seconds,
                scope=scope,seed=seed,budget_ref=budget_ref,mode=mode)
            emit(dumps(result['session']['transmission']))
            destination='the installed Codex authenticated service' if provider=='codex' else 'the API'
            if yes('send',f'Send this scope to {destination} now? This may incur charges. Stops before execution approval.'):
                result['session']=research.advance(root,result['session']['id'],send=True)
        except (ValueError, OSError, cli.Failure) as exc:
            result['error']=str(exc)
            if result['session'] is not None:
                try:result['session']=research.status(root,result['session']['id'])
                except (ValueError, OSError, cli.Failure):pass
        return result
    except (ValueError,OSError,cli.Failure) as exc:
        if linked_save_started:
            result['error']='Next session save incomplete; inspect project settings and local sessions before retrying. '+str(exc)
            return result
        if not revision_save_started:raise
        result['error']='Revision save incomplete; inspect parent status and project settings before retrying. '+str(exc)
        return result
    except (Cancelled, EOFError, KeyboardInterrupt):
        if linked_save_started and result['session'] is None:
            result['error']='Next session save interrupted; inspect project settings and local sessions before retrying.'
        if revision_save_started and not revision_save_complete:
            result['error']='Revision save interrupted; inspect parent status and project settings before retrying.'
        result['cancelled']=True
        return result
