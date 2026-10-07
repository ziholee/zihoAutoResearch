"""Local research record CLI. Stored commands are data and are never executed."""
import argparse
from datetime import datetime, timezone
from importlib.resources import files
import os
import re
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from .codec import loads, dumps
from .comparisons import compare, prepare_decision
from .experiments import prepare_create, validate_update, prepare_correction, superseded_ids, budget_used
from .git_tracking import snapshot, GitStateError
from .storage import atomic_write, project_lock
from .validation import ID, validate_document, inspect_project, readiness_missing
from .records import RecordSnapshot, load_records
from .reviews import prepare_add as prepare_review
from .submissions import prepare_add as prepare_submission
from .context import build_context, ContextError
from .evidence import read_evidence, EvidenceError


class Failure(Exception):
    def __init__(self, exit_code, diagnostics):
        self.exit_code = exit_code
        self.diagnostics = diagnostics


def diagnostic(code, path, message, severity='error'):
    return dict(severity=severity, code=code, path=str(path), message=message)


def reject(code, path, message, exit_code=3):
    raise Failure(exit_code, [diagnostic(code, path, message)])


def enforce(diagnostics):
    errors = [d for d in diagnostics if d['severity'] == 'error']
    if errors:
        codes = {d['code'] for d in errors}
        exit_code = 4 if 'io' in codes else 2 if codes & {'json', 'schema'} else 3
        raise Failure(exit_code, diagnostics)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def read_document(path):
    try:
        return loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        reject('json', path, str(exc), 2)


def safe_layout(store):
    if store.is_symlink():
        reject('conflict', store, 'Metadata directory must not be a symbolic link.')
    if not store.is_dir():
        reject('io', store, 'Project is not initialized. Run zar init.', 4)
    for name in ('project.json', 'program.md', 'reviews', 'experiments', 'submissions', 'reports'):
        path = store / name
        if path.is_symlink():
            reject('conflict', path, 'Metadata paths must not be symbolic links.')
        valid = path.is_file() if name.endswith(('.json', '.md')) else path.is_dir()
        if not valid:
            reject('conflict', path, 'Partial initialization: required file or directory missing.')


def initialize(root):
    if not root.is_dir():
        reject('io', root, 'Project root must already exist.', 4)
    store = root / '.autoresearch'
    # Separate init lock prevents two initializers replacing an empty destination.
    lock = root / '.autoresearch.init.lock'
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    temporary = None
    try:
        if store.exists() or store.is_symlink():
            safe_layout(store)
            with project_lock(store):
                project = read_document(store / 'project.json')
                enforce(validate_document(project, 'project'))
            return {'initialized': False, 'project': project}, []
        stamp = now()
        project = dict(schema_version=1, id='project-' + str(uuid4()), revision=1,
                       created_at=stamp, updated_at=stamp, name=None, objective=None,
                       comparison=None, environment=dict(os=None, runtime=None, device=None),
                       commands=[], budget=dict(max_experiments=None, max_run_seconds=None),
                       editable_paths=[], selected_experiment_id=None, next_action=None)
        staging = root / ('.autoresearch-init-' + str(uuid4()))
        staging.mkdir(mode=0o777)  # OS applies the user's umask, as for normal directories.
        temporary = staging
        for name in ('reviews', 'experiments', 'submissions', 'reports'):
            (temporary / name).mkdir()
        (temporary / 'project.json').write_text(dumps(project), encoding='utf-8')
        (temporary / 'program.md').write_text(files('zar').joinpath('program.md').read_text(encoding='utf-8'), encoding='utf-8')
        if store.exists() or store.is_symlink():
            reject('conflict', store, 'Initialization destination appeared concurrently.')
        temporary.rename(store)
        temporary = None
        return {'initialized': True, 'project': project}, []
    finally:
        if temporary is not None:
            shutil.rmtree(temporary)
        lock.unlink()


