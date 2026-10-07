"""Public bounded-context contract: omissions must not conceal unsafe states."""
import hashlib
from unittest.mock import patch
from contextlib import redirect_stdout
import io

from test_experiments import ExperimentHarness
from zar.codec import loads, dumps


class ContextTests(ExperimentHarness):
    def write_input(self, document):
        path = self.root / 'input.json'
        path.write_text(dumps(document), encoding='utf-8')
        return path

    def update_record(self, document):
        return self.invoke('experiment', 'update', document['id'], '--file', str(self.write_input(document)))

    def test_prioritized_pages_preserve_unknown_and_failure_counts(self):
        self.register(self.create('base', run_context=dict(scope='full', seed=1, budget_ref='v1')))
        doc = self.success(loads(self.record('base').read_text()))
        self.update_record(doc)
        doc = loads(self.record('base').read_text())
        decision = dict(revision=doc['revision'], decision=dict(status='keep', validity='valid',
                        reason='Mock baseline', evidence=doc['execution']['evidence'], next_action=None))
        self.invoke('experiment', 'decide', 'base', '--file', str(self.write_input(decision)))
        project = loads(self.stored.read_text()); project['selected_experiment_id'] = 'base'
        self.invoke('project', 'set', '--file', str(self.write_input(project)))
        self.register(self.create('unknown', kind='performance', baseline_id='base'))
        unknown = loads(self.record('unknown').read_text())
        unknown['execution'].update(status='unknown', note='Launch unknown', evidence=doc['execution']['evidence'])
        self.update_record(unknown)
        self.register(self.create('failed', kind='performance', baseline_id='base'))
        failed = loads(self.record('failed').read_text())
        failed['execution'].update(status='failed', started_at='2026-01-01T00:00:00Z',
                                  finished_at='2026-01-01T00:01:00Z', exit_code=1, note='Mock failure',
                                  evidence=doc['execution']['evidence'])
        self.update_record(failed)
        before = {p.name:p.read_bytes() for p in self.stored.parent.rglob('*.json')}
        first = self.invoke('context', '--limit', '1')['data']
        self.assertEqual(first['cards'][0]['id'], 'base')
        self.assertEqual(first['counts']['unknown'], 1)
        self.assertEqual(first['counts']['failed'], 1)
        self.assertTrue(first['safeguards']['has_unfinished'])
        self.assertFalse(first['safeguards']['evidence_checked'])
        self.assertEqual(first['page']['next_offset'], 1)
        second = self.invoke('context', '--limit', '1', '--offset', '1')['data']
        self.assertEqual(second['cards'][0]['id'], 'unknown')
        third = self.invoke('context', '--limit', '1', '--offset', '2')['data']
        self.assertEqual(third['cards'][0]['id'], 'failed')
        self.assertIsNone(third['page']['next_offset'])
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.stored.parent.rglob('*.json')})

    def test_successful_envelope_is_bounded_and_truncation_explicit(self):
        self.register(self.create('long', hypothesis='긴 근거 ' * 10000))
        result = self.invoke('context', '--max-bytes', '4096')
        self.assertLessEqual(len(dumps(result, ensure_ascii=True).encode()) + 1, 4096)
        self.assertIn('hypothesis', result['data']['cards'][0]['truncated_fields'])
        self.assertTrue(result['data']['omissions']['fields'])
        self.assertEqual(result['data']['cards'][0]['source'], '.autoresearch/experiments/long.json')

    def test_context_does_not_read_evidence_but_full_check_still_does(self):
        log = self.project/'large-log.txt'; log.write_text('original')
        self.register()
        doc = self.success(loads(self.record().read_text()))
        doc['execution']['evidence'] = [dict(kind='file', ref='large-log.txt', locator=None,
                                           sha256=hashlib.sha256(log.read_bytes()).hexdigest())]
        self.update_record(doc)
        log.write_text('changed')
        from zar.cli import main
        with patch('zar.validation.hashlib.file_digest', side_effect=AssertionError('context hashed evidence')):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['context','--project',str(self.project),'--json']),0)
        result = loads(output.getvalue())
        self.assertIn('evidence_not_checked', [d['code'] for d in result['diagnostics']])
        handle = result['data']['cards'][0]['evidence'][0]
        self.assertEqual(handle['pointer'], '/execution/evidence/0')
        self.assertEqual(handle['record_id'], 'exp-1')
        self.assertIn('evidence_changed', [d['code'] for d in self.invoke('check')['diagnostics']])

    def test_focus_invalid_inputs_and_corrupt_record_fail(self):
        self.register(self.create('base'))
        self.register(self.create('candidate', kind='performance', baseline_id='base'))
        data = self.invoke('context','--experiment','candidate','--limit','2')['data']
        self.assertEqual([d['id'] for d in data['cards']], ['candidate','base'])
        self.invoke('context','--experiment','missing',expected=3)
        for args in [('--limit','0'),('--offset','-1'),('--max-bytes','1')]:
            self.invoke('context',*args,expected=2)
        self.record('base').write_text('{')
        self.invoke('context',expected=2)

    def test_incomplete_project_is_inspectable_without_claiming_ready(self):
        project = loads(self.stored.read_text()); project['objective'] = None
        self.invoke('project','set','--file',str(self.write_input(project)))
        data = self.invoke('context')['data']
        self.assertFalse(data['ready'])
        self.assertIn('objective', data['missing'])

    def test_snapshot_pin_detects_metadata_changes_and_pages_are_stable(self):
        self.register(self.create('first'))
        first = self.invoke('context')['data']
        self.assertEqual(first, self.invoke('context','--snapshot',first['snapshot_id'])['data'])
        self.register(self.create('second'))
        self.invoke('context','--snapshot',first['snapshot_id'],expected=3)

    def test_record_files_are_read_once_per_context_call(self):
        self.register()
        from pathlib import Path
        from zar.cli import main
        original = Path.read_text
        calls = []
        def read(path, *args, **kwargs):
            if path.resolve() == self.record().resolve(): calls.append(path)
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['context','--project',str(self.project),'--json']),0)
        self.assertEqual(len(calls),1)

    def test_evidence_cli_exact_page_revision_and_unhashed_identity_pin(self):
        source = self.project/'log.txt'; source.write_bytes('가\r\nsecond\n'.encode())
        self.register()
        doc = self.success(loads(self.record().read_text()))
        doc['execution']['evidence'] = [dict(kind='file',ref='log.txt',locator=None,sha256=None)]
        self.update_record(doc)
        args = ['evidence','read','--kind','experiment','--id','exp-1','--pointer','/execution/evidence/0']
        first = self.invoke(*args,'--revision','2','--max-lines','1')['data']
        self.assertEqual(first['text'],'가\r\n')
        self.assertEqual(first['next_line'],2)
        digest = first['source']['actual_sha256']
        second = self.invoke(*args,'--start-line','2','--sha256',digest)['data']
        self.assertEqual(second['text'],'second\n')
        self.invoke(*args,'--revision','1',expected=3)
        source.write_text('changed\n')
        failure = self.invoke(*args,'--sha256',digest,expected=3)
        self.assertIsNone(failure['data'])
        self.assertEqual(failure['diagnostics'][0]['code'],'evidence_changed')

    def test_schema_valid_large_comparison_id_does_not_block_context(self):
        project = loads(self.stored.read_text())
        project['comparison']['id'] = 'x' * 1100000
        self.invoke('project','set','--file',str(self.write_input(project)))
        self.register()
        data = self.invoke('context')['data']
        self.assertIn('comparison_id',data['truncated_fields'])
        self.assertIn('comparison_id',data['cards'][0]['truncated_fields'])
        self.assertEqual(data['counts']['experiments'],1)

    def test_corrected_baseline_keeps_original_reference_and_warning(self):
        self.register(self.create('base'))
        original = self.success(loads(self.record('base').read_text()))
        self.update_record(original)
        original = loads(self.record('base').read_text())
        self.register(self.create('candidate',kind='performance',baseline_id='base',parent_id='base'))
        correction = dict(id='base-fixed',revision=original['revision'],execution=original['execution'],
                          reason='Mock observation correction',evidence=original['execution']['evidence'])
        correction['execution']['score'] = 2
        self.invoke('experiment','correct','base','--file',str(self.write_input(correction)))
        result = self.invoke('context','--experiment','candidate','--limit','2')
        candidate,base = result['data']['cards']
        self.assertEqual(candidate['baseline_id'],'base')
        self.assertEqual(base['corrected_by'],'base-fixed')
        self.assertEqual(result['data']['counts']['superseded'],1)
        self.assertIn('reference_superseded',[d['code'] for d in result['diagnostics']])
