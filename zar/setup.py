"""Consent-gated questionnaire for one configured API research session."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from . import cli, research
from .codec import dumps
from .llm import validate_profile
from .storage import atomic_write, project_lock


class Cancelled(Exception):
    pass


def setup(root, *, ask, emit):
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
    else:
        stamp=cli.now()
        original=dict(schema_version=1,id='project-'+str(uuid4()),revision=1,created_at=stamp,updated_at=stamp,
            name=None,objective=None,comparison=None,environment=dict(os=None,runtime=None,device=None),
            commands=[],budget=dict(max_experiments=None,max_run_seconds=None),editable_paths=[],
            selected_experiment_id=None,next_action=None)
    result=dict(view='research_setup',cancelled=False,saved=False,session=None)

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
        for key in ('name','objective'):p[key]=field(key,p[key],hint='Project '+key)
        comp=deepcopy(p['comparison'] or {})
        for key in ('id','dataset_ref','split_ref','metric','direction','evaluation_ref','min_delta'):
            comp[key]=field('comparison_id' if key=='id' else key,comp.get(key,0 if key=='min_delta' else None),
                choices=('minimize','maximize') if key=='direction' else None,number=key=='min_delta',hint='Evaluation comparison '+key)
        p['comparison']=comp
        for key in ('os','runtime','device'):
            p['environment'][key]=field(key,p['environment'][key],choices=('windows','linux','macos','other') if key=='os' else None,hint='Execution environment')
        for key in ('max_experiments','max_run_seconds'):
            p['budget'][key]=field(key,p['budget'][key],integer=(1,2147483647),hint='Positive project budget')
        name=field('command',p['commands'][0]['name'] if p['commands'] else 'train',hint='Configured command name')
        old=next((c for c in p['commands'] if c['name']==name),dict(argv=[],cwd='.'))
        count=field('argv_count',len(old['argv']) or None,integer=(1,100),hint='Number of argv items, including executable; no shell splitting')
        argv=[field(f'argv_{i}',old['argv'][i] if i<len(old['argv']) else None,hint='One literal executable/argument; do not add shell quoting') for i in range(count)]
        command=dict(name=name,argv=argv,cwd=field('cwd',old['cwd'],hint='Project-relative working directory'))
        p['commands']=[c for c in p['commands'] if c['name']!=name]+[command]
        count=field('editable_count',len(p['editable_paths']) or None,integer=(1,30),hint='Number of editable project paths')
        p['editable_paths']=[field(f'editable_{i}',p['editable_paths'][i] if i<len(p['editable_paths']) else None,hint='Project-relative editable path') for i in range(count)]
        defaults=[path for path in p['editable_paths'] if research.safe_path(root,path).is_file()]
        count=field('read_count',len(defaults) or None,integer=(1,30),hint='Number of exact source files sent to LLM')
        reads=[field(f'read_{i}',defaults[i] if i<len(defaults) else None,hint='Exact project-relative source file') for i in range(count)]
        profile=validate_profile({key:field(key,'ZAR_API_KEY' if key=='api_key_env' else None,hint='Environment variable NAME, never the secret value' if key=='api_key_env' else 'API '+key) for key in ('base_url','model','api_key_env')})
        metric_file=field('metric_file','metric.json',hint='New project-relative output JSON file')
        metric_key=field('metric_key',comp['metric'],hint='Top-level numeric JSON metric key')
        scope=field('scope','full',choices=('full','proxy'),hint='Evaluation scope')
        seed=field('seed',optional=True,integer=(-2147483648,2147483647),hint='Optional integer seed')
        budget_ref=field('budget_ref','local-session',hint='Budget protocol reference')
        max_calls=field('max_calls',9,integer=(1,100),hint='API call limit; first plan needs 5 calls')
        seconds=field('session_seconds',1800,integer=(1,86400),hint='Session wall-clock budget seconds')
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
        emit(dumps(dict(project=p,profile=profile,read_paths=reads,metric_file=metric_file,metric_key=metric_key,
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
            research.require(research.digest(research.get_project(root))==original_hash,'Project settings changed during setup; start again.')
            research.require(research.records_identity(root)==records_hash,'Research records changed during setup; start again.')
            cli.enforce(cli.inspect_project(root,p,snapshot=cli.load_records(root,p)))
            p['revision']+=1;p['updated_at']=cli.now()
            cli.enforce(cli.validate_document(p,'project'))
            atomic_write(store/'project.json',dumps(p))
        result['saved']=True
        try:
            result['session']=research.start(root,profile=profile,goal=p['objective'],read_paths=reads,command=name,
                metric_file=metric_file,metric_key=metric_key,max_calls=max_calls,session_seconds=seconds,
                scope=scope,seed=seed,budget_ref=budget_ref)
            emit(dumps(result['session']['transmission']))
            if yes('send','Send this scope to the API now? This may incur charges. Stops before execution approval.'):
                result['session']=research.advance(root,result['session']['id'],send=True)
        except (ValueError, OSError, cli.Failure) as exc:
            result['error']=str(exc)
            if result['session'] is not None:
                try:result['session']=research.status(root,result['session']['id'])
                except (ValueError, OSError, cli.Failure):pass
        return result
    except (Cancelled, EOFError, KeyboardInterrupt):
        result['cancelled']=True
        return result
