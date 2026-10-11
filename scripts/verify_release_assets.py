#!/usr/bin/env python3
"""Validate the exact public release assets before the separate OIDC publish job."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile

from verify_package import require, unpack_source, verify_release_metadata


STABLE_TAG = re.compile(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)')


def expected_assets(tag: str) -> set[str]:
    require(STABLE_TAG.fullmatch(tag) is not None, 'Only stable vMAJOR.MINOR.PATCH tags are allowed')
    version = tag[1:]
    return {f'ziho_autoresearch-{version}-py3-none-any.whl',
            f'ziho_autoresearch-{version}.tar.gz', 'SHA256SUMS'}


def validate_release(release: dict, tag: str, release_id: int | None = None) -> list[dict]:
    expected = expected_assets(tag)
    require(release.get('tag_name') == tag, 'Release tag does not match requested tag')
    require(release.get('draft') is False and release.get('prerelease') is False
            and bool(release.get('published_at')), 'Release must be published and stable')
    require(type(release.get('id')) is int and release['id'] > 0, 'Invalid release ID')
    if release_id is not None:
        require(release['id'] == release_id, 'Release ID changed since publication event')
    assets = release.get('assets', [])
    require(isinstance(assets, list) and len(assets) == len(expected), 'Unexpected release asset count')
    require({asset.get('name') for asset in assets} == expected, 'Missing, extra or duplicate release assets')
    ids = [asset.get('id') for asset in assets]
    require(all(type(value) is int and value > 0 for value in ids) and len(set(ids)) == len(ids),
            'Invalid or duplicate release asset IDs')
    require(all(asset.get('state') == 'uploaded' for asset in assets), 'Release assets are not fully uploaded')
    return assets


def verify_checksums(directory: Path, tag: str) -> list[Path]:
    expected = expected_assets(tag)
    entries = list(directory.iterdir())
    require({path.name for path in entries} == expected, 'Missing or extra downloaded release assets')
    require(all(path.is_file() and not path.is_symlink() for path in entries), 'Assets must be regular files')
    hashes = {}
    for line in (directory / 'SHA256SUMS').read_text(encoding='ascii').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        require(match is not None, 'Malformed or unsafe checksum entry')
        digest, name = match.groups()
        require(name in expected - {'SHA256SUMS'}, 'Unexpected checksum filename')
        require(name not in hashes, 'Duplicate checksum filename')
        hashes[name] = digest
    require(set(hashes) == expected - {'SHA256SUMS'}, 'Missing distribution checksum')
    distributions = [directory / name for name in sorted(hashes)]
    for path in distributions:
        require(hashlib.sha256(path.read_bytes()).hexdigest() == hashes[path.name],
                f'Checksum mismatch: {path.name}')
    return distributions


def verify_source(wheel: Path, archive: Path, checkout: Path, tag: str) -> None:
    project = tomllib.loads((checkout / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    require(project['version'] == tag[1:], 'Tag and source version differ')
    require(project['name'] == 'ziho-autoresearch', 'Unexpected project name')
    tracked = subprocess.check_output(['git', '-C', str(checkout), 'ls-files', '-z']).decode().split('\0')
    tracked = {name for name in tracked if name}
    with tempfile.TemporaryDirectory(prefix='zar-release-assets-') as temporary:
        source = unpack_source(archive, Path(temporary) / 'source')
        require(source.name == f'ziho_autoresearch-{tag[1:]}', 'Source archive root differs from tag')
        # Compare all shipped tracked files, including examples executed by package verification.
        for path in source.rglob('*'):
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            if relative in tracked:
                require(not (checkout / relative).is_symlink(), f'Tracked symlink is unsupported: {relative}')
                require(path.read_bytes() == (checkout / relative).read_bytes(), f'Source drift: {relative}')
            else:
                require(relative == 'PKG-INFO' or relative == 'setup.cfg'
                        or relative in {f'ziho_autoresearch.egg-info/{name}' for name in
                                        ('PKG-INFO', 'SOURCES.txt', 'dependency_links.txt',
                                         'entry_points.txt', 'top_level.txt')},
                        f'Unexpected untracked source file: {relative}')
        generated_config = source / 'setup.cfg'
        if generated_config.is_file() and 'setup.cfg' not in tracked:
            require(generated_config.read_bytes() == b'[egg_info]\ntag_build = \ntag_date = 0\n\n',
                    'Unexpected generated setup.cfg')
        # The distribution must include the complete runtime package from the tag.
        package = {name: name for name in tracked
                   if name.startswith('zar/') and (checkout / name).is_file()}
        skill_prefix = 'skills/ziho-autoresearch/'
        package.update({'zar/_bundled_skill/' + name[len(skill_prefix):]: name
                        for name in tracked if name.startswith(skill_prefix)
                        and (checkout / name).is_file()})
        require(bool(package), 'Source checkout has no runtime package')
        for name in package.values():
            require((source / name).is_file(), f'Source distribution is missing {name}')
        with zipfile.ZipFile(wheel) as bundle:
            names = bundle.namelist()
            require(len(names) == len(set(names)), 'Duplicate wheel archive paths')
            for name in names:
                path = PurePosixPath(name)
                require(not path.is_absolute() and '..' not in path.parts and '\\' not in name
                        and ':' not in name, f'Unsafe wheel path: {name}')
                require(name in package or name.startswith(f'ziho_autoresearch-{tag[1:]}.dist-info/'),
                        f'Unexpected wheel file: {name}')
            require({name for name in names if name.startswith('zar/')} == set(package),
                    'Wheel runtime package differs from tagged source')
            for name, relative in package.items():
                require(bundle.read(name) == (checkout / relative).read_bytes(), f'Wheel source drift: {name}')
            if project.get('scripts'):
                entry_points = '[console_scripts]\n' + ''.join(
                    f'{key} = {value}\n' for key, value in sorted(project['scripts'].items()))
                require(bundle.read(f'ziho_autoresearch-{tag[1:]}.dist-info/entry_points.txt')
                        == entry_points.encode(), 'Wheel entry points differ from tagged project')
                require((source / 'ziho_autoresearch.egg-info/entry_points.txt').read_bytes()
                        == entry_points.encode(), 'Source entry points differ from tagged project')
        verify_release_metadata(wheel, source, checkout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--release-json', type=Path, required=True)
    parser.add_argument('--release-id', type=int)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    assets = validate_release(json.loads(args.release_json.read_text()), args.tag, args.release_id)
    if args.download:
        args.assets.mkdir(parents=True, exist_ok=False)
        for asset in assets:
            with (args.assets / asset['name']).open('xb') as output:
                subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream',
                                f"repos/ziholee/zihoAutoResearch/releases/assets/{asset['id']}"],
                               stdout=output, check=True)
    distributions = verify_checksums(args.assets, args.tag)
    wheel = next(path for path in distributions if path.suffix == '.whl')
    source = next(path for path in distributions if path.name.endswith('.tar.gz'))
    verify_source(wheel, source, args.checkout, args.tag)
    args.output.mkdir(parents=True, exist_ok=False)
    for path in distributions:
        shutil.copyfile(path, args.output / path.name)
    print('PASS: stable release identity, exact assets, checksums, metadata and tagged source')


if __name__ == '__main__':
    main()
