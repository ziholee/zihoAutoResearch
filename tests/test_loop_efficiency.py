"""Avoid repeated work without relaxing role or freshness boundaries."""
import json
import unittest
from unittest.mock import patch
from tests import test_research as fixture
from zar import research, records, roles


class LoopEfficiencyTests(unittest.TestCase):
    setUp=fixture.ResearchTests.setUp
    start=fixture.ResearchTests.start
    respond=fixture.ResearchTests.respond

    def test_planning_reads_records_once_on_each_side_of_model_call(self):
        s=self.start()
        original=records.load_records
        reads=[]
        def read(*args,**kwargs):
            reads.append(1)
            return original(*args,**kwargs)
        with patch('zar.records.load_records',side_effect=read), patch('zar.cli.load_records',side_effect=read), patch('zar.research.chat',side_effect=self.respond) as model:
            planned=research.advance(self.root,s['id'],send=True)
        self.assertEqual(model.call_count,5)
        self.assertEqual(len(reads),10)
        self.assertEqual(planned['state'],'awaiting_approval')
        self.assertFalse((self.root/'metric.json').exists())

    def test_record_change_during_call_is_not_hidden_by_snapshot(self):
        s=self.start()
        original=records.load_records
        changed=False
        def read(*args,**kwargs):
            snap=original(*args,**kwargs)
            if changed:snap.records['memory']['concurrent']={'id':'changed'}
            return snap
        def respond(*args):
            nonlocal changed
            changed=True
            return self.respond(*args)
        with patch('zar.records.load_records',side_effect=read), patch('zar.cli.load_records',side_effect=read), patch('zar.research.chat',side_effect=respond):
            with self.assertRaises(research.ResearchError):research.advance(self.root,s['id'],send=True)
        self.assertEqual(research.status(self.root,s['id'])['state'],'blocked')

    def test_compact_context_preserves_all_evidence_and_source_whitespace(self):
        context={'sources':{'train.py':{'content':'def f():\n    return "a b"\n','sha256':'x'}},
                 'evidence':[{'value':n,'label':'a b'} for n in range(30)]}
        text=roles.role_messages('analysis',context)[1]['content']
        self.assertEqual(json.loads(text),context)
        self.assertLess(len(text),len(json.dumps(context,ensure_ascii=False)))
        self.assertEqual(json.loads(text)['sources']['train.py']['content'],context['sources']['train.py']['content'])
