"""Read-only Git identity and working-tree inspection."""
import os
from pathlib import Path
import subprocess


class GitStateError(Exception):
    pass


def snapshot(root):
    root = Path(root).resolve()
    env = os.environ.copy()
    for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR', 'GIT_OBJECT_DIRECTORY',
                 'GIT_ALTERNATE_OBJECT_DIRECTORIES'):
        env.pop(name, None)

    def git(*args):
        try:
            result = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                                     '-C', str(root), *args], env=env, capture_output=True, timeout=15)
        except subprocess.TimeoutExpired as exc:
            raise GitStateError('Git inspection timed out.') from exc
        if result.returncode:
            raise GitStateError(result.stderr.decode('utf-8', errors='replace').strip() or 'Git inspection failed.')
        return result.stdout

    top = Path(os.fsdecode(git('rev-parse', '--show-toplevel').removesuffix(b'\n'))).resolve()
    head = git('rev-parse', '--verify', 'HEAD^{commit}').decode('ascii').strip()
    prefix = root.relative_to(top).as_posix()
    prefix = '' if prefix == '.' else prefix + '/'
    metadata = prefix + '.autoresearch/'
    transient = prefix + '.autoresearch.init.lock'
    code_changes, record_changes = [], []
    entries = git('status', '--porcelain=v1', '-z', '--untracked-files=all',
                  '--ignore-submodules=none', '--no-renames').split(b'\0')
    for entry in entries:
        if not entry:
            continue
        status = entry[:2].decode('ascii')
        path = entry[3:].decode('utf-8', errors='replace')
        if path in (transient, metadata + '.lock'):
            continue
        change = {'status': status, 'path': path}
        (record_changes if path.startswith(metadata) else code_changes).append(change)
    if git('rev-parse', '--verify', 'HEAD^{commit}').decode('ascii').strip() != head:
        raise GitStateError('HEAD changed during inspection; retry after Git activity finishes.')
    return dict(repository=str(top), head=head, code_ref='git:' + head,
                code_clean=not code_changes, code_changes=code_changes, record_changes=record_changes)
