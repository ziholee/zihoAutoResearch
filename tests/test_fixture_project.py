"""Exercise check with the documented simulated experiment history."""
import json
from pathlib import Path
import shutil

from test_cli import CliHarness, REPO


class FixtureProjectTests(CliHarness):
    def prepare_fixture(self):
        self.init()
        source = REPO / 'examples/contract-v1'
        shutil.copytree(source / 'logs', self.project / 'logs')
        shutil.copyfile(source / 'submission-example.txt', self.project / 'submission-example.txt')
        shutil.copyfile(source / 'project.json', self.stored)
        for filename, kind in [('review', 'reviews'), ('baseline', 'experiments'),
                               ('candidate', 'experiments'), ('submission', 'submissions')]:
            doc = json.loads((source / (filename + '.json')).read_text())
            shutil.copyfile(source / (filename + '.json'), self.stored.parent / kind / (doc['id'] + '.json'))

    def test_fixture_history_checks_and_reports_selection(self):
        self.prepare_fixture()
        result = self.invoke('check')
        self.assertEqual(result['data']['selected_experiment_id'], 'exp-baseline')
        self.assertEqual(result['data']['last_experiment_id'], 'exp-candidate')

    def test_changed_submission_is_a_conflict(self):
        self.prepare_fixture()
        (self.project / 'submission-example.txt').write_text('changed')
        self.invoke('check', expected=3)

    def test_missing_evidence_is_a_warning(self):
        self.prepare_fixture()
        (self.project / 'logs/baseline.txt').unlink()
        result = self.invoke('check')
        self.assertTrue(any(d['severity'] == 'warning' for d in result['diagnostics']))
