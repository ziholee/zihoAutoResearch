"""Regression checks for the lightweight documentation contract gate."""
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.check_contract import validate

REPO = Path(__file__).resolve().parents[1]


class ContractChecksTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(REPO / 'zar', self.root / 'zar', ignore=shutil.ignore_patterns('__pycache__'))
        for folder in ('docs', 'templates', 'skills/example'):
            (self.root / folder).mkdir(parents=True)
        # Explicit documented command fixture: do not generate expectations from
        # the checker, so a new real command must update this coverage fixture.
        commands = '`skill install` `init` `project set` `status` `check` `review add` `submission add` `memory add` `candidate add` '
        commands += '`research start` `report` `lineage` `experiment create` `git status` `context` `evidence read`\n'
        # Independently authored multilingual declarations and installation fixture.
        self.readmes = {
            'README.md': ('공개', '개발 소스 기능 (미배포)', '에 포함되지 않습니다.'),
            'README.en.md': ('Public', 'Development source features (unreleased)', 'not included in public'),
            'README.ja.md': ('公開版', '開発ソースの機能（未リリース）', 'に含まれません。'),
            'README.zh-CN.md': ('公开版', '开发源码功能（尚未发布）', '不包含在公开版'),
        }
        for guide in ('uv-installation', 'agent-installation', 'first-run-and-resume', 'research-api'):
            self.write(f'docs/{guide}.md', '# Guide\n')
        for name, (label, heading, excluded) in self.readmes.items():
            self.write(name, commands + f'**{label} v0.3.0** Recording CLI.\n'
                + '[Install](docs/uv-installation.md) [Agent](docs/agent-installation.md)\n'
                + '[Resume](docs/first-run-and-resume.md) [Research](docs/research-api.md)\n'
                + '```sh\nuv tool install ziho-autoresearch\nzar --help\n'
                + 'python -m venv .venv\npython -m pip install ziho-autoresearch\n'
                + 'zar skill install --agent codex --project ./my-project\n'
                + 'zar skill install --agent claude --project ./my-project\n```\n'
                + f'## {heading}\n`research` {excluded} v0.3.0\n')
        self.write('docs/cli-and-file-contract.md', commands)
        self.write('skills/example/SKILL.md', '---\nname: example\ndescription: Test skill.\n---\n')
        shutil.copyfile(REPO / 'templates/program.md', self.root / 'templates/program.md')
        shutil.copyfile(REPO / 'pyproject.toml', self.root / 'pyproject.toml')

    def write(self, path, text):
        (self.root / path).write_text(text, encoding='utf-8')

    def append(self, path, text):
        with (self.root / path).open('a', encoding='utf-8') as stream:
            stream.write(text)

    def test_valid_contract(self):
        self.assertEqual(validate(self.root), [])

    def test_missing_local_link(self):
        self.append('README.md', '[missing](docs/missing.md#section)\n')
        errors = validate(self.root)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn('missing local link target: docs/missing.md#section', errors[0])

    def test_all_translations_are_required_and_link_checked(self):
        for name in ('README.en.md', 'README.ja.md', 'README.zh-CN.md'):
            with self.subTest(name=name):
                original = (self.root / name).read_text()
                self.append(name, '[broken](docs/missing.md)\n')
                self.assertTrue(any(name in e and 'missing local link' in e for e in validate(self.root)))
                (self.root / name).unlink()
                self.assertTrue(any(name in e and 'cannot read Markdown' in e for e in validate(self.root)))
                self.write(name, original)

    def test_public_development_and_exclusion_declarations_required(self):
        for name, (label, heading, excluded) in self.readmes.items():
            original = (self.root / name).read_text()
            for removed in (f'**{label} v0.3.0**', f'## {heading}', excluded):
                with self.subTest(name=name, removed=removed):
                    self.write(name, original.replace(removed, ''))
                    self.assertTrue(any(name in e and 'README contract' in e for e in validate(self.root)))
            self.write(name, original)

    def test_versions_must_match_but_not_development_package_version(self):
        name = 'README.ja.md'
        original = (self.root / name).read_text()
        self.write(name, original.replace('v0.3.0', 'v0.2.0'))
        self.assertTrue(any(name in e and 'public version' in e for e in validate(self.root)))
        self.write(name, original.replace('v0.3.0', 'v0.2.0', 1))
        self.assertTrue(any(name in e and 'version' in e for e in validate(self.root)))
        self.write(name, original)
        self.write('pyproject.toml', '[project]\nname="test"\nversion="9.0.0"\ndependencies=[]\n')
        self.assertEqual(validate(self.root), [])

    def test_install_commands_must_be_executable_examples_in_public_scope(self):
        commands = ('uv tool install ziho-autoresearch', 'zar --help', 'python -m venv .venv',
                    'python -m pip install ziho-autoresearch',
                    'zar skill install --agent codex --project ./my-project',
                    'zar skill install --agent claude --project ./my-project')
        for name in self.readmes:
            original = (self.root / name).read_text()
            for command in commands:
                with self.subTest(name=name, command=command):
                    self.write(name, original.replace(command, '# ' + command))
                    self.assertTrue(any(name in e and 'installation command' in e for e in validate(self.root)))
            # Commands moved to development instructions do not document public installation.
            before, development = original.split('## ', 1)
            opening = before.index('```sh')
            self.write(name, before[:opening] + '## ' + development + before[opening:])
            self.assertTrue(any(name in e and 'installation command' in e for e in validate(self.root)))
            self.write(name, original)

    def test_hidden_or_example_declarations_do_not_count(self):
        for wrapper in ('<!-- {} -->', '```md\n{}\n```'):
            original = (self.root / 'README.en.md').read_text()
            declaration = '**Public v0.3.0** Recording CLI.'
            self.write('README.en.md', original.replace(declaration, wrapper.format(declaration)))
            self.assertTrue(any('README.en.md' in e and 'public declaration' in e for e in validate(self.root)))
            self.write('README.en.md', original)

    def test_required_guide_links_cannot_be_only_comments_or_examples(self):
        original = (self.root / 'README.zh-CN.md').read_text()
        for guide in ('uv-installation', 'agent-installation', 'first-run-and-resume', 'research-api'):
            with self.subTest(guide=guide):
                self.write('README.zh-CN.md', original.replace(f'docs/{guide}.md', 'docs/cli-and-file-contract.md')
                           + f'\n<!-- [Hidden](docs/{guide}.md) -->\n')
                self.assertTrue(any('README.zh-CN.md' in e and 'required guide link' in e for e in validate(self.root)))
        self.write('README.zh-CN.md', original)

    def test_unused_reference_definition_does_not_supply_required_guide(self):
        original = (self.root / 'README.en.md').read_text()
        self.write('README.en.md', original.replace('[Install](docs/uv-installation.md)', '')
                   + '\n[unused-install]: docs/uv-installation.md\n')
        self.assertTrue(any('README.en.md' in e and 'required guide link docs/uv-installation.md' in e
                            for e in validate(self.root)))

    def test_harmless_prose_and_shell_whitespace_changes_are_allowed(self):
        for name in self.readmes:
            text = (self.root / name).read_text().replace('Recording CLI.', 'Different localized explanation.')
            text = text.replace('uv tool install ziho-autoresearch', 'uv  tool install "ziho-autoresearch"')
            self.write(name, text)
        self.assertEqual(validate(self.root), [])

    def test_template_drift(self):
        self.append('templates/program.md', '\nChanged template\n')
        self.assertEqual(validate(self.root), ['zar/program.md: differs from templates/program.md'])

    def test_link_spaces_encoding_titles_and_anchors(self):
        self.write('docs/space name.md', '# Heading\n')
        self.append('README.md', '[one](docs/space%20name.md#unchecked-anchor)\n'
                    '[two](<docs/space name.md>)\n'
                    '[three](docs/space%20name.md "A title")\n'
                    '[four](docs/space name.md)\n'
                    '[local](#no-anchor-validation)\n'
                    '[external](https://example.invalid/missing)\n'
                    '[mail](mailto:nobody@example.invalid)\n'
                    '```md\n[example](does-not-exist.md)\n```\n')
        self.assertEqual(validate(self.root), [])

    def test_reference_link_target(self):
        self.append('README.md', '[guide][contract]\n[contract]: docs/missing.md\n')
        self.assertTrue(any('missing local link target' in error for error in validate(self.root)))

    def test_missing_skill_description(self):
        self.write('skills/example/SKILL.md', '---\nname: example\n---\n')
        self.assertTrue(any('nonempty scalar description' in error for error in validate(self.root)))

    def test_machine_local_validator_path(self):
        self.append('skills/example/SKILL.md', 'Run /Users/example/.codex/skills/quick_validate.py\n')
        self.assertTrue(any('machine-local' in error for error in validate(self.root)))

    def test_runtime_dependency(self):
        self.write('pyproject.toml', '[project]\nname = "test"\ndependencies = ["requests"]\n')
        self.assertTrue(any('runtime dependencies' in error for error in validate(self.root)))

    def test_missing_documented_command(self):
        path = self.root / 'docs/cli-and-file-contract.md'
        self.write('docs/cli-and-file-contract.md', path.read_text().replace('`context`', 'context'))
        errors = validate(self.root)
        self.assertEqual(errors, ['docs/cli-and-file-contract.md: missing documented CLI command `context`'])


if __name__ == '__main__':
    unittest.main()
