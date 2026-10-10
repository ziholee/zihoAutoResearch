"""Contract validation. Checks recorded structure and evidence, never ML correctness."""
from datetime import datetime
from decimal import Decimal
import hashlib
import math
from pathlib import Path
import re

META = 'schema_version id revision created_at updated_at'
ID = re.compile(r'[a-z0-9-]{1,64}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)\Z')


def diagnostic(code, path, message, severity='error'):
    return dict(severity=severity, code=code, path=str(path), message=message)


def readiness_missing(project):
    missing = [k for k in ('objective', 'comparison', 'commands', 'editable_paths') if not project.get(k)]
    if not (project.get('environment') or {}).get('runtime'):
        missing.append('environment.runtime')
    for k in ('max_experiments', 'max_run_seconds'):
        if not (project.get('budget') or {}).get(k):
            missing.append('budget.' + k)
    return missing


class Validator:
    def __init__(self):
        self.errors = []

    def error(self, p, message, code='schema'):
        self.errors.append(diagnostic(code, p, message))

    def obj(self, value, fields, path):
        if not isinstance(value, dict):
            self.error(path, 'Expected object')
            return False
        expected = set(fields.split())
        for key in sorted(expected - value.keys()):
            self.error(path + '.' + key, 'Required field is missing')
        for key in sorted(value.keys() - expected):
            self.error(path + '.' + key, 'Unknown field')
        return expected <= value.keys()

    def scalar(self, value, kind, path, nullable=False):
        if value is None and nullable:
            return
        valid = False
        if kind == 'str':
            valid = isinstance(value, str) and bool(value.strip())
        elif kind == 'int':
            valid = type(value) is int
        elif kind == 'positive':
            valid = type(value) is int and value > 0
        elif kind == 'number':
            valid = type(value) in (int, float, Decimal) and (value.is_finite() if isinstance(value, Decimal) else (True if isinstance(value, int) else math.isfinite(value)))
        elif kind in ('id', 'hash'):
            valid = isinstance(value, str) and bool((ID if kind == 'id' else HASH).fullmatch(value))
        elif kind == 'time':
            try:
                valid = isinstance(value, str) and bool(STAMP.fullmatch(value)) and datetime.fromisoformat(value.replace('Z', '+00:00')) is not None
            except ValueError:
                valid = False
        if not valid:
            self.error(path, 'Expected ' + kind + (' or null' if nullable else ''))

    def enum(self, value, choices, path, nullable=False):
        if value is None and nullable:
            return
        if not isinstance(value, str) or value not in choices.split():
            self.error(path, 'Expected one of: ' + choices)

    def array(self, value, fn, path, nonempty=False):
        if not isinstance(value, list):
            self.error(path, 'Expected array')
            return
        if nonempty and not value:
            self.error(path, 'Array must not be empty')
        for i, item in enumerate(value):
            fn(item, f'{path}[{i}]')

    def order(self, a, b, path):
        try:
            if a and b and datetime.fromisoformat(a.replace('Z', '+00:00')) > datetime.fromisoformat(b.replace('Z', '+00:00')):
                self.error(path, 'Timestamps are out of order', 'conflict')
        except (ValueError, TypeError, AttributeError):
            pass

    def evidence(self, value, path):
        if not self.obj(value, 'kind ref locator sha256', path): return
        self.enum(value['kind'], 'file url user_report fixture', path + '.kind')
        self.scalar(value['ref'], 'str', path + '.ref')
        self.scalar(value['locator'], 'str', path + '.locator', True)
        self.scalar(value['sha256'], 'hash', path + '.sha256', True)

    def environment(self, value, path):
        if not self.obj(value, 'os runtime device', path): return
        self.enum(value['os'], 'windows linux macos other', path + '.os', True)
        for k in ('runtime', 'device'): self.scalar(value[k], 'str', path + '.' + k, True)

    def comparison(self, value, path):
        if not self.obj(value, 'id dataset_ref split_ref metric direction evaluation_ref min_delta', path): return
        for k in ('id', 'dataset_ref', 'split_ref', 'metric', 'evaluation_ref'): self.scalar(value[k], 'str', path + '.' + k)
        self.enum(value['direction'], 'minimize maximize', path + '.direction')
        self.scalar(value['min_delta'], 'number', path + '.min_delta')
        if type(value['min_delta']) in (int, float, Decimal):
            try:
                if value['min_delta'] < 0: self.error(path + '.min_delta', 'Must be nonnegative')
            except ArithmeticError: pass

    def run_context(self, value, path):
        if not self.obj(value, 'scope seed budget_ref', path): return
        self.enum(value['scope'], 'proxy full', path + '.scope')
        self.scalar(value['seed'], 'int', path + '.seed', True)
        self.scalar(value['budget_ref'], 'str', path + '.budget_ref')

    def command(self, value, path):
        if not self.obj(value, 'name argv cwd', path): return
        self.enum(value['name'], 'train validate predict other', path + '.name')
        self.array(value['argv'], lambda v,p: self.scalar(v, 'str', p), path + '.argv', True)
        self.scalar(value['cwd'], 'str', path + '.cwd')

    def finding(self, value, path):
        if not self.obj(value, 'id topic applicability observation assessment evidence limitation next_action', path): return
        for k in ('id','topic','applicability','observation'): self.scalar(value[k], 'str', path + '.' + k)
        for k in ('limitation','next_action'): self.scalar(value[k], 'str', path + '.' + k, True)
        self.enum(value['assessment'], 'confirmed_issue suspected passed_in_scope unverifiable not_applicable', path + '.assessment')
        self.array(value['evidence'], self.evidence, path + '.evidence', value['assessment'] in ('confirmed_issue','passed_in_scope'))
        if value['assessment'] == 'unverifiable' and not value['limitation']: self.error(path, 'Unverifiable finding needs limitation', 'conflict')
        if value['assessment'] == 'suspected' and not value['next_action']: self.error(path, 'Suspected finding needs next_action', 'conflict')

    def decision(self, value, path):
        if not self.obj(value, 'status validity reason evidence next_action', path): return
        self.enum(value['status'], 'keep discard hold', path + '.status')
        self.enum(value['validity'], 'valid invalid not_comparable', path + '.validity')
        self.scalar(value['reason'], 'str', path + '.reason')
        self.scalar(value['next_action'], 'str', path + '.next_action', True)
        self.array(value['evidence'], self.evidence, path + '.evidence', value['status'] == 'keep')
        if value['status'] == 'keep' and value['validity'] != 'valid': self.error(path, 'Keep requires valid result', 'conflict')
        if value['status'] == 'hold' and not value['next_action']: self.error(path, 'Hold requires next_action', 'conflict')

    def history(self, value, path):
        if not self.obj(value, 'decided_at decision', path): return
        self.scalar(value['decided_at'], 'time', path + '.decided_at')
        self.decision(value['decision'], path + '.decision')

    def artifact(self, value, path):
        if not self.obj(value, 'role path sha256 code_ref config_ref evidence', path): return
        for k in ('role','path','code_ref','config_ref'): self.scalar(value[k], 'str', path + '.' + k)
        self.scalar(value['sha256'], 'hash', path + '.sha256', value['role'] != 'submission')
        self.array(value['evidence'], self.evidence, path + '.evidence', True)

    def execution(self, value, path):
        if not self.obj(value, 'status started_at finished_at exit_code score evidence artifacts note', path): return
        self.enum(value['status'], 'planned running succeeded failed interrupted unknown cancelled', path + '.status')
        for k in ('started_at','finished_at'): self.scalar(value[k], 'time', path + '.' + k, True)
        self.scalar(value['exit_code'], 'int', path + '.exit_code', True)
        self.scalar(value['score'], 'number', path + '.score', True)
        self.scalar(value['note'], 'str', path + '.note', True)
        self.array(value['evidence'], self.evidence, path + '.evidence', value['status'] == 'succeeded')
        self.array(value['artifacts'], self.artifact, path + '.artifacts')
        self.order(value['started_at'], value['finished_at'], path)
        status = value['status']
        if status in ('planned', 'cancelled') and value['started_at'] is not None: self.error(path, 'Never-run states cannot have a start time', 'conflict')
        if status in ('running', 'succeeded', 'failed', 'interrupted') and value['started_at'] is None: self.error(path, 'Observed execution requires a start time', 'conflict')
        if status == 'cancelled' and (value['exit_code'] is not None or value['score'] is not None or value['artifacts'] or not value['note']): self.error(path, 'Cancellation requires a reason and no execution results or artifacts', 'conflict')
        if status == 'unknown' and value['started_at'] is None and (not value['evidence'] or value['exit_code'] is not None or value['artifacts']): self.error(path, 'Unconfirmed start requires evidence and no exit code/artifacts', 'conflict')
        if (status in ('succeeded','failed','interrupted')) != (value['finished_at'] is not None): self.error(path, 'Terminal state requires finish time; other states prohibit it', 'conflict')
        if status == 'succeeded' and (type(value['exit_code']) is not int or value['exit_code'] != 0 or value['score'] is None): self.error(path, 'Success requires exit_code 0 and score', 'conflict')
        if status in ('failed','interrupted','unknown') and (value['score'] is not None or not value['note']): self.error(path, 'Failed/interrupted/unknown requires null score and reason', 'conflict')
        if status == 'planned' and (value['exit_code'] is not None or value['score'] is not None or value['evidence'] or value['artifacts'] or value['note'] is not None): self.error(path, 'Planned execution must have empty initial results', 'conflict')


