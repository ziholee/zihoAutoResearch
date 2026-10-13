"""Export the packaged skill into an explicitly chosen, unused directory."""
from importlib.resources import files
from pathlib import Path
import re
import stat
import unicodedata


class DestinationExists(FileExistsError):
    """The user-selected destination is already occupied."""


def skill_source():
    bundled = files('zar').joinpath('_bundled_skill')
    if bundled.is_dir():
        return bundled
    # Setuptools maps this canonical tree into zar._bundled_skill in wheels.
    # Running directly from a source checkout uses that same tree in place.
    root = Path(__file__).resolve().parent.parent
    source = root / 'skills' / 'ziho-autoresearch'
    if (root / 'pyproject.toml').is_file() and (source / 'SKILL.md').is_file():
        return source
    raise FileNotFoundError('The distribution does not contain the ziho-autoresearch skill.')


def install_skill(destination):
    destination = Path(destination).expanduser().absolute()
    source = skill_source()
    created = []
    try:
        destination.mkdir()
    except FileExistsError as exc:
        raise DestinationExists(str(destination)) from exc
    created.append(destination)

    def copy_tree(origin, target):
        for child in sorted(origin.iterdir(), key=lambda entry: entry.name):
            output = target / child.name
            if child.is_dir():
                output.mkdir()
                created.append(output)
                copy_tree(child, output)
            else:
                with output.open('xb') as stream:
                    created.append(output)
                    stream.write(child.read_bytes())

    try:
        copy_tree(source, destination)
    except BaseException:
        # Only remove entries created by this invocation. Never recursively remove
        # unexpected files which another process may have added during the copy.
        for path in reversed(created):
            try:
                path.rmdir() if path.is_dir() else path.unlink()
            except OSError:
                pass
        raise
    return {'view': 'skill_install', 'destination': str(destination),
            'files': sorted(path.relative_to(destination).as_posix()
                            for path in created if path.is_file())}


def skill_guidance(directory):
    """Render project instructions without writing or registering anything."""
    def valid_path(value):
        return value.strip() and not any(
            unicodedata.category(char).startswith('C') or
            unicodedata.category(char) in ('Zl', 'Zp') for char in value)

    if not valid_path(directory):
        raise ValueError('Skill directory must be explicit and contain no control characters.')
    try:
        skill = Path(directory).expanduser().absolute() / 'SKILL.md'
    except RuntimeError as exc:
        raise ValueError('Cannot expand the home directory in the skill path.') from exc
    if not valid_path(str(skill)):
        raise ValueError('Skill path contains control characters.')
    if not skill.is_file():
        raise FileNotFoundError(2, 'Expected an existing SKILL.md file', str(skill))
    # A code span prevents path punctuation from becoming Markdown instructions.
    delimiter = '`' * (1 + max((len(run) for run in re.findall(r'`+', str(skill))), default=0))
    path_span = f'{delimiter} {skill} {delimiter}'
    markdown = (
        '## ML experiments with ziho-autoresearch\n\n'
        f'- For ML experiment planning, execution, recording or resumption, read {path_span} '
        'and follow its applicable procedures alongside this project’s instructions. '
        'If unavailable, report the missing skill and restore its path before running experiments.\n'
        '- Work in the intended ML project. Before resuming, run `zar context --json` and '
        '`zar status --json` there (or pass `--project <root>`); inspect the actual workspace too. '
        'If uninitialized, initialize only the intended project within the user’s scope.\n'
        '- Do not rerun an `unknown` experiment until its actual process and logs establish its state.\n'
        '- Respect the user-authorized editable paths, execution environment, run count and time budget. '
        'Using this skill does not authorize training or external submission.\n'
        '- Use `zar check --json` before relying on recorded evidence for a consequential decision. '
        'Metadata checks do not prove ML validity or that selected code is checked out.\n'
        '- Keep experiment records in `.autoresearch/`; use `.autoresearch/program.md` for project '
        'interpretation and `project.json` for settings. Do not duplicate changing state here.\n'
    )
    return {'view': 'skill_guidance', 'skill_file': str(skill), 'markdown': markdown}


AGENT_DIRECTORIES = {'codex': '.agents', 'claude': '.claude'}


def install_agent_skill(agent, scope, project, *, dry_run=False):
    """Install in a documented discovery directory, preserving occupied paths."""
    try:
        root = Path.home() if scope == 'user' else Path(project).expanduser().absolute()
    except RuntimeError as exc:
        raise ValueError('Cannot determine the installation root home directory.') from exc
    if not str(root).strip() or any(
            unicodedata.category(char).startswith('C') or
            unicodedata.category(char) in ('Zl', 'Zp') for char in str(root)):
        raise ValueError('Installation root must contain no control characters.')
    if scope == 'project' and not project.strip():
        raise ValueError('Project must be an explicit existing directory.')
    if not root.is_dir():
        raise FileNotFoundError(2, 'Installation root must already be a directory', str(root))
    root = root.resolve()
    parents = [root / AGENT_DIRECTORIES[agent], root / AGENT_DIRECTORIES[agent] / 'skills']
    destination = parents[-1] / 'ziho-autoresearch'

    def redirected(path):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        # Reparse attributes also catch Windows junctions on Python 3.11,
        # which predates Path.is_junction(). Do not follow redirecting entries.
        return (stat.S_ISLNK(info.st_mode) or
                bool(getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT))

    def check_parent(path):
        if redirected(path) or (path.exists() and not path.is_dir()):
            raise DestinationExists(str(path))

    for path in parents:
        check_parent(path)
    if destination.exists() or redirected(destination):
        raise DestinationExists(str(destination))
    skill_source()  # Fail before creating discovery directories if the bundle is unavailable.
    result = {'view': 'skill_install', 'destination': str(destination), 'files': []}
    created = []
    try:
        if not dry_run:
            for path in parents:
                try:
                    path.mkdir()
                    created.append(path)
                except FileExistsError:
                    check_parent(path)
            result = install_skill(destination)
    except BaseException:
        for path in reversed(created):
            try:
                path.rmdir()  # Keep preexisting parents and concurrent writers' files.
            except OSError:
                pass
        raise
    invocation = ('$' if agent == 'codex' else '/') + 'ziho-autoresearch'
    result.update(agent=agent, scope=scope, dry_run=dry_run, invocation=invocation,
                  next_steps=[
                      'Open the target ML project in the agent; ensure zar is available in its terminal.',
                      'If the skill is not listed, restart the agent and check its skill settings.',
                      f'{invocation} Inspect this project without training; propose the first experiment plan.',
                      'Installation does not authorize training or verify agent discovery.'])
    return result
