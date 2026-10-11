"""Export the packaged skill into an explicitly chosen, unused directory."""
from importlib.resources import files
from pathlib import Path


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
