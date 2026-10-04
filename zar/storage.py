"""Cooperative locks and same-filesystem atomic replacement."""
from contextlib import contextmanager
import os
import stat
from pathlib import Path
import tempfile


def atomic_write(path: Path, text: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix='.zar-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def project_lock(store: Path):
    lock = store / '.lock'
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()