def validate_document(doc, kind):
    if kind == 'memory':
        from .memories import validate_memory
        return validate_memory(doc)
    v = Validator()
    fields = {'project':'name objective comparison environment commands budget editable_paths selected_experiment_id next_action',
              'review':'supersedes_id code_ref data_ref items',
              'experiment':'kind hypothesis parent_id baseline_id comparison environment code_ref config_ref command review_ids execution decision decision_history',
              'submission':'supersedes_id experiment_id competition external_id artifact leaderboard metric direction score submitted_at observed_at evidence'}
    if kind not in fields: return [diagnostic('schema', '$', 'Unknown record kind')]
    # v1 compatibility: old experiment documents may omit correction (equivalent to null).
    if kind == 'experiment' and isinstance(doc, dict) and 'correction' in doc:
        fields[kind] += ' correction'
    if kind == 'experiment' and isinstance(doc, dict) and 'run_context' in doc:
        fields[kind] += ' run_context'
    if not v.obj(doc, META + ' ' + fields[kind], '$'): return v.errors
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1: v.error('$.schema_version', 'Only schema_version 1 is supported')
    v.scalar(doc['id'], 'id', '$.id')
    v.scalar(doc['revision'], 'positive', '$.revision')
    for k in ('created_at','updated_at'): v.scalar(doc[k], 'time', '$.' + k)
    v.order(doc['created_at'], doc['updated_at'], '$')
    if kind == 'project':
        for k in ('name','objective','next_action'): v.scalar(doc[k], 'str', '$.' + k, True)
        v.scalar(doc['selected_experiment_id'], 'id', '$.selected_experiment_id', True)
        if doc['comparison'] is not None: v.comparison(doc['comparison'], '$.comparison')
        v.environment(doc['environment'], '$.environment')
        v.array(doc['commands'], v.command, '$.commands')
        v.array(doc['editable_paths'], lambda x,p:v.scalar(x,'str',p), '$.editable_paths')
        if v.obj(doc['budget'], 'max_experiments max_run_seconds', '$.budget'):
            for k in ('max_experiments','max_run_seconds'): v.scalar(doc['budget'][k], 'positive', '$.budget.' + k, True)
    elif kind == 'review':
        v.scalar(doc['supersedes_id'], 'id', '$.supersedes_id', True)
        for k in ('code_ref','data_ref'): v.scalar(doc[k], 'str', '$.' + k)
        v.array(doc['items'], v.finding, '$.items', True)
    elif kind == 'experiment':
        if doc.get('run_context') is not None:
            v.run_context(doc['run_context'], '$.run_context')
        correction = doc.get('correction')
        if correction is not None and v.obj(correction, 'supersedes_id reason evidence', '$.correction'):
            v.scalar(correction['supersedes_id'], 'id', '$.correction.supersedes_id')
            v.scalar(correction['reason'], 'str', '$.correction.reason')
            v.array(correction['evidence'], v.evidence, '$.correction.evidence', True)
        v.enum(doc['kind'], 'baseline validity_fix performance confirmation', '$.kind')
        for k in ('hypothesis','code_ref','config_ref'): v.scalar(doc[k], 'str', '$.' + k)
        for k in ('parent_id','baseline_id'): v.scalar(doc[k], 'id', '$.' + k, True)
        v.comparison(doc['comparison'], '$.comparison')
        v.environment(doc['environment'], '$.environment')
        v.command(doc['command'], '$.command')
        v.array(doc['review_ids'], lambda x,p:v.scalar(x,'id',p), '$.review_ids')
        v.execution(doc['execution'], '$.execution')
        if doc['decision'] is not None: v.decision(doc['decision'], '$.decision')
        v.array(doc['decision_history'], v.history, '$.decision_history')
        if not v.errors:
            e = doc['execution']; d = doc['decision']; h = doc['decision_history']
            if (d is None and h) or (d is not None and (not h or h[-1]['decision'] != d)): v.error('$.decision_history', 'Current decision must match last history entry', 'conflict')
            if d and (e['status'] not in ('succeeded','failed','interrupted') or (d['status'] == 'keep' and e['status'] != 'succeeded')): v.error('$.decision', 'Decision conflicts with execution state', 'conflict')
            for artifact in e['artifacts']:
                if any(artifact[k] != doc[k] for k in ('code_ref','config_ref')): v.error('$.execution.artifacts', 'Artifact provenance must match experiment', 'conflict')
            if doc['kind'] == 'baseline' and doc['baseline_id'] is not None: v.error('$.baseline_id', 'Baseline cannot have baseline_id', 'conflict')
            if doc['kind'] in ('performance','confirmation') and doc['baseline_id'] is None: v.error('$.baseline_id', 'Comparison baseline required', 'conflict')
    else:
        v.scalar(doc['supersedes_id'], 'id', '$.supersedes_id', True)
        v.scalar(doc['experiment_id'], 'id', '$.experiment_id')
        for k in ('competition','external_id','leaderboard','metric'): v.scalar(doc[k], 'str', '$.' + k)
        v.enum(doc['direction'], 'minimize maximize', '$.direction')
        v.scalar(doc['score'], 'number', '$.score')
        for k in ('submitted_at','observed_at'): v.scalar(doc[k], 'time', '$.' + k)
        v.order(doc['submitted_at'], doc['observed_at'], '$')
        v.array(doc['evidence'], v.evidence, '$.evidence', True)
        if v.obj(doc['artifact'], 'path sha256', '$.artifact'):
            v.scalar(doc['artifact']['path'], 'str', '$.artifact.path')
            v.scalar(doc['artifact']['sha256'], 'hash', '$.artifact.sha256')
    return v.errors


