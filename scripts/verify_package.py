#!/usr/bin/env python3
"""Verify built distributions outside the checkout using local synthetic examples."""
from __future__ import annotations

import argparse
from decimal import Decimal
from email import policy
from email.parser import BytesParser
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from urllib.parse import unquote, urlsplit


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run(arguments: list[str], cwd: Path, environment: dict[str, str], timeout: int = 90) -> str:
    result = subprocess.run(arguments, cwd=cwd, env=environment, capture_output=True,
                            text=True, encoding='utf-8', timeout=timeout)
    require(result.returncode == 0,
            f'Command failed ({result.returncode}): {arguments!r}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def unpack_source(archive: Path, destination: Path) -> Path:
    """Extract ordinary files/directories only; never follow archive links."""
    destination.mkdir()
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        roots = set()
        for member in members:
            relative = PurePosixPath(member.name)
            require(bool(relative.parts) and not relative.is_absolute()
                    and '..' not in relative.parts and '\\' not in member.name
                    and ':' not in member.name,
                    f'Unsafe source archive path: {member.name}')
            require(member.isdir() or member.isfile(), f'Unsupported archive member: {member.name}')
            roots.add(relative.parts[0])
        require(len(roots) == 1, 'Source archive must contain a single root directory')
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = bundle.extractfile(member)
                require(source is not None, f'Cannot read archive member: {member.name}')
                with source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
    return destination / next(iter(roots))


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'), parse_float=Decimal)


def canonical_bytes(store: Path) -> dict[str, bytes]:
    paths = [store / 'project.json']
    for directory in ('reviews', 'experiments', 'submissions', 'memories', 'candidates'):
        paths.extend(sorted((store / directory).glob('*.json')))
    return {path.relative_to(store).as_posix(): path.read_bytes() for path in paths}


def verify_release_metadata(wheel: Path, source: Path, checkout: Path) -> None:
    """Check the shipped metadata, license and release instructions themselves."""
    for relative in ('pyproject.toml', 'README.md', 'LICENSE', 'CHANGELOG.md', 'docs/releasing.md'):
        shipped = source / relative
        require(shipped.is_file(), f'Source distribution is missing {relative}')
        require(shipped.read_bytes() == (checkout / relative).read_bytes(),
                f'Source distribution contains stale {relative}')
    project_file = tomllib.loads((source / 'pyproject.toml').read_text(encoding='utf-8'))
    project = project_file['project']
    expected = {'name': 'ziho-autoresearch', 'requires-python': '>=3.11',
                'dependencies': [], 'license': 'MIT', 'license-files': ['LICENSE'], 'readme': 'README.md'}
    for key, value in expected.items():
        require(project.get(key) == value, f'Unexpected release project metadata: {key}')
    urls = project['urls']
    require(set(urls) == {'Repository', 'Issues', 'Documentation'}, 'Missing release project URLs')
    for value in urls.values():
        require(isinstance(value, str)
                and (value == 'https://github.com/ziholee/zihoAutoResearch'
                     or value.startswith('https://github.com/ziholee/zihoAutoResearch/')),
                f'Unexpected release project URL: {value}')
    readme = (source / 'README.md').read_text(encoding='utf-8').strip()
    require(bool(readme), 'Release README must not be empty')
    metadata_fields = {'Name': project['name'], 'Version': project['version'],
                       'Requires-Python': project['requires-python'], 'License-Expression': project['license'],
                       'Description-Content-Type': 'text/markdown'}
    with zipfile.ZipFile(wheel) as bundle:
        metadata_paths = [name for name in bundle.namelist() if name.endswith('.dist-info/METADATA')]
        require(len(metadata_paths) == 1, 'Wheel must contain exactly one distribution METADATA')
        wheel_metadata = BytesParser(policy=policy.default).parsebytes(bundle.read(metadata_paths[0]))
        source_metadata = BytesParser(policy=policy.default).parsebytes((source / 'PKG-INFO').read_bytes())
        for label, metadata in (('wheel', wheel_metadata), ('sdist', source_metadata)):
            require(tuple(int(part) for part in metadata.get('Metadata-Version', '0').split('.')) >= (2, 4),
                    f'{label}: PEP 639-capable metadata version expected')
            for key, value in metadata_fields.items():
                require(metadata.get_all(key) == [value], f'{label}: unexpected {key} metadata')
            require(not metadata.get_all('Requires-Dist'), f'{label}: runtime dependencies must remain empty')
            require(metadata.get_all('License-File') == ['LICENSE'], f'{label}: missing LICENSE metadata reference')
            require(sorted(metadata.get_all('Project-URL', []))
                    == sorted(f'{key}, {value}' for key, value in urls.items()),
                    f'{label}: project URL metadata differs from pyproject.toml')
            require(metadata.get_payload(decode=True).decode('utf-8').strip() == readme,
                    f'{label}: README body differs from source')
        require(wheel_metadata['Metadata-Version'] == source_metadata['Metadata-Version'],
                'Wheel and source metadata versions differ')
        license_path = str(PurePosixPath(metadata_paths[0]).parent / 'licenses' / 'LICENSE')
        require(license_path in bundle.namelist(), 'Wheel is missing the referenced LICENSE file')
        require(bundle.read(license_path) == (source / 'LICENSE').read_bytes(),
                'Wheel LICENSE differs from source distribution')
    print('PASS: wheel/sdist release metadata, README, MIT license and release documentation')


def verify_skill_export(wheel: Path, source: Path, checkout: Path, workspace: Path,
                        virtual: Path, environment: dict[str, str]) -> None:
    canonical = checkout / 'skills/ziho-autoresearch'
    expected = {path.relative_to(canonical).as_posix(): path.read_bytes()
                for path in canonical.rglob('*') if path.is_file()}
    require('SKILL.md' in expected and 'references/cli-recipes.md' in expected,
            'Canonical skill or its CLI recipes are missing')
    source_skill = source / 'skills/ziho-autoresearch'
    shipped = {path.relative_to(source_skill).as_posix(): path.read_bytes()
               for path in source_skill.rglob('*') if path.is_file()}
    require(shipped == expected, 'Source distribution skill differs from canonical source')
    with zipfile.ZipFile(wheel) as bundle:
        prefix = 'zar/_bundled_skill/'
        bundled = {name.removeprefix(prefix): bundle.read(name) for name in bundle.namelist()
                   if name.startswith(prefix) and not name.endswith('/')}
    require(bundled == expected, 'Wheel skill differs from canonical source')
    cli = virtual / ('Scripts/zar.exe' if os.name == 'nt' else 'bin/zar')
    destination = workspace / 'exported-skill'
    command = [str(cli), 'skill', 'install', '--dest', str(destination), '--json']
    result = json.loads(run(command, workspace, environment))
    require(result['ok'] is True and result['data']['destination'] == str(destination)
            and result['data']['files'] == sorted(expected), 'Unexpected skill export result')
    exported = {path.relative_to(destination).as_posix(): path.read_bytes()
                for path in destination.rglob('*') if path.is_file()}
    require(exported == expected, 'Exported skill differs from canonical source')
    for name, content in exported.items():
        if not name.endswith('.md'):
            continue
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', content.decode('utf-8')):
            link = urlsplit(target)
            if link.scheme or link.netloc or not link.path:
                continue
            referenced = (destination / name).parent / unquote(link.path)
            require(referenced.resolve().is_relative_to(destination.resolve()) and referenced.is_file(),
                    f'Exported skill has missing or escaping reference: {name}: {target}')
    rejected = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                              text=True, encoding='utf-8', timeout=90)
    require(rejected.returncode == 3 and json.loads(rejected.stdout)['ok'] is False,
            'Installed skill export did not reject an existing destination')
    require(exported == {path.relative_to(destination).as_posix(): path.read_bytes()
                         for path in destination.rglob('*') if path.is_file()},
            'Rejected skill export modified existing files')
    require(not (workspace / '.autoresearch').exists(), 'Skill export initialized a project')
    instructions = workspace / 'AGENTS.md'
    instructions.write_bytes(b'existing project instructions\n')
    guidance_command = [str(cli), 'skill', 'guidance', '--skill-dir', str(destination)]
    guidance = json.loads(run([*guidance_command, '--json'], workspace, environment))
    require(guidance['ok'] and guidance['data']['view'] == 'skill_guidance'
            and Path(guidance['data']['skill_file']).samefile(destination / 'SKILL.md'),
            'Unexpected installed skill guidance result')
    require(run(guidance_command, workspace, environment).rstrip('\n') ==
            guidance['data']['markdown'].rstrip('\n'), 'Guidance text and JSON differ')
    require(instructions.read_bytes() == b'existing project instructions\n'
            and not (workspace / '.autoresearch').exists(), 'Guidance modified project files')
    for agent, directory, invocation in (('codex', '.agents', '$ziho-autoresearch'),
                                          ('claude', '.claude', '/ziho-autoresearch')):
        target = workspace / (agent + '-project')
        target.mkdir()
        for name in ('AGENTS.md', 'CLAUDE.md'):
            (target / name).write_bytes(b'original rules\n')
        command = [str(cli), 'skill', 'install', '--agent', agent, '--project', str(target)]
        preview = json.loads(run([*command, '--dry-run', '--json'], workspace, environment))
        require(preview['ok'] and preview['data']['dry_run']
                and not (target / directory).exists(), 'Preview wrote discovery files')
        installed_skill = json.loads(run([*command, '--json'], workspace, environment))
        location = target / directory / 'skills/ziho-autoresearch'
        require(installed_skill['ok'] and installed_skill['data']['invocation'] == invocation
                and Path(installed_skill['data']['destination']).samefile(location),
                'Unexpected agent installation result')
        require(expected == {path.relative_to(location).as_posix(): path.read_bytes()
                             for path in location.rglob('*') if path.is_file()},
                'Agent installation differs from the bundled skill')
        conflict = subprocess.run([*command, '--json'], cwd=workspace, env=environment,
                                  capture_output=True, text=True, encoding='utf-8', timeout=90)
        require(conflict.returncode == 3 and not json.loads(conflict.stdout)['ok'],
                'Existing agent skill was overwritten')
        for name in ('AGENTS.md', 'CLAUDE.md'):
            require((target / name).read_bytes() == b'original rules\n', 'Instructions modified')
        require(not (target / '.autoresearch').exists(), 'Agent installation initialized a project')
    print('PASS: installed wheel Codex/Claude discovery directories, preview, contents and conflicts')
    print('PASS: installed wheel guidance text/JSON and existing instructions preserved')
    print('PASS: installed wheel skill export; complete bytes, local references and overwrite refusal')