def state(root, project, snapshot):
    experiments = list(snapshot.records['experiment'].values())
    superseded = superseded_ids(experiments)
    latest = max(experiments, key=lambda e: (datetime.fromisoformat(e['created_at'].replace('Z', '+00:00')), e['id']), default=None)
    missing = readiness_missing(project)
    return dict(project_id=project['id'], revision=project['revision'], ready=not missing,
                missing=missing, budget_used=budget_used(experiments),
                superseded_experiment_ids=sorted(superseded), selected_experiment_id=project['selected_experiment_id'],
                last_experiment_id=latest['id'] if latest else None,
                unfinished=[dict(id=e['id'], status=e['execution']['status']) for e in experiments
                            if e['execution']['status'] in ('planned', 'running', 'unknown')],
                unselected_keep_ids=[e['id'] for e in experiments if e['id'] not in superseded and e['decision'] and
                                     e['decision']['status'] == 'keep' and e['id'] != project['selected_experiment_id']],
                next_action=project['next_action'])


def save_experiment(args, root, project, snapshot):
    # Caller holds the project lock throughout validation and the single-file write.
    store = root / '.autoresearch'
    enforce(inspect_project(root, project, snapshot=snapshot))
    body = read_document(Path(args.file))
    records = list(snapshot.records['experiment'].values())
    superseded = superseded_ids(records)
    if args.action == 'create':
        missing = readiness_missing(project)
        if missing:
            reject('not_ready', 'project.json', 'Required settings: ' + ', '.join(missing))
        count = budget_used(records)
        if count >= project['budget']['max_experiments']:
            reject('conflict', 'budget.max_experiments', 'Experiment budget has been reached.')
        candidate, errors = prepare_create(body, project, now())
        enforce(errors)
        if args.git_head:
            git_state = inspect_git(root)
            if not git_state['code_clean']:
                reject('conflict', 'git', 'Commit or set aside code/config changes before --git-head. Run zar git status.')
            candidate['code_ref'] = git_state['code_ref']
        path = store / 'experiments' / (candidate['id'] + '.json')
        if path.exists() or path.is_symlink():
            reject('conflict', path, 'Experiment ID already exists.')
    else:
        if not ID.fullmatch(args.id):
            reject('arguments', 'id', 'Invalid experiment ID.', 2)
        path = store / 'experiments' / (args.id + '.json')
        if not path.is_file():
            reject('conflict', path, 'Experiment does not exist.')
        current = snapshot.records['experiment'][args.id]
        if current['id'] in superseded:
            reject('conflict', path, 'This experiment has been superseded; use the active correction.')
        if args.action == 'correct':
            if project['selected_experiment_id'] == current['id']:
                reject('conflict', path, 'Deselect this experiment before correcting its result.')
            candidate, errors = prepare_correction(current, body, now())
            enforce(errors)
            path = store / 'experiments' / (candidate['id'] + '.json')
            if path.exists() or path.is_symlink():
                reject('conflict', path, 'Correction requires an unused experiment ID.')
        elif args.action == 'decide':
            candidate, errors = prepare_decision(current, body, {d['id']:d for d in records}, now())
            enforce(errors)
        else:
            enforce(validate_update(current, body))
            candidate = body
            candidate['revision'] += 1
            candidate['updated_at'] = now()
            enforce(validate_document(candidate, 'experiment'))
    diagnostics = inspect_project(root, project, experiment=candidate, snapshot=snapshot)
    enforce(diagnostics)
    atomic_write(path, dumps(candidate))
    return {'experiment': candidate}, diagnostics


def save_observation(args, root, project, snapshot):
    # The caller holds the same cooperative lock as every record mutation.
    enforce(inspect_project(root, project, snapshot=snapshot))
    kind = args.command
    prepare = prepare_review if kind == 'review' else prepare_submission
    candidate, errors = prepare(read_document(Path(args.file)), now())
    enforce(errors)
    record_id = candidate['id']
    path = root / '.autoresearch' / (kind + 's') / (record_id + '.json')
    if (path.exists() or path.is_symlink() or record_id == project['id']
            or any(record_id in group for group in snapshot.records.values())):
        reject('conflict', path, 'Record requires an unused record ID.')
    # Overlay copied maps so validation sees all links, correction branches and
    # evidence before a single append-only write; original documents stay intact.
    records = {kind: dict(group) for kind, group in snapshot.records.items()}
    records[kind][record_id] = candidate
    paths = dict(snapshot.paths)
    paths[record_id] = path
    proposed = RecordSnapshot(records, paths, list(snapshot.diagnostics))
    diagnostics = inspect_project(root, project, snapshot=proposed)
    enforce(diagnostics)
    atomic_write(path, dumps(candidate))
    return {kind: candidate}, diagnostics