def inspect_project(root, project, *, experiment=None, snapshot=None, check_files=True):
    """Validate a snapshot, optionally overlaying an unwritten experiment.

    Metadata mode preserves record/link/state checks but explicitly reports that
    referenced files were not checked. Full evidence validation is the default.
    """
    from .records import load_records

    root = Path(root)
    store = root / '.autoresearch'
    snapshot = snapshot if snapshot is not None else load_records(root, project)
    result = validate_document(project, 'project') + list(snapshot.diagnostics)
    records = {kind: dict(group) for kind, group in snapshot.records.items()}
    paths = dict(snapshot.paths)
    if not check_files:
        result.append(diagnostic('evidence_not_checked', store,
                                 'Referenced evidence and artifact files were not checked', 'warning'))
    if experiment is not None:
        errors = validate_document(experiment, 'experiment')
        proposed_id = experiment.get('id') if isinstance(experiment, dict) else None
        path = store / 'experiments' / ((proposed_id if isinstance(proposed_id, str) else '<invalid>') + '.json')
        for error in errors:
            error['path'] = str(path) + ':' + error['path']
        result.extend(errors)
        if not errors:
            if (isinstance(project, dict) and proposed_id == project.get('id')) or any(proposed_id in group for kind, group in records.items() if kind != 'experiment'):
                result.append(diagnostic('conflict', path, 'Duplicate record ID'))
            records['experiment'][proposed_id] = experiment
            paths[proposed_id] = path
    # A project update may change its ID after this snapshot was loaded.
    if isinstance(project, dict) and isinstance(project.get('id'), str):
        for group in records.values():
            if project['id'] in group:
                item = diagnostic('conflict', paths[project['id']], 'Duplicate record ID')
                if item not in result:
                    result.append(item)
    if any(d['code'] in ('schema','json') and d['severity'] == 'error' for d in result): return result

    def issue(doc, message, code='conflict', severity='error'):
        result.append(diagnostic(code, paths.get(doc.get('id'), store / 'project.json'), message, severity))

    def file_check(ref, sha, path, strict=False):
        if not check_files:
            return
        file = Path(ref)
        if not file.is_absolute(): file = root / file
        try:
            if not file.is_file():
                result.append(diagnostic('evidence_missing', path, 'Referenced file is unavailable: ' + ref, 'warning'))
            elif sha:
                with file.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest != sha: result.append(diagnostic('conflict' if strict else 'evidence_changed', path, 'Referenced file hash has changed: ' + ref, 'error' if strict else 'warning'))
            else:
                result.append(diagnostic('evidence_unhashed', path, 'File content identity is unverified: ' + ref, 'warning'))
        except OSError as exc: result.append(diagnostic('io', path, str(exc)))

    def evidence_walk(value, path):
        if isinstance(value, dict):
            if set(value) == {'kind','ref','locator','sha256'}:
                if value['kind'] in ('file','fixture'): file_check(value['ref'], value['sha256'], path)
                else: result.append(diagnostic('evidence_unverified', path, 'External/user evidence is recorded but not independently verified', 'warning'))
            else:
                for k,x in value.items(): evidence_walk(x, str(path) + '.' + k)
        elif isinstance(value, list):
            for i,x in enumerate(value): evidence_walk(x, f'{path}[{i}]')

    comparisons = {}
    for doc in [project] + list(records['experiment'].values()):
        comp = doc.get('comparison')
        if comp:
            if comp['id'] in comparisons and comparisons[comp['id']] != comp: issue(doc, 'Comparison ID has conflicting field values')
            comparisons[comp['id']] = comp
    for kind in ('review','submission'):
        group = records[kind]; successors = {}
        for doc in group.values():
            old = doc['supersedes_id']
            if old:
                if old not in group or old == doc['id']: issue(doc, 'Invalid supersedes reference')
                elif any(doc[k] != group[old][k] for k in (('code_ref','data_ref') if kind == 'review' else ('competition','external_id','leaderboard'))): issue(doc, 'Correction changes record identity')
                if old in successors: issue(doc, 'Correction history branches')
                successors[old] = doc['id']
            seen = {doc['id']}; cursor = old
            while cursor in group:
                if cursor in seen:
                    issue(doc, 'Correction history contains a cycle'); break
                seen.add(cursor); cursor = group[cursor]['supersedes_id']
    superseded = {d['supersedes_id'] for d in records['review'].values() if d['supersedes_id']}
    for doc in records['review'].values(): issue(doc, 'Current code/data freshness is not independently verified', 'freshness_unknown', 'warning')
    experiments = records['experiment']
    corrected = {}
    plan_fields = ('kind', 'hypothesis', 'parent_id', 'baseline_id', 'comparison', 'environment',
                   'code_ref', 'config_ref', 'command', 'review_ids')
    terminal = ('succeeded', 'failed', 'interrupted')
    for doc in experiments.values():
        correction = doc.get('correction')
        if not correction:
            continue
        ref = correction['supersedes_id']
        original = experiments.get(ref)
        if original is None or ref == doc['id']:
            issue(doc, 'Correction references a missing or identical experiment')
        else:
            if any(doc[k] != original[k] for k in plan_fields) or doc.get('run_context') != original.get('run_context'):
                issue(doc, 'Correction must retain the same execution plan')
            if doc['execution']['status'] not in terminal or original['execution']['status'] not in terminal:
                issue(doc, 'Correction requires completed executions')
            previous_artifacts = original['execution']['artifacts']
            if doc['execution']['artifacts'][:len(previous_artifacts)] != previous_artifacts:
                issue(doc, 'Correction must retain original artifacts')
        if ref in corrected:
            issue(doc, 'Experiment correction history branches')
        corrected[ref] = doc['id']
        seen = {doc['id']}
        cursor = ref
        while cursor in experiments:
            if cursor in seen:
                issue(doc, 'Experiment correction history contains a cycle')
                break
            seen.add(cursor)
            ancestor = experiments[cursor].get('correction')
            cursor = ancestor['supersedes_id'] if ancestor else None
    for original_id, replacement in corrected.items():
        if original_id in experiments:
            issue(experiments[original_id], 'Superseded by correction: ' + replacement, 'experiment_superseded', 'warning')
    for doc in experiments.values():
        for field in ('parent_id','baseline_id'):
            ref = doc[field]
            if ref in corrected:
                issue(doc, 'Referenced experiment was corrected; reassess before reuse: ' + ref, 'reference_superseded', 'warning')
            if ref is not None and (ref not in experiments or ref == doc['id']): issue(doc, 'Invalid ' + field)
            seen = {doc['id']}; cursor = ref
            while cursor in experiments:
                if cursor in seen:
                    issue(doc, field + ' contains a cycle'); break
                seen.add(cursor); cursor = experiments[cursor][field]
        base = experiments.get(doc['baseline_id'])
        if base and doc['comparison'] != base['comparison']: issue(doc, 'Baseline comparison differs')
        for ref in doc['review_ids']:
            if ref not in records['review']: issue(doc, 'Missing review: ' + ref)
            elif ref in superseded: issue(doc, 'Referenced review has been superseded: ' + ref, 'review_superseded', 'warning')
        for a in doc['execution']['artifacts']: file_check(a['path'], a['sha256'], paths[doc['id']])
    selected = project.get('selected_experiment_id')
    if selected is not None:
        doc = experiments.get(selected)
        if selected in corrected or not doc or doc['execution']['status'] != 'succeeded' or not doc['decision'] or doc['decision']['status'] != 'keep' or doc['decision']['validity'] != 'valid' or doc['comparison'] != project['comparison']:
            issue(project, 'Selected experiment must be a succeeded valid keep in the current comparison')
    tuples = {}
    for doc in records['submission'].values():
        exp = experiments.get(doc['experiment_id'])
        if doc['experiment_id'] in corrected:
            issue(doc, 'Submission retains a superseded experiment reference', 'reference_superseded', 'warning')
        if not exp or exp['execution']['status'] != 'succeeded': issue(doc, 'Submission requires a succeeded experiment')
        elif not any(a['role'] == 'submission' and all(a[k] == doc['artifact'][k] for k in ('path','sha256')) for a in exp['execution']['artifacts']): issue(doc, 'Submission artifact does not match experiment artifact')
        file_check(doc['artifact']['path'], doc['artifact']['sha256'], paths[doc['id']], True)
        key = tuple(doc[k] for k in ('competition','external_id','leaderboard'))
        tuples.setdefault(key, []).append(doc)
    for docs in tuples.values():
        if len([d for d in docs if d['supersedes_id'] is None]) > 1: issue(docs[-1], 'Duplicate submission identity without correction')
    from .memories import validate_links
    validate_links(records, issue)
    for group in records.values():
        for doc in group.values(): evidence_walk(doc, paths[doc['id']])
    return result
