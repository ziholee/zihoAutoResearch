#!/usr/bin/env python3
"""Check repository documentation contracts using only the Python standard library.

This checks file links, not Markdown anchor spelling or the truth of prose claims.
It never runs an ML command or contacts a remote service.
"""
from __future__ import annotations

import re
from pathlib import Path
import subprocess
import sys
import tomllib
from urllib.parse import unquote, urlsplit


# Inline links (including images) and explicit reference-link definitions.
_LINK = re.compile(r'\]\(\s*(<[^>\n]+>|(?:[^()\n]|\([^()\n]*\))+)\s*\)')
_REFERENCE = re.compile(r'^ {0,3}\[[^]\n]+\]:\s*(<[^>\n]+>|\S+)', re.MULTILINE)
_LOCAL_HOME = re.compile(r'(?:/(?:Users|home)/[^\s/]+/|[A-Za-z]:[\\/]Users[\\/]|~[/\\]\.(?:codex|agents)[/\\])')


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
    markdown = {root / 'README.md'}
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
        prose = _without_fences(text)
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
    print('Documentation contracts passed (links, template, skill, CLI coverage, runtime dependencies).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
