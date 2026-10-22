from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zar import research, session_memory as memory
from zar.codec import dumps
from test_session_memory import record


class RelevanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();(self.root/'.autoresearch/sessions').mkdir(parents=True)
        self.records={'base':record('base',2),'candidate':record('candidate',1,'base')}
        for doc in self.records.values():doc['comparison'].update(id='cmp',dataset_ref='data',split_ref='split',metric='rmse',evaluation_ref='eval')
        self.project={k:deepcopy(self.records['candidate'][k]) for k in ('comparison','environment')}
        self.current=dict(id='session-'+'f'*32,memory_selection_version=1,run_context=deepcopy(self.records['candidate']['run_context']))
    def add(self,n,*,legacy=False,scope=None):
        s=dict(id='session-'+f'{n:032x}',created_at=f'{n:04d}',state='complete',experiment_id='candidate',outputs={'memory':dict(lesson='proposal',limitation='hold')})
        if not legacy:s['memory_assessment']=memory.assess({},memory.build_evidence(s,self.records))
        if scope:s['memory_assessment']['provenance']['experiment']['run_context']['scope']=scope
        (self.root/'.autoresearch/sessions'/ (s['id']+'.json')).write_text(dumps(s))
        return s
    def select(self,cache=None):
        return research._prior_lessons(self.root,self.current,cache,project=self.project,experiments=self.records)
    def test_old_matched_precedes_recent_unknown_and_keeps_hold(self):
        old=self.add(1)
        for i in range(2,9):self.add(i,legacy=True)
        lessons,counts=self.select()
        self.assertEqual([x['session_id'] for x in lessons],[old['id']]+['session-'+f'{n:032x}' for n in (8,7,6,5)])
        self.assertEqual(lessons[0]['relevance'],'matched');self.assertEqual(lessons[0]['assessment']['status'],'hold')
        self.assertEqual(lessons[1]['assessment']['status'],'unassessed')
    def test_mismatch_and_stale_do_not_fill(self):
        self.add(1);self.add(2,scope='proxy');self.add(3,legacy=True)
        self.records['candidate']['revision']=2
        lessons,counts=self.select()
        self.assertEqual(len(lessons),1);self.assertEqual(counts['counts']['source_changed'],2)
    def test_legacy_policy_unchanged(self):
        for i in range(1,8):self.add(i,legacy=True)
        self.current.pop('memory_selection_version')
        lessons=research._prior_lessons(self.root,self.current)
        self.assertEqual([x['created_at'] for x in lessons],['0003','0004','0005','0006','0007'])
        self.assertNotIn('relevance',lessons[0])
    def test_cache_hashes_reused_only_within_one_call(self):
        for i in range(1,9):self.add(i)
        cache={}
        original=memory.identity
        with patch.object(memory,'identity',wraps=original) as identity:
            first,_=self.select(cache)
            self.assertLessEqual(identity.call_count,2)
        self.records['candidate']['revision']=2
        second,_=self.select(cache)
        self.assertTrue(first);self.assertEqual(second,[])
    def test_correction_excludes_legacy_and_validated(self):
        self.add(1);self.add(2,legacy=True)
        self.records['new']=dict(record('new',1),correction={'supersedes_id':'candidate'})
        self.assertEqual(self.select()[0],[])
    def test_stale_latest_is_replaced_by_next_eligible(self):
        for i in range(1,8):self.add(i)
        path=self.root/'.autoresearch/sessions'/('session-'+f'{7:032x}'+'.json')
        path.write_text(path.read_text().replace('"sha256": "','"sha256": "bad'))
        lessons,summary=self.select()
        self.assertEqual([x['created_at'] for x in lessons],['0006','0005','0004','0003','0002'])
        self.assertEqual(summary['counts']['source_changed'],1)
        self.assertEqual(summary['counts']['limit'],1)
    def test_equal_dates_use_session_id_descending(self):
        for i in (4,1,3,2):
            s=self.add(i);s['created_at']='same'
            (self.root/'.autoresearch/sessions'/(s['id']+'.json')).write_text(dumps(s))
        self.assertEqual([x['session_id'] for x in self.select()[0]],['session-'+f'{n:032x}' for n in (4,3,2,1)])
    def test_declared_mismatch_excluded_and_unknown_not_promoted(self):
        self.add(1)
        self.project['environment']['device']='gpu'
        out,summary=self.select()
        self.assertEqual(out,[]);self.assertEqual(summary['counts']['mismatch'],1)
        self.project['environment']['device']=None
        out,_=self.select()
        self.assertEqual(out[0]['relevance'],'unknown');self.assertEqual(out[0]['assessment']['status'],'hold')
    def test_seed_is_not_a_filter_and_changes_are_explained(self):
        self.add(1);self.current['run_context']['seed']=999
        out,_=self.select()
        self.assertEqual(out[0]['relevance'],'matched')
        self.assertEqual(out[0]['differences']['seed'],dict(source=42,current=999))
    def test_history_change_with_same_size_and_mtime_invalidates_cache(self):
        import os
        s=self.add(1);cache={};self.select(cache)
        path=self.root/'.autoresearch/sessions'/(s['id']+'.json');stat=path.stat()
        path.write_text(path.read_text().replace('proposal','changed!'))
        os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        self.assertEqual(path.stat().st_size,stat.st_size)
        self.assertEqual(self.select(cache)[0][0]['proposal']['lesson'],'changed!')
    def test_cache_limits_do_not_change_selection(self):
        for i in range(1,9):self.add(i)
        expected=self.select()
        for entries,size in ((0,0),(2,100000),(2048,1)):
            with patch.object(research,'HISTORY_CACHE_MAX_ENTRIES',entries),patch.object(research,'HISTORY_CACHE_MAX_BYTES',size):
                cache={}
                self.assertEqual(self.select(cache),expected);self.assertEqual(self.select(cache),expected)
                self.assertLessEqual(len(cache),entries)
                self.assertLessEqual(sum(v[2] for v in cache.values()),size)
    def test_policy_pin_is_conditional_token_input(self):
        keys=('id','goal','profile','project_hash','records_hash','sources','command','metric_file','metric_key','outputs','experiment_id','run_context','deadline','max_calls','environment_hash')
        s={key:None for key in keys}
        legacy=research.token(s)
        self.assertEqual(legacy,research.digest(s))
        s['memory_selection_version']=1
        self.assertNotEqual(legacy,research.token(s))
        for value in (2,None,True):
            self.current['memory_selection_version']=value
            with self.assertRaisesRegex(research.ResearchError,'Unsupported'):
                self.select()
    def test_history_condition_copy_cannot_forge_a_match(self):
        self.records['candidate']['comparison']['dataset_ref']='other-data'
        s=self.add(1)
        s['memory_assessment']['provenance']['experiment']['comparison']=deepcopy(self.project['comparison'])
        (self.root/'.autoresearch/sessions'/(s['id']+'.json')).write_text(dumps(s))
        lessons,summary=self.select()
        self.assertEqual(lessons,[]);self.assertEqual(summary['counts']['mismatch'],1)
    def test_saved_condition_copy_does_not_override_current_hashed_source(self):
        self.add(1,scope='proxy')
        lessons,_=self.select()
        self.assertEqual(lessons[0]['relevance'],'matched')
        self.assertEqual(lessons[0]['assessment']['provenance']['experiment']['run_context']['scope'],'full')
    def test_all_comparison_fields_and_scope_budget_are_required(self):
        self.add(1)
        for field in ('id','dataset_ref','split_ref','metric','direction','evaluation_ref','min_delta'):
            with self.subTest(field=field):
                old=self.project['comparison'][field]
                self.project['comparison'][field]='different' if field!='min_delta' else 9
                self.assertEqual(self.select()[0],[])
                self.project['comparison'][field]=old
        for field in ('scope','budget_ref'):
            with self.subTest(field=field):
                old=self.current['run_context'][field];self.current['run_context'][field]='different'
                self.assertEqual(self.select()[0],[])
                self.current['run_context'][field]=old
    def test_deleted_source_is_not_a_legacy_fallback(self):
        self.add(1,legacy=True);del self.records['candidate']
        lessons,summary=self.select()
        self.assertEqual(lessons,[]);self.assertEqual(summary['counts']['source_changed'],1)
    def test_changed_contrast_handles_excluded_before_top_five_with_refill(self):
        for i in range(1,7):self.add(i)
        s=self.add(7)
        s['outputs']['memory']['contrast']=dict(effect='helped',applicability='same',evidence=['invented'])
        (self.root/'.autoresearch/sessions'/(s['id']+'.json')).write_text(dumps(s))
        lessons,summary=self.select()
        self.assertEqual([x['created_at'] for x in lessons],['0006','0005','0004','0003','0002'])
        self.assertEqual(summary['counts']['source_changed'],1)
