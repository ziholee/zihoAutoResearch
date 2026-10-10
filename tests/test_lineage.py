"""Public lineage reads preserve canonical records and separate correction from runs."""
import contextlib
import io
import json
from unittest.mock import patch
from test_experiments import ExperimentHarness
from zar.cli import main


class LineageTests(ExperimentHarness):
    def originals(self):
        return {p: p.read_bytes() for p in self.stored.parent.rglob('*.json')}

    def test_empty_and_legacy_graph(self):
        for directory in ('memories', 'candidates'):
            (self.stored.parent / directory).rmdir()
        before = self.originals()
        data = self.invoke('lineage')['data']
        self.assertEqual(data['nodes'], [])
        self.assertEqual(data['edges'], [])
        self.assertEqual(data['counts']['execution_count'], 0)
        self.assertEqual(before, self.originals())

    def test_original_edges_correction_counts_and_read_only_metadata(self):
        self.register()
        doc = self.success(json.loads(self.record().read_text()))
        self.update(doc)
        self.register(self.create('child', parent_id='exp-1', baseline_id='exp-1', kind='performance'))
        original = json.loads(self.record().read_text())
        correction = dict(id='fixed', revision=original['revision'], execution=original['execution'],
                          reason='Correct synthetic score', evidence=original['execution']['evidence'])
        correction['execution']['score'] = 1.2
        self.invoke('experiment', 'correct', 'exp-1', '--file', str(self.write_input(correction)))
        before = self.originals()
        graph = self.invoke('lineage')['data']
        self.assertEqual(graph, self.invoke('lineage')['data'])
        self.assertEqual(graph['counts']['record_count'], 3)
        self.assertEqual(graph['counts']['execution_count'], 2)
        self.assertEqual({(e['type'], e['source'], e['target']) for e in graph['edges']},
                         {('parent', 'exp-1', 'child'), ('baseline', 'exp-1', 'child'), ('correction', 'exp-1', 'fixed')})
        self.assertTrue(all(e['source_superseded'] for e in graph['edges']))
        nodes = {n['id']: n for n in graph['nodes']}
        self.assertEqual(nodes['exp-1']['active_record_id'], 'fixed')
        self.assertEqual(nodes['child']['parent_id'], 'exp-1')
        self.assertEqual(nodes['child']['code_ref'], 'code-1')
        self.assertEqual(before, self.originals())
        output = io.StringIO()
        with patch('hashlib.file_digest', side_effect=AssertionError('No evidence hashing')), \
             patch('zar.cli.inspect_git', side_effect=AssertionError('No Git lookup')), contextlib.redirect_stdout(output):
            self.assertEqual(main(['lineage', '--project', str(self.project), '--format', 'mermaid', '--json']), 0)
        self.assertTrue(json.loads(output.getvalue())['data']['mermaid'].startswith('flowchart'))

    def test_human_diagnostics_do_not_corrupt_graph_output(self):
        self.register()
        self.update(self.success(json.loads(self.record().read_text())))
        for format in ('json', 'mermaid'):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(main(['lineage', '--project', str(self.project), '--format', format]), 0)
            self.assertIn('warning:', err.getvalue())
            self.assertNotIn('warning:', out.getvalue())
            if format == 'json': self.assertEqual(json.loads(out.getvalue())['view'], 'experiment_lineage')

    def test_missing_and_cyclic_references_fail_without_writes(self):
        self.register()
        doc = json.loads(self.record().read_text())
        doc['parent_id'] = 'absent'
        self.record().write_text(json.dumps(doc))
        before = self.originals()
        self.invoke('lineage', expected=3)
        self.assertEqual(before, self.originals())
        doc['parent_id'] = 'exp-1'
        self.record().write_text(json.dumps(doc))
        self.invoke('lineage', expected=3)

    def test_mermaid_human_output_and_invalid_format(self):
        self.register()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(['lineage', '--project', str(self.project), '--format', 'mermaid'])
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().startswith('flowchart'))
        self.invoke('lineage', '--format', 'html', expected=2)
