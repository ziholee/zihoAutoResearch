import json
import os
import unittest
import subprocess

from test_cli import CliHarness


class GitTrackingTests(CliHarness):
    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.project), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def setup_repo(self):
        self.git('init')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.project/'train.py').write_text('# simulated code; never executed\n')
        self.git('add','train.py')
        self.git('commit','-m','fixture code')
        doc=self.ready(self.init())
        self.invoke('project','set','--file',str(self.write_input(doc)))
        return self.git('rev-parse','HEAD')

    def body(self):
        return dict(id='exp-git',kind='baseline',hypothesis='Record committed code',
                    parent_id=None,baseline_id=None,code_ref='placeholder',config_ref='in code commit',
                    command=dict(name='train',argv=['never-execute'],cwd='.'),review_ids=[])

    def test_git_head_creation_links_sha_without_committing(self):
        sha=self.setup_repo()
        result=self.invoke('experiment','create','--git-head','--file',str(self.write_input(self.body())))
        self.assertEqual(result['data']['experiment']['code_ref'], 'git:'+sha)
        self.assertEqual(self.git('rev-parse','HEAD'), sha)
        status=self.invoke('git','status')['data']
        self.assertEqual(status['head'],sha)
        self.assertTrue(status['code_clean'])
        self.assertTrue(status['record_changes'])

    def test_dirty_tracked_and_untracked_code_refused(self):
        self.setup_repo()
        (self.project/'train.py').write_text('# changed\n')
        source=self.write_input(self.body())
        self.invoke('experiment','create','--git-head','--file',str(source),expected=3)
        self.git('add','train.py')
        self.invoke('experiment','create','--git-head','--file',str(source),expected=3)
        self.git('commit','-m','changed fixture')
        (self.project/'new-config.json').write_text('{}')
        self.invoke('experiment','create','--git-head','--file',str(source),expected=3)
        self.assertFalse((self.stored.parent/'experiments/exp-git.json').exists())

    def test_non_git_project_and_unborn_head_report_conflict(self):
        self.init()
        self.invoke('git','status',expected=3)
        self.git('init')
        self.invoke('git','status',expected=3)

    def test_repository_path_with_spaces(self):
        renamed = self.project.with_name('project with spaces')
        self.project.rename(renamed)
        self.project = renamed
        sha = self.setup_repo()
        self.assertEqual(self.invoke('git', 'status')['data']['head'], sha)

    @unittest.skipIf(os.name == 'nt', 'Win32 paths do not preserve trailing spaces')
    def test_repository_path_with_trailing_space(self):
        renamed=self.project.with_name('project with space ')
        self.project.rename(renamed)
        self.project=renamed
        sha=self.setup_repo()
        self.assertEqual(self.invoke('git','status')['data']['head'],sha)

    def test_result_commit_retains_original_code_reference(self):
        sha=self.setup_repo()
        self.invoke('experiment','create','--git-head','--file',str(self.write_input(self.body())))
        record=self.stored.parent/'experiments/exp-git.json'
        doc=json.loads(record.read_text())
        doc['execution'].update(status='running',started_at='2026-01-01T00:00:00Z')
        self.invoke('experiment','update','exp-git','--file',str(self.write_input(doc)))
        self.git('add','.autoresearch/project.json','.autoresearch/program.md','.autoresearch/experiments/exp-git.json')
        self.git('commit','-m','record simulated observation')
        self.assertNotEqual(self.git('rev-parse','HEAD'),sha)
        self.assertEqual(json.loads(record.read_text())['code_ref'],'git:'+sha)
        status=self.invoke('git','status')['data']
        self.assertTrue(status['code_clean'])
        self.assertEqual(status['record_changes'],[])
