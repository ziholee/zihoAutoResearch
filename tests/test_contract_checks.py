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
        commands = '`init` `project set` `status` `check` `review add` `submission add` '
        commands += '`report` `experiment create` `git status` `context` `evidence read`\n'
        self.write('README.md', commands)
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
