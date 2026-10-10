#!/usr/bin/env python3
"""Verify built distributions outside the checkout with synthetic observations only."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import venv


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
    for directory in ('reviews', 'experiments', 'submissions', 'memories'):
        paths.extend(sorted((store / directory).glob('*.json')))
    return {path.relative_to(store).as_posix(): path.read_bytes() for path in paths}


def verify(dist: Path) -> None:
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
        checkout = Path(__file__).resolve().parents[1]
        require(not workspace.is_relative_to(checkout), 'Package verification must run outside the checkout')
        virtual = workspace / 'venv'
        venv.EnvBuilder(with_pip=True).create(virtual)
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
    print('Package verification passed; observations were synthetic and no training was requested.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=Path('dist'), help='directory containing one wheel and sdist')
    arguments = parser.parse_args()
    try:
        verify(arguments.dist)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.TimeoutExpired) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
