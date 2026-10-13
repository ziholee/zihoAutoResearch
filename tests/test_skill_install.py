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


class SkillGuidanceTests(CliHarness):
    def test_guidance_preserves_project_and_skill_and_handles_markdown_path(self):
        destination = self.root / '한글 skill ` [notes]'
        self.cli('skill', 'install', '--dest', str(destination), '--json')
        sentinel = self.root / 'AGENTS.md'
        sentinel.write_bytes(b'existing instructions\n')
        before = {p.relative_to(self.root): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file()}
        result = self.cli('skill', 'guidance', '--skill-dir', destination.name,
                          '--project', 'does-not-exist', '--json')['data']
        self.assertEqual(result['view'], 'skill_guidance')
        self.assertTrue(Path(result['skill_file']).samefile(destination / 'SKILL.md'))
        self.assertIn('`` ' + result['skill_file'] + ' ``', result['markdown'])
        for phrase in ('zar context', 'zar status', 'unknown', 'zar check', 'budget'):
            self.assertIn(phrase, result['markdown'])
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes()
                                 for p in self.root.rglob('*') if p.is_file()})
        self.assertFalse((self.root / '.autoresearch').exists())
        self.assertFalse((self.root / 'does-not-exist').exists())

    def test_text_output_is_the_same_markdown(self):
        from zar.cli import main
        destination = self.root / 'skill'
        self.cli('skill', 'install', '--dest', str(destination), '--json')
        expected = self.cli('skill', 'guidance', '--skill-dir', str(destination), '--json')['data']
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['skill', 'guidance', '--skill-dir', str(destination)])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), expected['markdown'])

    def test_requires_explicit_valid_skill_directory(self):
        self.cli('skill', 'guidance', '--json', expected=2)
        for value in ('', '   ', 'bad\npath', 'bad\tpath', 'bad\x01path', 'bad\u2028path'):
            self.cli('skill', 'guidance', '--skill-dir', value,
                     '--json', expected=2)
        for destination in (self.root / 'absent', self.project):
            result = self.cli('skill', 'guidance', '--skill-dir', str(destination),
                              '--json', expected=4)
            self.assertEqual(result['diagnostics'][0]['code'], 'io')
        (self.project / 'SKILL.md').mkdir()
        self.cli('skill', 'guidance', '--skill-dir', str(self.project), '--json', expected=4)


    def test_unresolvable_home_returns_json_argument_error(self):
        from zar.cli import main
        output = io.StringIO()
        with patch.object(Path, 'expanduser', side_effect=RuntimeError('unknown home')), \
                contextlib.redirect_stdout(output):
            code = main(['skill', 'guidance', '--skill-dir', '~missing/skill', '--json'])
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertFalse(result['ok'])
        self.assertEqual(result['diagnostics'][0]['code'], 'arguments')