def inspect_git(root):
    try:
        return snapshot(root)
    except GitStateError as exc:
        reject('conflict', 'git', str(exc))


def execute(args):
    root = Path(args.project).expanduser().resolve()
    if args.command == 'init':
        return initialize(root)
    if args.command == 'git':
        return inspect_git(root), []
    store = root / '.autoresearch'
    safe_layout(store)
    with project_lock(store):
        project = read_document(store / 'project.json')
        enforce(validate_document(project, 'project'))
        snapshot = load_records(root, project)
        if args.command in ('context', 'evidence'):
            diagnostics = inspect_project(root, project, snapshot=snapshot, check_files=False)
            enforce(diagnostics)
            if args.command == 'context':
                return build_context(project, snapshot.records, diagnostics, experiment=args.experiment,
                                     limit=args.limit, offset=args.offset, max_bytes=args.max_bytes,
                                     snapshot=args.snapshot)
            if not ID.fullmatch(args.id): reject('arguments', 'id', 'Invalid record ID.', 2)
            document = snapshot.records[args.kind].get(args.id)
            if document is None: reject('conflict', args.id, 'Record does not exist.')
            if args.revision is not None and args.revision != document['revision']:
                reject('conflict', args.id, 'Record revision changed; refresh the evidence handle.')
            if args.sha256 is not None and not re.fullmatch(r'[0-9a-f]{64}', args.sha256):
                reject('arguments', 'sha256', 'Expected a lowercase SHA256 hash.', 2)
            data, evidence_diagnostics = read_evidence(root, document, args.pointer,
                start_line=args.start_line, max_lines=args.max_lines, max_bytes=args.max_bytes)
            if args.sha256 is not None and args.sha256 != data['source']['actual_sha256']:
                reject('evidence_changed', args.pointer, 'Evidence differs from the requested page identity; no excerpt returned.')
            data.update(view='evidence_page', record_kind=args.kind, record_id=args.id,
                        record_revision=document['revision'])
            return data, diagnostics + evidence_diagnostics
        if args.command == 'experiment' and args.action == 'compare':
            diagnostics = inspect_project(root, project, snapshot=snapshot)
            enforce(diagnostics)
            records = snapshot.records['experiment']
            for id in (args.base_id, args.candidate_id):
                if not ID.fullmatch(id): reject('arguments', 'id', 'Invalid experiment ID.', 2)
                if id not in records: reject('conflict', id, 'Experiment does not exist.')
            return compare(records[args.base_id], records[args.candidate_id], records), diagnostics
        if args.command == 'experiment':
            return save_experiment(args, root, project, snapshot)
        if args.command in ('review', 'submission'):
            return save_observation(args, root, project, snapshot)
        if args.command == 'project':
            candidate = read_document(Path(args.file))
            enforce(validate_document(candidate, 'project'))
            for field in ('id', 'created_at', 'revision'):
                if candidate[field] != project[field]:
                    reject('conflict', field, f'{field} must match the current project document.')
            if (candidate['comparison'] is not None and project['comparison'] is not None
                    and candidate['comparison']['id'] == project['comparison']['id']
                    and candidate['comparison'] != project['comparison']):
                reject('conflict', 'comparison', 'Changed comparison fields require a new comparison ID.')
            diagnostics = inspect_project(root, candidate, snapshot=snapshot)
            enforce(diagnostics)
            candidate['revision'] += 1
            candidate['updated_at'] = now()
            enforce(validate_document(candidate, 'project'))
            atomic_write(store / 'project.json', dumps(candidate))
            return {'project': candidate}, diagnostics
        diagnostics = inspect_project(root, project, snapshot=snapshot)
        enforce(diagnostics)
        data = state(root, project, snapshot)
        if args.command == 'check' and data['missing']:
            diagnostics.extend(diagnostic('not_ready', field, 'Required setting is missing.') for field in data['missing'])
            raise Failure(3, diagnostics)
        return data, diagnostics


