"""Fixed-input identities without transmitting or retaining file contents."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zar import file_provenance as fp
from zar.codec import loads
from zar.validation import validate_document
from zar.experiments import prepare_create, validate_update, prepare_correction
from zar.comparisons import compare_pair, repeat_summary
from zar.memory_selection import classify
from zar.session_memory import source_identity, VERSION
import test_research as fixtures


class FileProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root/'eval.py').write_bytes(b'evaluation')
        (self.root/'data.bin').write_bytes(b'\x00\xffprivate-content')
        self.policy = dict(version=1, evaluation_paths=['eval.py'], provenance_paths=['data.bin'])

    def test_streamed_binary_identity_has_no_contents(self):
        actual = fp.snapshot(self.root, self.policy)
        self.assertEqual(actual, dict(version=1, files={
            'eval.py': dict(role='evaluation', size_bytes=10, sha256=hashlib.sha256(b'evaluation').hexdigest()),
            'data.bin': dict(role='input', size_bytes=17, sha256=hashlib.sha256(b'\x00\xffprivate-content').hexdigest())}))
        self.assertNotIn('private-content', str(actual))
        fp.assert_current(self.root, self.policy, actual)

    def test_same_size_mtime_content_change_and_deleted_file_detected(self):
        manifest = fp.snapshot(self.root, self.policy)
        path = self.root/'eval.py'; before = path.stat()
        path.write_bytes(b'EVAluation')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaises(ValueError): fp.assert_current(self.root, self.policy, manifest)
        path.unlink()
        with self.assertRaises(ValueError): fp.snapshot(self.root, self.policy)

    def test_policy_rejects_bad_paths_overlaps_and_unsupported_version(self):
        for name in ('../eval.py', './eval.py', '/eval.py', '.private', 'dir//eval.py', 'dir\\eval.py', 'C:eval.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                fp.validate_policy(dict(self.policy, evaluation_paths=[name]), [])
        for policy, editable in ((self.policy, ['eval.py']), (self.policy, ['./data.bin']),
                                 (dict(self.policy, provenance_paths=['eval.py']), []),
                                 (dict(self.policy, version=2), []),
                                 (dict(self.policy, evaluation_paths=[]), [])):
            with self.assertRaises(ValueError):fp.validate_policy(policy, editable)

    def test_symlink_and_directory_rejected(self):
        (self.root/'directory').mkdir()
        with self.assertRaises(ValueError):
            fp.snapshot(self.root, dict(self.policy, provenance_paths=['directory']))
        try: (self.root/'redirect').symlink_to(self.root/'data.bin')
        except (OSError, NotImplementedError): return
        with self.assertRaises(ValueError):
            fp.snapshot(self.root, dict(self.policy, provenance_paths=['redirect']))

    def test_filesystem_aliases_cannot_bypass_fixed_input_protection(self):
        try: os.link(self.root/'eval.py', self.root/'editable.py')
        except OSError as exc: self.skipTest('Hardlinks unavailable: '+str(exc))
        before=(self.root/'eval.py').read_bytes()
        with self.assertRaises(ValueError):fp.validate_paths(self.root,self.policy,['editable.py'])
        with self.assertRaises(ValueError):
            fp.validate_paths(self.root,dict(self.policy,provenance_paths=['editable.py']),[])
        self.assertEqual((self.root/'eval.py').read_bytes(),before)

    def test_case_alias_rejected_where_filesystem_is_case_insensitive(self):
        alias=self.root/'EVAL.py'
        if not alias.exists():self.skipTest('Case-sensitive filesystem')
        with self.assertRaises(ValueError):fp.validate_paths(self.root,self.policy,['EVAL.py'])

    def test_missing_editable_is_allowed_but_redirected_or_nonfile_is_not(self):
        fp.validate_paths(self.root,self.policy,['future.py','new/future.py'])
        (self.root/'directory').mkdir()
        with self.assertRaises(ValueError):fp.validate_paths(self.root,self.policy,['directory'])
        with self.assertRaises(ValueError):fp.validate_paths(self.root,self.policy,['../future.py'])
        try:(self.root/'redirect').symlink_to(self.root/'data.bin')
        except (OSError,NotImplementedError):return
        with self.assertRaises(ValueError):fp.validate_paths(self.root,self.policy,['redirect'])

    def test_limits_are_failures_not_partial_manifests(self):
        with patch.object(fp, 'MAX_FILE_BYTES', 4):
            with self.assertRaises(ValueError):fp.snapshot(self.root, self.policy)
        with patch.object(fp, 'MAX_TOTAL_BYTES', 20):
            with self.assertRaises(ValueError):fp.snapshot(self.root, self.policy)
        with patch.object(fp, 'MAX_FILES', 1):
            with self.assertRaises(ValueError):fp.snapshot(self.root, self.policy)

    def test_file_changed_during_hash_rejected(self):
        original = fp.os.read
        mutated = False
        def changed(fd, amount):
            nonlocal mutated
            result = original(fd, amount)
            if result and not mutated:
                mutated = True
                (self.root/'eval.py').write_bytes(b'CHANGED!!!')
            return result
        with patch.object(fp.os, 'read', side_effect=changed):
            with self.assertRaises(ValueError):fp.snapshot(self.root, self.policy)

    def test_malformed_manifest_is_not_accepted(self):
        manifest = fp.snapshot(self.root, self.policy)
        for field, value in (('size_bytes', True), ('sha256', 'not-a-hash'), ('role', 'editable')):
            wrong = deepcopy(manifest); wrong['files']['eval.py'][field] = value
            with self.assertRaises(ValueError):fp.validate_manifest(wrong)
        with self.assertRaises(ValueError):fp.validate_manifest(dict(manifest, version=9))
        with self.assertRaises(ValueError):fp.validate_manifest(dict(version=1, files={}))


class FileManifestRecordTests(unittest.TestCase):
    setUp = fixtures.ResearchTests.setUp

    def project(self):
        return loads((self.root/'.autoresearch/project.json').read_text())

    def manifest(self):
        (self.root/'eval.py').write_text('frozen evaluator')
        return fp.snapshot(self.root, dict(version=1,evaluation_paths=['eval.py'],provenance_paths=[]))

    def record(self, name, manifest=None):
        body=dict(id=name,kind='baseline',hypothesis='test',parent_id=None,baseline_id=None,
                  code_ref='code',config_ref='config',command=self.project()['commands'][0],review_ids=[],
                  run_context=dict(scope='full',seed=42,budget_ref='test'))
        if manifest is not None:body['file_manifest']=manifest
        doc, errors=prepare_create(body,self.project(),'2026-10-28T00:00:00Z')
        self.assertEqual(errors, [])
        doc['execution'].update(status='succeeded',started_at='2026-10-28T00:00:00Z',finished_at='2026-10-28T00:00:00Z',exit_code=0,score=1,
                                evidence=[dict(kind='user_report',ref='observed',locator=None,sha256=None)])
        return doc

    def test_optional_project_schema_and_manifest_immutability(self):
        project=self.project();self.assertEqual(validate_document(project,'project'),[])
        project['file_contract']=dict(version=1,evaluation_paths=['eval.py'],provenance_paths=[])
        self.assertEqual(validate_document(project,'project'),[])
        project['file_contract']['evaluation_paths']=['train.py']
        self.assertTrue(validate_document(project,'project'))
        manifest=self.manifest();original=self.record('base',manifest)
        for changed in (dict(original,file_manifest=None), {k:v for k,v in original.items() if k!='file_manifest'}):
            self.assertTrue(validate_update(original,changed))
        legacy=self.record('old');self.assertTrue(validate_update(legacy,dict(legacy,file_manifest=manifest)))

    def test_comparison_requires_both_matching_fixed_manifests(self):
        manifest=self.manifest();base=self.record('base',manifest);candidate=self.record('candidate',manifest)
        docs={d['id']:d for d in (base,candidate)}
        self.assertTrue(compare_pair(base,candidate,docs)['comparable'])
        candidate['code_ref']='different-candidate-code'
        self.assertTrue(compare_pair(base,candidate,docs)['comparable'])
        candidate['file_manifest']['files']['eval.py']['sha256']='0'*64
        self.assertIn('file_manifest_mismatch',compare_pair(base,candidate,docs)['reasons'])
        candidate.pop('file_manifest')
        self.assertIn('file_manifest_unknown',compare_pair(base,candidate,docs)['reasons'])
        base.pop('file_manifest')
        self.assertTrue(compare_pair(base,candidate,docs)['comparable'])

    def test_confirmation_and_correction_keep_manifest_contract(self):
        manifest=self.manifest();base=self.record('base',manifest);repeat=self.record('repeat',manifest)
        repeat.update(kind='confirmation',parent_id='base',baseline_id='base')
        repeat['file_manifest']['files']['eval.py']['sha256']='0'*64
        result=repeat_summary(base,dict(base=base,repeat=repeat))
        self.assertEqual(result['experiment_ids'],['base'])
        body=dict(id='corrected',revision=1,execution=deepcopy(base['execution']),reason='record correction',evidence=deepcopy(base['execution']['evidence']))
        corrected,errors=prepare_correction(base,body,'2026-10-28T00:00:01Z')
        self.assertEqual(errors,[]);self.assertEqual(corrected['file_manifest'],base['file_manifest'])

    def test_memory_cannot_mark_missing_manifest_as_matched(self):
        manifest=self.manifest();record=self.record('base',manifest)
        lesson=dict(experiment_id='base',proposal={},assessment=dict(version=VERSION,provenance=dict(experiment=dict(id='base',sha256=source_identity(record)))))
        session=dict(run_context=record['run_context'],file_manifest=deepcopy(manifest))
        selected,excluded=classify(lesson,session,self.project(),dict(base=record),set(),{})
        self.assertIsNone(excluded);self.assertEqual(selected['relevance'],'matched')
        session.pop('file_manifest')
        selected,excluded=classify(lesson,session,self.project(),dict(base=record),set(),{})
        self.assertIsNone(excluded);self.assertEqual(selected['relevance'],'unknown')
        session['file_manifest']=deepcopy(manifest);session['file_manifest']['files']['eval.py']['sha256']='0'*64
        selected,excluded=classify(lesson,session,self.project(),dict(base=record),set(),{})
        self.assertEqual(excluded,'mismatch')


if __name__=='__main__':unittest.main()