class AgentSkillInstallTests(CliHarness):
    def test_project_install_for_both_agents_preserves_instructions(self):
        expected = {p.relative_to(REPO / 'skills/ziho-autoresearch').as_posix(): p.read_bytes()
                    for p in (REPO / 'skills/ziho-autoresearch').rglob('*') if p.is_file()}
        for name in ('AGENTS.md', 'CLAUDE.md'):
            (self.project / name).write_bytes(b'original rules')
        for agent, directory, invocation in (
                ('codex', '.agents', '$ziho-autoresearch'),
                ('claude', '.claude', '/ziho-autoresearch')):
            data = self.invoke('skill', 'install', '--agent', agent)['data']
            destination = self.project / directory / 'skills/ziho-autoresearch'
            self.assertTrue(Path(data['destination']).samefile(destination))
            self.assertEqual(data['scope'], 'project')
            self.assertEqual(data['invocation'], invocation)
            self.assertFalse(data['dry_run'])
            self.assertEqual(expected, {p.relative_to(destination).as_posix(): p.read_bytes()
                                        for p in destination.rglob('*') if p.is_file()})
            self.invoke('skill', 'install', '--agent', agent, expected=3)
        for name in ('AGENTS.md', 'CLAUDE.md'):
            self.assertEqual((self.project / name).read_bytes(), b'original rules')
        self.assertFalse((self.project / '.autoresearch').exists())

    def test_preview_creates_nothing_and_missing_project_is_not_created(self):
        before = list(self.project.iterdir())
        data = self.invoke('skill', 'install', '--agent', 'codex', '--dry-run')['data']
        self.assertTrue(data['dry_run'])
        self.assertEqual(list(self.project.iterdir()), before)
        self.cli('skill', 'install', '--agent', 'codex', '--project', str(self.root / 'absent'),
                 '--json', expected=4)
        self.assertFalse((self.root / 'absent').exists())

    def test_user_install_uses_home_and_does_not_touch_project(self):
        from zar.cli import main
        for agent, directory in (('codex', '.agents'), ('claude', '.claude')):
            output = io.StringIO()
            with patch.object(Path, 'home', return_value=self.root), contextlib.redirect_stdout(output):
                code = main(['skill', 'install', '--agent', agent, '--scope', 'user', '--json'])
            self.assertEqual(code, 0)
            data = json.loads(output.getvalue())['data']
            self.assertEqual(data['scope'], 'user')
            self.assertTrue((self.root / directory / 'skills/ziho-autoresearch/SKILL.md').is_file())
        self.assertEqual(list(self.project.iterdir()), [])

    def test_option_conflicts_and_invalid_paths_do_not_write(self):
        for args in (('--dest', 'new', '--agent', 'codex'),
                     ('--dest', 'new', '--scope', 'user'),
                     ('--dest', 'new', '--dry-run'),
                     ('--agent', 'other'), ('--agent', 'codex', '--scope', 'other'),
                     ('--agent', 'codex', '--project', 'bad\npath')):
            self.cli('skill', 'install', *args, '--json', expected=2)
        self.assertEqual(list(self.root.iterdir()), [self.project])

    def test_parent_files_and_symlinks_are_rejected_without_following(self):
        parent = self.project / '.agents'
        parent.write_bytes(b'preserve')
        self.invoke('skill', 'install', '--agent', 'codex', expected=3)
        self.assertEqual(parent.read_bytes(), b'preserve')
        parent.unlink()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        try:
            parent.symlink_to(elsewhere, target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        self.invoke('skill', 'install', '--agent', 'codex', expected=3)
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_copy_failure_cleans_only_created_parents(self):
        from zar.cli import main
        with patch('zar.skill_install.install_skill', side_effect=OSError('copy failed')), \
                contextlib.redirect_stdout(io.StringIO()):
            code = main(['skill', 'install', '--agent', 'codex', '--project', str(self.project), '--json'])
        self.assertEqual(code, 4)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_unresolvable_home_is_json_error(self):
        from zar.cli import main
        output = io.StringIO()
        with patch.object(Path, 'home', side_effect=RuntimeError('unknown home')), \
                contextlib.redirect_stdout(output):
            code = main(['skill', 'install', '--agent', 'codex', '--scope', 'user', '--json'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())['diagnostics'][0]['code'], 'arguments')


    def test_failure_preserves_existing_parent_and_concurrent_file(self):
        from zar.cli import main
        parent = self.project / '.agents'
        parent.mkdir()

        def failure(destination):
            (destination.parent / 'other.txt').write_bytes(b'another writer')
            raise OSError('copy failed')

        with patch('zar.skill_install.install_skill', side_effect=failure), \
                contextlib.redirect_stdout(io.StringIO()):
            code = main(['skill', 'install', '--agent', 'codex', '--project', str(self.project), '--json'])
        self.assertEqual(code, 4)
        self.assertEqual((parent / 'skills/other.txt').read_bytes(), b'another writer')

    def test_destination_and_nested_parent_symlinks_are_not_followed(self):
        parent = self.project / '.agents'
        parent.mkdir()
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        link = parent / 'skills'
        try:
            link.symlink_to(elsewhere, target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        self.invoke('skill', 'install', '--agent', 'codex', '--dry-run', expected=3)
        link.unlink()
        link.mkdir()
        destination = link / 'ziho-autoresearch'
        destination.symlink_to(self.root / 'missing', target_is_directory=True)
        self.invoke('skill', 'install', '--agent', 'codex', expected=3)
        self.assertTrue(destination.is_symlink())
        self.assertFalse((self.root / 'missing').exists())
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_text_output_explains_invocation_and_preview(self):
        from zar.cli import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['skill', 'install', '--agent', 'claude', '--project', str(self.project), '--dry-run'])
        self.assertEqual(code, 0)
        self.assertIn('preview', output.getvalue())
        self.assertIn('/ziho-autoresearch', output.getvalue())
        self.assertIn('restart', output.getvalue())
        self.assertEqual(list(self.project.iterdir()), [])


    def test_windows_reparse_parent_is_rejected_without_is_junction_api(self):
        import stat
        from types import SimpleNamespace
        from zar.cli import main
        parent = self.project.resolve() / '.agents'
        parent.mkdir()
        original = Path.lstat

        def reparse_info(path, *args, **kwargs):
            if path == parent:
                return SimpleNamespace(st_mode=stat.S_IFDIR,
                                       st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return original(path, *args, **kwargs)

        output = io.StringIO()
        with patch.object(Path, 'lstat', reparse_info), contextlib.redirect_stdout(output):
            code = main(['skill', 'install', '--agent', 'codex', '--project', str(self.project), '--json'])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(output.getvalue())['diagnostics'][0]['code'], 'conflict')
        self.assertEqual(list(parent.iterdir()), [])