class Parser(argparse.ArgumentParser):
    def error(self, message):
        reject('arguments', '', message, 2)


def parse(arguments):
    globals_parser = Parser(add_help=False, allow_abbrev=False)
    globals_parser.add_argument('--json', action='store_true')
    globals_parser.add_argument('--project', default='.')
    global_args, remaining = globals_parser.parse_known_args(arguments)
    parser = Parser(prog='zar', description=__doc__, allow_abbrev=False)
    parser.add_argument('--json', action='store_true', help='emit a single JSON result')
    parser.add_argument('--project', help='project root (default: current directory)')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('init', 'status', 'check'):
        commands.add_parser(name)
    context = commands.add_parser('context', help='bounded metadata context; evidence files are not checked')
    context.add_argument('--experiment')
    context.add_argument('--limit', type=int, default=5)
    context.add_argument('--offset', type=int, default=0)
    context.add_argument('--max-bytes', type=int, default=16384)
    context.add_argument('--snapshot', help='reject pagination if canonical records changed')
    evidence = commands.add_parser('evidence')
    evidence_actions = evidence.add_subparsers(dest='action', required=True, parser_class=Parser)
    reader = evidence_actions.add_parser('read')
    reader.add_argument('--kind', choices=('experiment','review','submission'), required=True)
    reader.add_argument('--id', required=True)
    reader.add_argument('--pointer', required=True)
    reader.add_argument('--revision', type=int, help='require the recorded handle revision')
    reader.add_argument('--sha256', help='require a prior page content hash, including unhashed sources')
    reader.add_argument('--start-line', type=int, default=1)
    reader.add_argument('--max-lines', type=int, default=80)
    reader.add_argument('--max-bytes', type=int, default=16384)
    project = commands.add_parser('project')
    actions = project.add_subparsers(dest='action', required=True, parser_class=Parser)
    setter = actions.add_parser('set')
    setter.add_argument('--file', required=True)
    for kind in ('review', 'submission'):
        observation = commands.add_parser(kind)
        observation_actions = observation.add_subparsers(dest='action', required=True, parser_class=Parser)
        observation_add = observation_actions.add_parser('add')
        observation_add.add_argument('--file', required=True)
    experiment = commands.add_parser('experiment')
    experiment_actions = experiment.add_subparsers(dest='action', required=True, parser_class=Parser)
    create = experiment_actions.add_parser('create')
    create.add_argument('--file', required=True)
    create.add_argument('--git-head', action='store_true', help='bind code_ref to clean Git HEAD')
    update = experiment_actions.add_parser('update')
    update.add_argument('id')
    update.add_argument('--file', required=True)
    correct = experiment_actions.add_parser('correct')
    correct.add_argument('id')
    correct.add_argument('--file', required=True)
    comparer = experiment_actions.add_parser('compare')
    comparer.add_argument('base_id')
    comparer.add_argument('candidate_id')
    decide = experiment_actions.add_parser('decide')
    decide.add_argument('id')
    decide.add_argument('--file', required=True)
    git_parser = commands.add_parser('git')
    git_actions = git_parser.add_subparsers(dest='action', required=True, parser_class=Parser)
    git_actions.add_parser('status')
    args = parser.parse_args(remaining)
    args.json, args.project = global_args.json, global_args.project
    return args


