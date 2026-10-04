"""Project-only CLI. Stored commands are data and are never executed."""
import argparse
from datetime import datetime, timezone
from importlib.resources import files
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4

from .codec import loads, dumps
from .storage import atomic_write, project_lock
from .validation import validate_document, inspect_project, readiness_missing


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


def state(root, project):
    experiments = [read_document(p) for p in sorted((root / '.autoresearch/experiments').glob('*.json'))]
    latest = max(experiments, key=lambda e: (datetime.fromisoformat(e['created_at'].replace('Z', '+00:00')), e['id']), default=None)
    missing = readiness_missing(project)
    return dict(project_id=project['id'], revision=project['revision'], ready=not missing,
                missing=missing, selected_experiment_id=project['selected_experiment_id'],
                last_experiment_id=latest['id'] if latest else None,
                unfinished=[dict(id=e['id'], status=e['execution']['status']) for e in experiments
                            if e['execution']['status'] in ('planned', 'running', 'unknown')],
                unselected_keep_ids=[e['id'] for e in experiments if e['decision'] and
                                     e['decision']['status'] == 'keep' and e['id'] != project['selected_experiment_id']],
                next_action=project['next_action'])


def execute(args):
    root = Path(args.project).expanduser().resolve()
    if args.command == 'init':
        return initialize(root)
    store = root / '.autoresearch'
    safe_layout(store)
    with project_lock(store):
        project = read_document(store / 'project.json')
        enforce(validate_document(project, 'project'))
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
            diagnostics = inspect_project(root, candidate)
            enforce(diagnostics)
            candidate['revision'] += 1
            candidate['updated_at'] = now()
            enforce(validate_document(candidate, 'project'))
            atomic_write(store / 'project.json', dumps(candidate))
            return {'project': candidate}, diagnostics
        diagnostics = inspect_project(root, project)
        enforce(diagnostics)
        data = state(root, project)
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
    project = commands.add_parser('project')
    actions = project.add_subparsers(dest='action', required=True, parser_class=Parser)
    setter = actions.add_parser('set')
    setter.add_argument('--file', required=True)
    args = parser.parse_args(remaining)
    args.json, args.project = global_args.json, global_args.project
    return args


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    json_mode = '--json' in arguments
    code, data, diagnostics = 0, None, []
    try:
        if json_mode and ('--help' in arguments or '-h' in arguments):
            data = {'commands': ['init', 'project set --file <json>', 'status', 'check'],
                    'options': ['--project <root>', '--json'],
                    'description': __doc__}
        else:
            args = parse(arguments)
            data, diagnostics = execute(args)
    except Failure as exc:
        code, diagnostics = exc.exit_code, exc.diagnostics
    except OSError as exc:
        code = 4
        diagnostics = [diagnostic('io', exc.filename or '', str(exc))]
    if json_mode:
        print(dumps(dict(ok=code == 0, data=data, diagnostics=diagnostics), ensure_ascii=True))
    else:
        if data is not None:
            if 'project' in data:
                project = data['project']
                print(f"Project: {project['id']} (revision {project['revision']})")
                if 'initialized' in data:
                    print('Initialized.' if data['initialized'] else 'Already initialized; preserved existing files.')
            else:
                print(f"Project: {data['project_id']} (revision {data['revision']})")
                print('Ready: ' + ('yes' if data['ready'] else 'no'))
                print('Missing: ' + (', '.join(data['missing']) or 'none'))
                print('Selected experiment: ' + (data['selected_experiment_id'] or 'none'))
                print('Last experiment: ' + (data['last_experiment_id'] or 'none'))
                print('Unfinished: ' + (', '.join(f"{e['id']} ({e['status']})" for e in data['unfinished']) or 'none'))
                print('Unselected keep: ' + (', '.join(data['unselected_keep_ids']) or 'none'))
                print('Next action: ' + (data['next_action'] or 'unset'))
        for item in diagnostics:
            print(f"{item['severity']}: {item['path']}: {item['message']}")
    return code
