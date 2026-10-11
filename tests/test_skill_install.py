"""Skill export contracts: opt-in destination, complete content and preservation."""
import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from test_cli import CliHarness, REPO


class SkillInstallTests(CliHarness):
    def test_exports_whole_skill_without_initializing_project(self):
        destination = self.root / 'my-skill'
        sentinel = self.root / 'AGENTS.md'
        sentinel.write_bytes(b'user instructions\n')
        result = self.cli('skill', 'install', '--dest', destination.name, '--json')
        source = REPO / 'skills/ziho-autoresearch'
        expected = {p.relative_to(source).as_posix(): p.read_bytes()
                    for p in source.rglob('*') if p.is_file()}
        actual = {p.relative_to(destination).as_posix(): p.read_bytes()
                  for p in destination.rglob('*') if p.is_file()}
        self.assertEqual(actual, expected)
        self.assertIn('SKILL.md', actual)
        self.assertIn('references/cli-recipes.md', actual)
        reported = Path(result['data']['destination'])
        self.assertTrue(reported.is_absolute())
        self.assertTrue(reported.samefile(destination))
        self.assertEqual(result['data']['files'], sorted(expected))
        self.assertEqual(sentinel.read_bytes(), b'user instructions\n')
        self.assertFalse((self.root / '.autoresearch').exists())
        self.assertFalse((self.root / '.agents').exists())

    def test_requires_explicit_destination(self):
        self.cli('skill', 'install', '--json', expected=2)
        self.cli('skill', 'install', '--dest', '', '--json', expected=2)
        self.assertEqual(list(self.root.iterdir()), [self.project])

    def test_refuses_existing_files_directories_and_symlinks(self):
        file = self.root / 'file'
        file.write_bytes(b'user bytes')
        empty = self.root / 'empty'
        empty.mkdir()
        occupied = self.root / 'occupied'
        occupied.mkdir()
        (occupied / 'SKILL.md').write_bytes(b'user skill')
        targets = [file, empty, occupied]
        for name, target in [('linked', occupied), ('dangling', self.root / 'absent')]:
            link = self.root / name
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                continue  # Windows may not grant symlink privileges.
            targets.append(link)
        for target in targets:
            with self.subTest(target=target):
                result = self.cli('skill', 'install', '--dest', str(target), '--json', expected=3)
                self.assertEqual(result['diagnostics'][0]['code'], 'conflict')
        self.assertEqual(file.read_bytes(), b'user bytes')
        self.assertEqual(list(empty.iterdir()), [])
        self.assertEqual((occupied / 'SKILL.md').read_bytes(), b'user skill')
        self.assertFalse((self.root / 'absent').exists())

    def test_missing_parent_does_not_create_ancestors(self):
        parent = self.root / 'missing'
        self.cli('skill', 'install', '--dest', str(parent / 'skill'), '--json', expected=4)
        self.assertFalse(parent.exists())

    def test_copy_failure_removes_only_own_writes(self):
        from zar.cli import main
        destination = self.root / 'failed'
        sentinel = self.root / 'user.txt'
        sentinel.write_bytes(b'preserve')
        original = Path.open
        writes = 0

        def fail_second_write(path, mode='r', *args, **kwargs):
            nonlocal writes
            if mode == 'xb':
                writes += 1
                if writes == 2:
                    raise OSError('injected write failure')
            return original(path, mode, *args, **kwargs)

        stdout = io.StringIO()
        with patch.object(Path, 'open', fail_second_write), contextlib.redirect_stdout(stdout):
            code = main(['skill', 'install', '--dest', str(destination), '--json'])
        self.assertEqual(code, 4)
        self.assertFalse(json.loads(stdout.getvalue())['ok'])
        self.assertFalse(destination.exists())
        self.assertEqual(sentinel.read_bytes(), b'preserve')

    def test_failed_copy_preserves_unexpected_files_added_by_another_writer(self):
        from zar.cli import main
        destination = self.root / 'shared'
        original = Path.open

        def concurrent_failure(path, mode='r', *args, **kwargs):
            if mode == 'xb':
                (destination / 'user.txt').write_bytes(b'other writer')
                raise OSError('injected concurrent write')
            return original(path, mode, *args, **kwargs)

        with patch.object(Path, 'open', concurrent_failure), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['skill', 'install', '--dest', str(destination), '--json']), 4)
        self.assertEqual(list(destination.iterdir()), [destination / 'user.txt'])
        self.assertEqual((destination / 'user.txt').read_bytes(), b'other writer')