def emit_text(text):
    """Keep human output usable when a terminal cannot encode recorded text."""
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    print(text.encode(encoding, errors='backslashreplace').decode(encoding))


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    json_mode = '--json' in arguments
    code, data, diagnostics = 0, None, []
    try:
        if json_mode and ('--help' in arguments or '-h' in arguments):
            data = {'commands': ['init', 'project set --file <json>', 'status', 'check',
                                 'review add --file <json>', 'submission add --file <json>',
                                 'experiment create --file <json> [--git-head]', 'experiment update <id> --file <json>',
                                 'experiment correct <id> --file <json>', 'experiment compare <base-id> <candidate-id>',
                                 'experiment decide <id> --file <json>', 'git status',
                                 'context [--experiment <id>] [--limit <n>] [--offset <n>] [--max-bytes <n>] [--snapshot <hash>]',
                                 'evidence read --kind <kind> --id <id> --pointer <pointer> [--revision <n>] [--sha256 <hash>] [--start-line <n>] [--max-lines <n>] [--max-bytes <n>]'],
                    'options': ['--project <root>', '--json'],
                    'description': __doc__}
        else:
            args = parse(arguments)
            data, diagnostics = execute(args)
    except Failure as exc:
        code, diagnostics = exc.exit_code, exc.diagnostics
    except (ContextError, EvidenceError) as exc:
        code = exc.exit_code
        diagnostics = [diagnostic(exc.code, '', exc.message)]
    except OSError as exc:
        code = 4
        diagnostics = [diagnostic('io', exc.filename or '', str(exc))]
    if json_mode:
        print(dumps(dict(ok=code == 0, data=data, diagnostics=diagnostics), ensure_ascii=True))
    else:
        if data is not None:
            if data.get('view') in ('research_context', 'evidence_page'):
                emit_text(dumps(data).rstrip('\n'))
            elif 'comparable' in data:
                emit_text('Comparable: ' + ('yes' if data['comparable'] else 'no'))
                emit_text('Reasons: ' + (', '.join(data['reasons']) or 'none'))
                emit_text('Improvement: ' + str(data['improvement']))
                emit_text('Meets min delta: ' + str(data['meets_min_delta']))
                for label, summary in data['repeats'].items():
                    emit_text(label + ' repetitions: ' + dumps(summary).strip())
            elif 'repository' in data:
                emit_text('Repository: ' + data['repository'])
                emit_text('HEAD: ' + data['head'])
                emit_text('Code clean: ' + ('yes' if data['code_clean'] else 'no'))
                for category in ('code_changes', 'record_changes'):
                    emit_text(category + ':')
                    for change in data[category]:
                        emit_text(change['status'] + ' ' + change['path'])
            elif 'submission' in data:
                submission = data['submission']
                emit_text(f"Submission: {submission['id']} (revision {submission['revision']})")
                emit_text('Experiment: ' + submission['experiment_id'])
                emit_text('Score: ' + str(submission['score']))
            elif 'review' in data:
                review = data['review']
                emit_text(f"Review: {review['id']} (revision {review['revision']})")
                emit_text('Findings: ' + str(len(review['items'])))
            elif 'experiment' in data:
                experiment = data['experiment']
                emit_text(f"Experiment: {experiment['id']} (revision {experiment['revision']})")
                emit_text('Execution: ' + experiment['execution']['status'])
            elif 'project' in data:
                project = data['project']
                emit_text(f"Project: {project['id']} (revision {project['revision']})")
                if 'initialized' in data:
                    emit_text('Initialized.' if data['initialized'] else 'Already initialized; preserved existing files.')
            else:
                emit_text(f"Project: {data['project_id']} (revision {data['revision']})")
                emit_text('Ready: ' + ('yes' if data['ready'] else 'no'))
                emit_text('Missing: ' + (', '.join(data['missing']) or 'none'))
                emit_text('Selected experiment: ' + (data['selected_experiment_id'] or 'none'))
                emit_text('Last experiment: ' + (data['last_experiment_id'] or 'none'))
                emit_text('Unfinished: ' + (', '.join(f"{e['id']} ({e['status']})" for e in data['unfinished']) or 'none'))
                emit_text('Unselected keep: ' + (', '.join(data['unselected_keep_ids']) or 'none'))
                emit_text('Budget used: ' + str(data['budget_used']))
                emit_text('Superseded experiments: ' + (', '.join(data['superseded_experiment_ids']) or 'none'))
                emit_text('Next action: ' + (data['next_action'] or 'unset'))
        for item in diagnostics:
            emit_text(f"{item['severity']}: {item['path']}: {item['message']}")
    return code