def verify(dist: Path, checkout: Path | None = None) -> None:
    dist = dist.resolve()
    wheels = sorted(dist.glob('*.whl'))
    sources = sorted(dist.glob('*.tar.gz'))
    require(len(wheels) == 1 and len(sources) == 1,
            f'{dist}: expected exactly one wheel and one .tar.gz source distribution')
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONHOME', None)
    environment['PYTHONNOUSERSITE'] = '1'
    with tempfile.TemporaryDirectory(prefix='zar-package-check-') as temporary:
        workspace = Path(temporary).resolve()
        checkout = (checkout or Path(__file__).resolve().parents[1]).resolve()
        require(not workspace.is_relative_to(checkout), 'Package verification must run outside the checkout')
        virtual = workspace / 'venv'
        venv.EnvBuilder(with_pip=True, symlinks=(os.name != 'nt')).create(virtual)
        python = virtual / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        run([str(python), '-I', '-m', 'pip', 'install', '--no-index', '--no-deps',
             '--disable-pip-version-check', str(wheels[0])], workspace, environment)
        installed = json.loads(run([str(python), '-I', '-c',
            'import json, sysconfig, zar; print(json.dumps({"module": zar.__file__, '
            '"site": sysconfig.get_path("purelib")}))'], workspace, environment))
        module = Path(installed['module']).resolve()
        site = Path(installed['site']).resolve()
        require(site.is_relative_to(virtual.resolve()) and module.is_relative_to(site),
                f'zar was not imported from the fresh environment site-packages: {module}')
        source = unpack_source(sources[0], workspace / 'source')
        verify_release_metadata(wheels[0], source, checkout)
        verify_skill_export(wheels[0], source, checkout, workspace, virtual, environment)
        example = source / 'examples/mock-cycle.py'
        require(example.is_file(), 'Source distribution is missing examples/mock-cycle.py')
        require((source / 'skills/ziho-autoresearch/SKILL.md').is_file(),
                'Source distribution is missing the published skill')
        require((source / 'skills/ziho-autoresearch/references/cli-recipes.md').is_file(),
                'Source distribution is missing the skill CLI recipes')
        for scenario in ('comparable', 'scope-mismatch'):
            output = workspace / scenario
            stdout = run([str(python), '-I', str(example), '--output', str(output),
                          '--scenario', scenario], workspace, environment)
            summary = read_json(output / 'summary.json')
            require(json.loads(stdout, parse_float=Decimal) == summary, 'Example stdout and summary differ')
            require(summary['simulated'] is True and summary['scenario'] == scenario,
                    f'{scenario}: example must identify synthetic observations')
            require(summary['unfinished'] == [] and summary['budget_used'] == 2,
                    f'{scenario}: unexpected unfinished work or mock budget usage')
            comparison = summary['comparison']
            if scenario == 'comparable':
                require(comparison['comparable'] is True and comparison['improvement'] == Decimal('0.1'),
                        'Comparable example must show exact synthetic 0.1 improvement')
                require(summary['decision']['status'] == 'keep'
                        and summary['selected_experiment_id'] == 'mock-candidate'
                        and summary['workspace_matches_selection'] is True,
                        'Comparable example must adopt the candidate')
            else:
                require(comparison['comparable'] is False and comparison['improvement'] is None
                        and 'scope_mismatch' in comparison['reasons'],
                        'Scope mismatch must block comparison')
                require(summary['decision']['status'] == 'hold'
                        and summary['decision']['validity'] == 'not_comparable'
                        and summary['selected_experiment_id'] == 'mock-baseline'
                        and summary['workspace_matches_selection'] is False,
                        'Scope mismatch must hold candidate and preserve baseline selection')
            project = output / 'project'
            store = project / '.autoresearch'
            report = store / 'reports/summary.md'
            require(report.is_file() and report.stat().st_size > 0, f'{scenario}: report is missing or empty')
            require(Path(summary['report']).resolve() == report.resolve(), f'{scenario}: wrong report path')
            before = canonical_bytes(store)
            regenerated = json.loads(run([str(python), '-I', '-m', 'zar', 'report', '--project', str(project),
                                          '--output', 'summary.md', '--overwrite', '--json'],
                                         workspace, environment))
            require(regenerated['ok'] is True, f'{scenario}: report overwrite failed')
            require(before == canonical_bytes(store), f'{scenario}: report overwrite changed canonical JSON')
            require(report.is_file() and report.stat().st_size > 0, f'{scenario}: regenerated report is empty')
            require(not list(output.rglob('TRAINING_WAS_EXECUTED')), f'{scenario}: training marker was created')
            print(f'PASS: installed wheel + sdist {scenario}; report preserves canonical JSON')
        memory_example = source / 'examples/mock-memory.py'
        require(memory_example.is_file(), 'Source distribution is missing examples/mock-memory.py')
        summary = json.loads(run([str(python), '-I', str(memory_example), '--output', str(workspace / 'memory-cycle')],
                                 workspace, environment))
        require(summary == dict(simulated=True, memory_counts=dict(total=3, active=0, retired=1, superseded=2),
                                originals_preserved=True, evidence_hash_matched=True, budget_used=2),
                'Unexpected installed-package memory lifecycle result')
        print('PASS: installed wheel + sdist failure memory; recall, evidence, retirement and original preservation')
        candidate_example = source / 'examples/mock-candidates.py'
        require(candidate_example.is_file(), 'Source distribution is missing examples/mock-candidates.py')
        summary = json.loads(run([str(python), '-I', str(candidate_example), '--output', str(workspace / 'candidate-cycle')],
                                 workspace, environment))
        require(summary == dict(simulated=True, deferred=1, non_improving=1, forecasts_preserved=True,
                                actual_cost_state='unknown', budget_used=2, selected_experiment_id='reference'),
                'Unexpected installed-package candidate lifecycle result')
        print('PASS: installed wheel + sdist candidate rationale; forecasts, observations, deferral and original preservation')
        lineage_example = source / 'examples/mock-lineage.py'
        require(lineage_example.is_file(), 'Source distribution is missing examples/mock-lineage.py')
        summary = json.loads(run([str(python), '-I', str(lineage_example), '--output', str(workspace / 'lineage-cycle')],
                                 workspace, environment))
        require(summary == dict(simulated=True, git_linear=True, experiment_siblings=True, record_count=4,
                                execution_count=3, correction_count=1, failed_count=1, cancelled_count=1,
                                stale_reference_count=4, originals_preserved=True, git_head_preserved=True,
                                training_executed=False, budget_used=2),
                'Unexpected installed-package lineage result')
        print('PASS: installed wheel + sdist lineage; Git history differs from experiment ancestry, originals preserved')
        resume_example = source / 'examples/mock-resume.py'
        require(resume_example.is_file(), 'Source distribution is missing examples/mock-resume.py')
        for scope in ('full', 'proxy'):
            # Exercise record preservation even with a drafts-named ancestor.
            target = workspace / 'drafts' / ('resume-' + scope)
            # Separate harness invocations discard all in-memory state at the checkpoint.
            run([str(python), '-I', str(resume_example), 'prepare', '--root', str(target),
                 '--scope', scope], workspace, environment)
            run([str(python), '-I', str(resume_example), 'resume', '--root', str(target)],
                workspace, environment)
            result = read_json(target.parent / (target.name + '-result.json'))
            for field in ('baseline_preserved', 'read_and_report_canonical_preserved',
                          'unknown_same_id_resolved', 'evidence_prefix_preserved', 'workspace_files_preserved'):
                require(result[field] is True, f'{scope}: resume failed {field}')
            state = result['final_status']['data']
            require(state['budget_used'] == 2 and state['unfinished'] == []
                    and state['selected_experiment_id'] == 'demand-base', 'Resume altered budget or selection')
            require(result['training_invoked'] is False, 'Resume executed the training sentinel')
            comparison = result['comparison']['data']
            require(comparison['comparable'] is (scope == 'full'), 'Unexpected resumed comparison')
            if scope == 'full':
                require(comparison['improvement'] == Decimal('0.2'), 'Unexpected resumed numeric improvement')
            else:
                require(comparison['improvement'] is None and 'scope_mismatch' in comparison['reasons'],
                        'Resumed proxy/full mismatch not preserved')
            require(result['mismatch']['ok'] is False and result['mismatch']['data'] is None,
                    'Changed evidence returned content')
            require(any(item['code'] == 'evidence_changed'
                        for item in result['changed_evidence_comparison']['diagnostics']),
                    'Changed evidence warning was lost')
            print(f'PASS: installed wheel + sdist {scope} resume; fresh process, unknown evidence, hold and preservation')
        ml_example = source / 'examples/ml-loop.py'
        require(ml_example.is_file(), 'Source distribution is missing examples/ml-loop.py')
        output = workspace / 'ml-cycle'
        summary = json.loads(run([str(python), '-I', str(ml_example), '--output', str(output)],
                                 workspace, environment, timeout=120))
        require(summary == json.loads((output / 'summary.json').read_text(encoding='utf-8')),
                'ML example stdout and summary differ')
        require(summary['execution_count'] == 2, 'ML resume must not rerun training')
        print('PASS: installed wheel + sdist actual synthetic ML; baseline, candidate and fresh-process resume')
        crash_example = source / 'examples/crash-recovery.py'
        require(crash_example.is_file(), 'Source distribution is missing examples/crash-recovery.py')
        if sys.platform.startswith('linux') or sys.platform == 'darwin':
            output = workspace / 'crash-cycle'
            summary = json.loads(run([str(python), '-I', str(crash_example), '--output', str(output)],
                                     workspace, environment, timeout=120))
            require(summary == json.loads((output / 'summary.json').read_text(encoding='utf-8')),
                    'Crash example stdout and summary differ')
            print('PASS: installed wheel + sdist real CLI termination, unknown preservation and evidence-based recovery')
        else:
            print('SKIP: CLI crash example needs Linux waitpid or macOS kqueue exit witness')
        utility = source / 'scripts/benchmark_workflow_utility.py'
        require(utility.is_file(), 'Source distribution is missing workflow utility benchmark')
        output = workspace / 'workflow-utility'
        summary = json.loads(run([str(python), '-I', str(utility), '--output', str(output), '--repeats', '1'],
                                 workspace, environment, timeout=180))
        require(summary == json.loads((output / 'summary.json').read_text(encoding='utf-8')),
                'Utility benchmark stdout and summary differ')
        for arm in ('direct', 'zar'):
            result = summary['trials'][0]['arms'][arm]
            require(result['verified'] and result['execution_count'] == 2
                    and result['resumed_without_execution'], 'Paired workflow requirements failed')
        print('PASS: installed wheel + sdist paired direct/Git and zar workflow; no timing superiority gate')
    print('Package verification passed; local synthetic examples only, no cloud model calls.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=Path('dist'), help='directory containing one wheel and sdist')
    parser.add_argument('--checkout', type=Path, help='source checkout matching these distributions')
    arguments = parser.parse_args()
    try:
        verify(arguments.dist, arguments.checkout)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, zipfile.BadZipFile,
            subprocess.TimeoutExpired) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
