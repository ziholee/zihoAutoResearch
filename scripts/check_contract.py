#!/usr/bin/env python3
"""Check repository documentation contracts using only the Python standard library.

This checks file links, not Markdown anchor spelling or the truth of prose claims.
It never runs an ML command or contacts a remote service.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path
import subprocess
import sys
import tomllib
from urllib.parse import unquote, urlsplit


# Inline links (including images) and explicit reference-link definitions.
_LINK = re.compile(r'\]\(\s*(<[^>\n]+>|(?:[^()\n]|\([^()\n]*\))+)\s*\)')
_REFERENCE = re.compile(r'^ {0,3}\[[^]\n]+\]:\s*(<[^>\n]+>|\S+)', re.MULTILINE)
_LOCAL_HOME = re.compile(r'(?:/(?:Users|home)/[^\s/]+/|[A-Za-z]:[\\/]Users[\\/]|~[/\\]\.(?:codex|agents)[/\\])')


# Visible declaration vocabulary, not full translated prose or a package version.
# Public releases can lag behind the version being developed in pyproject.toml.
_READMES = {
    'README.md': ('공개', '개발', '미배포', '포함되지 않습니다'),
    'README.en.md': ('Public', 'Development', 'unreleased', 'not included in public'),
    'README.ja.md': ('公開版', '開発', '未リリース', 'に含まれません'),
    'README.zh-CN.md': ('公开版', '开发', '尚未发布', '不包含在公开版'),
}
_GUIDES = ('uv-installation', 'agent-installation', 'first-run-and-resume', 'research-api')


def _without_comments(text: str) -> str:
    # Preserve line numbers for file-link diagnostics and scope boundaries.
    return re.sub(r'<!--.*?(?:-->|\Z)', lambda match: '\n' * match[0].count('\n'), text, flags=re.DOTALL)


def _shell_commands(text: str) -> list[tuple[str, ...]]:
    """Read complete single-line examples; never execute a documented command."""
    commands = []
    fence = None
    shell = False
    pending = []
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence is None and match:
            fence = match[1]
            shell = match[2].strip() in ('sh', 'bash', 'shell')
            pending = []
        elif fence is not None:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                commands.extend(pending)
                fence = None
            elif shell:
                try:
                    pending.append(tuple(shlex.split(line, comments=True)))
                except ValueError:
                    pass  # An incomplete example cannot satisfy a required command.
    return commands


def _readme_contracts(texts: dict[str, str]) -> list[str]:
    errors = []
    versions = {}
    for name, (public, development, unreleased, exclusion) in _READMES.items():
        if name not in texts:
            continue  # File-reading diagnostics are emitted by validate().
        text = _without_comments(texts[name])
        visible = _without_fences(text)
        lines = visible.splitlines()
        headings = [i for i, line in enumerate(lines)
                    if re.match(r'^##[ \t]+', line) and development in line and unreleased in line]
        if len(headings) != 1:
            errors.append(f'{name}: README contract needs one development/unreleased heading')
        boundary = headings[0] if headings else len(lines)
        public_text = '\n'.join(lines[:boundary])
        declarations = re.findall(r'(?m)^\s*(?:\*\*)?' + re.escape(public)
                                  + r'[ \t]+v(\d+\.\d+\.\d+)\b', public_text)
        if len(declarations) != 1:
            errors.append(f'{name}: README contract needs one visible public declaration before development')
        else:
            version = declarations[0]
            versions[name] = version
            end = next((i for i in range(boundary + 1, len(lines)) if re.match(r'^##[ \t]+', lines[i])), len(lines))
            paragraphs = re.split(r'\n\s*\n', '\n'.join(lines[boundary + 1:end]))
            exclusions = [p for p in paragraphs if 'research' in p and exclusion in p]
            if not exclusions or any(set(re.findall(r'\bv(\d+\.\d+\.\d+)(?![0-9]|[.][0-9])', p)) != {version} for p in exclusions):
                errors.append(f'{name}: README contract needs research exclusion with matching public version in development section')
        commands = _shell_commands('\n'.join(text.splitlines()[:boundary]))
        required = (
            ('uv tool install ziho-autoresearch', ('uv', 'tool', 'install', 'ziho-autoresearch'), False),
            ('python -m venv <directory>', ('python', '-m', 'venv'), True),
            ('python -m pip install ziho-autoresearch', ('python', '-m', 'pip', 'install', 'ziho-autoresearch'), False),
            ('zar --help', ('zar', '--help'), False),
            ('zar skill install --agent codex --project <directory>', ('zar', 'skill', 'install', '--agent', 'codex', '--project'), True),
            ('zar skill install --agent claude --project <directory>', ('zar', 'skill', 'install', '--agent', 'claude', '--project'), True),
        )
        for label, prefix, argument in required:
            if not any(command == prefix if not argument else
                       len(command) == len(prefix) + 1 and command[:-1] == prefix and bool(command[-1])
                       for command in commands):
                errors.append(f'{name}: missing public installation command `{label}` in a shell fence')
        targets = set()
        # Required guides use inline links in the README contract. An orphan
        # reference definition is not a user-visible navigation link.
        for match in _LINK.finditer(visible):
            try:
                url = urlsplit(_destination(match[1]))
                if not url.scheme and not url.netloc:
                    targets.add(unquote(url.path).removeprefix('./'))
            except ValueError:
                pass  # The ordinary file-link pass reports malformed URLs.
        for guide in _GUIDES:
            if f'docs/{guide}.md' not in targets:
                errors.append(f'{name}: missing required guide link docs/{guide}.md')
    canonical = versions.get('README.md')
    if canonical:
        for name, version in versions.items():
            if version != canonical:
                errors.append(f'{name}: public version v{version} differs from README.md v{canonical}')
    return errors


def _without_fences(text: str) -> str:
    """Exclude literal examples while retaining their line numbers for diagnostics."""
    lines = []
    fence = None
    for line in text.splitlines(keepends=True):
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if fence is None and match:
            fence = match.group(1)
            lines.append('\n')
        elif fence is not None:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
                fence = None
            lines.append('\n')
        else:
            lines.append(line)
    return ''.join(lines)


def _destination(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('<'):
        return raw[1:raw.index('>')]
    # A quoted optional title is separate from the path; tolerate unescaped spaces.
    return re.sub(r'\s+[\"\'][^\n]*[\"\']\s*$', '', raw).strip()


def _commands(root: Path) -> set[str]:
    # Plain help comes from argparse's real command registration. The JSON help
    # contains a separately maintained list, so it cannot alone detect a new command.
    result = subprocess.run([sys.executable, '-m', 'zar', '--help'], cwd=root,
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError(f'CLI help failed: {result.stderr.strip() or result.stdout.strip()}')
    match = re.search(r'\{([a-z][a-z0-9_-]*(?:,[a-z][a-z0-9_-]*)+)\}', result.stdout)
    if not match:
        raise ValueError('CLI help does not expose the top-level command choices')
    return set(match.group(1).split(','))


def validate(root: Path) -> list[str]:
    """Return actionable contract errors for a source checkout rooted at *root*."""
    root = Path(root).resolve()
    errors: list[str] = []
    markdown = {root / name for name in _READMES}
    for directory in ('docs', 'templates', 'skills'):
        markdown.update((root / directory).rglob('*.md'))
    texts = {}
    for path in sorted(markdown):
        relative = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            errors.append(f'{relative}: cannot read Markdown: {exc}')
            continue
        texts[relative] = text
        prose = _without_fences(_without_comments(text))
        for match in list(_LINK.finditer(prose)) + list(_REFERENCE.finditer(prose)):
            target = _destination(match.group(1))
            try:
                url = urlsplit(target)
            except ValueError:
                errors.append(f'{relative}: invalid link: {target}')
                continue
            if url.scheme or url.netloc or not url.path:
                continue
            local = unquote(url.path)
            local = re.sub(r'\\([ ()])', r'\1', local)
            linked = root / local.lstrip('/') if local.startswith('/') else path.parent / local
            if not linked.exists():
                line = prose.count('\n', 0, match.start()) + 1
                errors.append(f'{relative}:{line}: missing local link target: {target}')
        if relative.startswith('skills/') and _LOCAL_HOME.search(text):
            errors.append(f'{relative}: machine-local home/tool path is not portable')
        if path.name == 'SKILL.md':
            front = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', text, re.DOTALL)
            if not front:
                errors.append(f'{relative}: missing YAML frontmatter')
            else:
                for key in ('name', 'description'):
                    field = re.search(rf'^{key}:[ \t]*([^\r\n]+)', front.group(1), re.MULTILINE)
                    if not field or field.group(1).strip() in ('', "''", '""', '|', '>'):
                        errors.append(f'{relative}: frontmatter needs a nonempty scalar {key}')
    errors.extend(_readme_contracts(texts))
    if not list((root / 'skills').rglob('SKILL.md')):
        errors.append('skills/: no SKILL.md found')
    try:
        if (root / 'zar/program.md').read_bytes() != (root / 'templates/program.md').read_bytes():
            errors.append('zar/program.md: differs from templates/program.md')
    except OSError as exc:
        errors.append(f'program template: {exc}')
    try:
        project = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']
        if project.get('dependencies', []) or 'dependencies' in project.get('dynamic', []):
            errors.append('pyproject.toml: runtime dependencies must remain empty and static')
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        errors.append(f'pyproject.toml: cannot read project metadata: {exc}')
    try:
        commands = _commands(root)
        for document in ('README.md', 'docs/cli-and-file-contract.md'):
            text = texts.get(document, '')
            snippets = re.findall(r'`([^`\n]+)`', text)
            documented = {re.sub(r'^zar\s+', '', snippet.strip()).split()[0]
                          for snippet in snippets if snippet.strip()}
            for command in sorted(commands - documented):
                errors.append(f'{document}: missing documented CLI command `{command}`')
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        errors.append(f'CLI command coverage: {exc}')
    return errors


def main() -> int:
    errors = validate(Path(__file__).resolve().parents[1])
    if errors:
        for error in errors:
            print(f'ERROR: {error}', file=sys.stderr)
        return 1
    print('Documentation contracts passed (README scope/install, links, template, skill, CLI coverage, runtime dependencies).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
