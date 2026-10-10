"""Derived reports preserve source truth and never overwrite user documents."""
from contextlib import redirect_stdout
from decimal import Decimal
import hashlib
import html
import io
from unittest.mock import patch

from test_experiments import ExperimentHarness
from zar.codec import dumps, loads


class ReportTests(ExperimentHarness):
    def write_input(self, document):
        path = self.root / 'input.json'
        path.write_text(dumps(document), encoding='utf-8')
        return path

    @property
    def reports(self):
        return self.stored.parent / 'reports'

    def originals(self):
        return {str(p.relative_to(self.stored.parent)): p.read_bytes()
                for p in self.stored.parent.rglob('*.json')}

    def content(self, path):
        # Generation time is metadata, never an execution observation.
        return '\n'.join(line for line in html.unescape(path.read_text()).splitlines()
                         if not line.startswith('생성 시각:'))

    def report(self, name='summary.md', **kwargs):
        return self.invoke('report', '--output', name, **kwargs)

    def test_empty_report_has_project_marker_and_preserves_originals(self):
        before = self.originals()
        self.report()
        text = self.content(self.reports / 'summary.md')
        project = loads(self.stored.read_text())
        self.assertEqual(text.splitlines()[0],
                         f'<!-- zar-report:v1 project_id={project["id"]} -->')
        self.assertIn('미기록', text)
        self.assertIn(project['next_action'], text)
        self.assertEqual(before, self.originals())

    def test_report_preserves_sources_decimal_evidence_and_unknown(self):
        review = dict(id='review-source', supersedes_id=None, code_ref='code-1',
                      data_ref='data-1', items=[dict(id='scope', topic='change scope',
                      applicability='Synthetic scope', observation='Unverified observation',
                      assessment='unverifiable', evidence=[], limitation='No direct check',
                      next_action='Check source')])
        self.invoke('review', 'add', '--file', str(self.write_input(review)))
        self.register(self.create(review_ids=['review-source']))
        log = self.project / 'recorded.log'
        log.write_text('DO-NOT-INFER-OR-IMPORT-THIS-LOG-CONTENT')
        digest = hashlib.sha256(log.read_bytes()).hexdigest()
        document = self.success(loads(self.record().read_text()))
        exact = '0.123456789012345678901234567890123456789'
        document['execution']['score'] = Decimal(exact)
        document['execution']['evidence'] = [dict(kind='file', ref=log.name,
                                                 locator='line 1', sha256=digest)]
        self.update(document)
        self.register(self.create('unknown-record'))
        unknown = loads(self.record('unknown-record').read_text())
        unknown['execution'].update(status='unknown', note='Outcome was not observed',
                                    evidence=[dict(kind='user_report', ref='Mock operator',
                                                   locator=None, sha256=None)])
        self.invoke('experiment', 'update', 'unknown-record', '--file', str(self.write_input(unknown)))
        review.update(id='review-corrected', supersedes_id='review-source')
        review['items'][0]['observation'] = 'Corrected observation'
        self.invoke('review', 'add', '--file', str(self.write_input(review)))
        before = self.originals()
        self.report()
        text = self.content(self.reports / 'summary.md')
        for value in ('exp-1', 'unknown-record', 'review-source', 'review-corrected',
                      'Unverified observation', 'Corrected observation', exact, 'recorded.log',
                      digest, 'line 1', 'file', '상태 불명', '미기록',
                      'Outcome was not observed', 'No direct check', 'code-1', 'config-1'):
            self.assertIn(value, text)
        self.assertNotIn('DO-NOT-INFER-OR-IMPORT-THIS-LOG-CONTENT', text)
        self.report('second.md')
        self.assertEqual(text, self.content(self.reports / 'second.md'))
        self.assertEqual(before, self.originals())
        self.assertEqual(loads(self.record().read_text())['review_ids'], ['review-source'])

    def test_output_paths_rejected_without_mutation(self):
        before = self.originals()
        for name in (str(self.root / 'outside.md'), '../outside.md',
                     'a/../../outside.md', 'summary.json', '.', 'missing/summary.md'):
            with self.subTest(name=name):
                self.report(name, expected=3)
        self.assertEqual(list(self.reports.iterdir()), [])
        self.assertEqual(before, self.originals())
        self.assertFalse((self.root / 'outside.md').exists())

    def test_submission_and_experiment_corrections_preserve_original_links(self):
        self.register()
        artifact = self.project / 'predictions.csv'
        artifact.write_text('id,prediction\n1,0.5\n')
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        document = self.success(loads(self.record().read_text()))
        document['execution']['artifacts'] = [dict(role='submission', path=artifact.name,
            sha256=digest, code_ref=document['code_ref'], config_ref=document['config_ref'],
            evidence=document['execution']['evidence'])]
        self.update(document)
        submission = dict(id='score-original', supersedes_id=None, experiment_id='exp-1',
            competition='synthetic-competition', external_id='external-score',
            artifact=dict(path=artifact.name, sha256=digest), leaderboard='public',
            metric='external-rmse', direction='minimize', score=Decimal('0.222222222222222222222'),
            submitted_at='2026-01-01T00:02:00Z', observed_at='2026-01-01T00:03:00Z',
            evidence=[dict(kind='user_report', ref='Synthetic external observation',
                           locator=None, sha256=None)])
        self.invoke('submission', 'add', '--file', str(self.write_input(submission)))
        submission.update(id='score-corrected', supersedes_id='score-original',
                          score=Decimal('0.333333333333333333333'))
        self.invoke('submission', 'add', '--file', str(self.write_input(submission)))
        document = loads(self.record().read_text())
        correction = dict(id='exp-corrected', revision=document['revision'],
            execution=document['execution'], reason='Correct synthetic observation',
            evidence=document['execution']['evidence'])
        correction['execution']['score'] = Decimal('1.125')
        self.invoke('experiment', 'correct', 'exp-1', '--file', str(self.write_input(correction)))
        before = self.originals()
        self.report()
        text = self.content(self.reports / 'summary.md')
        for value in ('exp-1', 'exp-corrected', 'score-original', 'score-corrected',
                      'external-score', 'external-rmse', 'synthetic-competition',
                      '0.222222222222222222222', '0.333333333333333333333',
                      'predictions.csv', digest, 'Correct synthetic observation'):
            self.assertIn(value, text)
        self.assertEqual(before, self.originals())
        self.assertEqual(loads((self.stored.parent / 'submissions' /
                               'score-corrected.json').read_text())['experiment_id'], 'exp-1')

    def test_existing_directory_and_output_symlinks_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        victim = outside / 'user.md'
        victim.write_text('user document')
        (self.reports / 'linked').symlink_to(outside, target_is_directory=True)
        (self.reports / 'linked.md').symlink_to(victim)
        (self.reports / 'directory.md').mkdir()
        for name in ('linked/summary.md', 'linked.md', 'directory.md'):
            with self.subTest(name=name):
                self.report(name, expected=3)
                self.invoke('report', '--output', name, '--overwrite', expected=3)
        self.assertEqual(victim.read_text(), 'user document')
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ['user.md'])

    def test_linked_reports_and_store_rejected(self):
        self.reports.rmdir()
        outside = self.root / 'outside-reports'
        outside.mkdir()
        self.reports.symlink_to(outside, target_is_directory=True)
        self.report(expected=3)
        self.assertEqual(list(outside.iterdir()), [])
        self.reports.unlink()
        self.reports.mkdir()
        store = self.stored.parent
        moved = self.root / 'outside-store'
        store.rename(moved)
        store.symlink_to(moved, target_is_directory=True)
        self.report(expected=3)
        self.assertEqual(list((moved / 'reports').iterdir()), [])

    def test_overwrite_requires_same_project_marker_on_first_line(self):
        target = self.reports / 'summary.md'
        project_id = loads(self.stored.read_text())['id']
        for original in ('User document', '<!-- zar-report:v1 project_id=other-project -->\n',
                         f'User header\n<!-- zar-report:v1 project_id={project_id} -->\n'):
            target.write_text(original)
            self.invoke('report', '--output', 'summary.md', '--overwrite', expected=3)
            self.assertEqual(target.read_text(), original)
        target.unlink()
        self.report()
        original = target.read_bytes()
        self.report(expected=3)
        self.assertEqual(target.read_bytes(), original)
        expected_content = self.content(target)
        self.invoke('report', '--output', 'summary.md', '--overwrite')
        self.assertEqual(self.content(target), expected_content)

    def test_preexisting_nested_parent_is_supported(self):
        (self.reports / 'nested').mkdir()
        self.report('nested/summary.md')
        self.assertTrue((self.reports / 'nested/summary.md').is_file())

    def test_corrupt_record_prevents_output(self):
        self.register()
        self.record().write_text('{')
        before = self.originals()
        self.report(expected=2)
        self.assertEqual(list(self.reports.iterdir()), [])
        self.assertEqual(before, self.originals())

    def test_atomic_replace_failure_preserves_original_report_and_records(self):
        self.report()
        target = self.reports / 'summary.md'
        before = target.read_bytes(), self.originals()
        from zar.cli import main
        with patch('zar.storage.os.replace', side_effect=OSError('simulated replace failure')):
            with redirect_stdout(io.StringIO()) as output:
                code = main(['report', '--output', 'summary.md', '--overwrite',
                             '--project', str(self.project), '--json'])
        self.assertEqual(code, 4, output.getvalue())
        self.assertFalse(loads(output.getvalue())['ok'])
        self.assertEqual((target.read_bytes(), self.originals()), before)
        self.assertEqual(sorted(p.name for p in self.reports.iterdir()), ['summary.md'])

    def test_untrusted_markdown_is_inert_and_fractional_elapsed_is_exact(self):
        payload = '<script>alert(1)</script> [click](https://example.invalid) | `code`'
        self.register(self.create(hypothesis=payload))
        document = self.success(loads(self.record().read_text()))
        document['execution'].update(started_at='2026-01-01T23:59:59.999999999999Z',
                                     finished_at='2026-01-02T00:00:00.000000000001Z')
        self.update(document)
        self.report()
        raw = (self.reports / 'summary.md').read_text()
        self.assertNotIn('<script>', raw)
        self.assertNotIn('[click](https://example.invalid)', raw)
        self.assertNotIn('`code`', raw)
        self.assertIn(payload, html.unescape(raw))
        self.assertIn('0.000000000002 초', raw)
