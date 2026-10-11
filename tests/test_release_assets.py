"""Failure-oriented checks for the read-only gate before PyPI publication."""
import copy
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
_spec = importlib.util.spec_from_file_location('verify_release_assets', SCRIPTS / 'verify_release_assets.py')
assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(assets)
sys.path.remove(str(SCRIPTS))
TAG = 'v0.2.0'
WHEEL = 'ziho_autoresearch-0.2.0-py3-none-any.whl'
SDIST = 'ziho_autoresearch-0.2.0.tar.gz'


class ReleaseAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dist = self.root / 'assets'
        self.dist.mkdir()
        (self.dist / WHEEL).write_bytes(b'wheel bytes')
        (self.dist / SDIST).write_bytes(b'source bytes')
        self.checksums()
        self.release = dict(id=20, tag_name=TAG, draft=False, prerelease=False,
                            published_at='2026-10-11T00:00:00Z',
                            assets=[dict(id=i, name=name, state='uploaded')
                                    for i, name in enumerate(sorted(assets.expected_assets(TAG)), 1)])

    def checksums(self):
        (self.dist / 'SHA256SUMS').write_text(''.join(
            f'{hashlib.sha256((self.dist / name).read_bytes()).hexdigest()}  {name}\n'
            for name in (WHEEL, SDIST)))

    def test_valid_release_and_checksums(self):
        self.assertEqual(len(assets.validate_release(self.release, TAG, 20)), 3)
        self.assertEqual({p.name for p in assets.verify_checksums(self.dist, TAG)}, {WHEEL, SDIST})

    def test_reject_unstable_or_noncanonical_tags(self):
        for tag in ('v0.2.0rc1', 'v0.2.0.dev1', 'v0.2.0+local', '0.2.0', 'v00.2.0', '../v0.2.0', 'dev'):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                assets.expected_assets(tag)

    def test_release_identity_and_state(self):
        for field, value in (('tag_name', 'v0.1.0'), ('draft', True), ('prerelease', True),
                             ('published_at', None), ('id', 21)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                assets.validate_release({**self.release, field: value}, TAG, 20)

    def test_release_asset_inventory(self):
        for mutation in ('missing', 'extra', 'duplicate', 'unsafe', 'pending', 'duplicate-id'):
            release = copy.deepcopy(self.release)
            if mutation == 'missing':
                release['assets'].pop()
            elif mutation == 'extra':
                release['assets'].append(dict(id=100, name='extra.txt', state='uploaded'))
            elif mutation == 'duplicate':
                release['assets'][0]['name'] = release['assets'][1]['name']
            elif mutation == 'unsafe':
                release['assets'][0]['name'] = '../SHA256SUMS'
            elif mutation == 'pending':
                release['assets'][0]['state'] = 'new'
            else:
                release['assets'][0]['id'] = release['assets'][1]['id']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                assets.validate_release(release, TAG)

    def test_malformed_checksum_entries(self):
        original = (self.dist / 'SHA256SUMS').read_text()
        for value in (original + original.splitlines()[0] + '\n',
                      original.replace(WHEEL, '../' + WHEEL),
                      original.replace(WHEEL, '/tmp/' + WHEEL),
                      original.replace(WHEEL, 'folder\\' + WHEEL),
                      original.replace('  ', ' '), original.replace(WHEEL, 'SHA256SUMS'),
                      original.splitlines()[0] + '\n', original + '\n'):
            (self.dist / 'SHA256SUMS').write_text(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                assets.verify_checksums(self.dist, TAG)

    def test_corrupt_missing_and_extra_assets(self):
        (self.dist / WHEEL).write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
            assets.verify_checksums(self.dist, TAG)
        self.checksums()
        extra = self.dist / 'extra.txt'
        extra.write_text('extra')
        with self.assertRaisesRegex(ValueError, 'Missing or extra'):
            assets.verify_checksums(self.dist, TAG)
        extra.unlink()
        wheel = self.dist / WHEEL
        wheel.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing or extra'):
            assets.verify_checksums(self.dist, TAG)

    @unittest.skipIf(os.name == 'nt', 'Symlink creation requires Windows privileges')
    def test_reject_symlink_assets(self):
        wheel = self.dist / WHEEL
        wheel.unlink()
        wheel.symlink_to(self.dist / SDIST)
        with self.assertRaisesRegex(ValueError, 'regular files'):
            assets.verify_checksums(self.dist, TAG)

    def source_fixture(self, *, wheel_bytes=b'original', source_bytes=b'original', extra_wheel=None):
        checkout = self.root / 'checkout'
        checkout.mkdir(exist_ok=True)
        (checkout / 'zar').mkdir(exist_ok=True)
        (checkout / 'zar/__init__.py').write_bytes(b'original')
        (checkout / 'pyproject.toml').write_text('[project]\nname="ziho-autoresearch"\nversion="0.2.0"\n')
        subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
        subprocess.run(['git', '-C', str(checkout), 'add', '.'], check=True)
        with tarfile.open(self.dist / SDIST, 'w:gz') as archive:
            for name, data in [('zar/__init__.py', source_bytes),
                               ('pyproject.toml', (checkout / 'pyproject.toml').read_bytes())]:
                member = tarfile.TarInfo('ziho_autoresearch-0.2.0/' + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        with zipfile.ZipFile(self.dist / WHEEL, 'w') as wheel:
            wheel.writestr('zar/__init__.py', wheel_bytes)
            if extra_wheel:
                wheel.writestr(extra_wheel, b'bad')
        return checkout

    def test_source_and_wheel_agree_with_tagged_source(self):
        checkout = self.source_fixture()
        with patch.object(assets, 'verify_release_metadata') as metadata:
            assets.verify_source(self.dist / WHEEL, self.dist / SDIST, checkout, TAG)
            metadata.assert_called_once()

    def test_reject_source_drift_before_package_execution(self):
        checkout = self.source_fixture(source_bytes=b'changed')
        with patch.object(assets, 'verify_release_metadata') as metadata:
            with self.assertRaisesRegex(ValueError, 'Source drift'):
                assets.verify_source(self.dist / WHEEL, self.dist / SDIST, checkout, TAG)
            metadata.assert_not_called()

    def test_reject_wheel_drift(self):
        checkout = self.source_fixture(wheel_bytes=b'changed')
        with self.assertRaisesRegex(ValueError, 'Wheel source drift'):
            assets.verify_source(self.dist / WHEEL, self.dist / SDIST, checkout, TAG)

    def test_reject_wheel_extra_or_unsafe_path(self):
        for name in ('other.py', '../zar/extra.py', '/zar/extra.py'):
            checkout = self.source_fixture(extra_wheel=name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                assets.verify_source(self.dist / WHEEL, self.dist / SDIST, checkout, TAG)

    def test_reject_tag_version_mismatch(self):
        checkout = self.source_fixture()
        with self.assertRaisesRegex(ValueError, 'Tag and source version differ'):
            assets.verify_source(self.dist / WHEEL, self.dist / SDIST, checkout, 'v0.3.0')


if __name__ == '__main__':
    unittest.main()
