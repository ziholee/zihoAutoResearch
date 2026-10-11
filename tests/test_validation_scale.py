"""Ancestry validation preserves diagnostics without repeatedly walking shared tails."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import unittest

from zar.codec import loads
from zar.records import RecordSnapshot
from zar.validation import inspect_project


class CountingRecord(dict):
    reads = 0

    def __getitem__(self, key):
        if key in ('parent_id', 'baseline_id'):
            type(self).reads += 1
        return super().__getitem__(key)


class AncestryValidationTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'examples/contract-v1'
        self.project = loads((source / 'project.json').read_text())
        self.project['selected_experiment_id'] = None
        self.template = loads((source / 'baseline.json').read_text())
        self.template.update(review_ids=[], decision=None, decision_history=[])
        self.template['execution'].update(status='planned', started_at=None, finished_at=None,
                                         exit_code=None, score=None, evidence=[], note=None)

    def records(self, links, field):
        records = {}
        for identifier, ancestor in links.items():
            doc = deepcopy(self.template)
            doc.update(id=identifier, parent_id=None, baseline_id=None)
            doc[field] = ancestor
            records[identifier] = CountingRecord(doc)
        return records

    def inspect(self, records, overlay=None):
        groups = {kind: {} for kind in ('experiment', 'review', 'submission', 'memory', 'candidate')}
        groups['experiment'] = records
        snapshot = RecordSnapshot(groups, {key: Path(key + '.json') for key in records}, [])
        return inspect_project(Path('synthetic-scale'), self.project, snapshot=snapshot,
                               experiment=overlay, check_files=False)

    def test_deep_shared_ancestry_requires_linear_reference_reads(self):
        # Count work rather than wall time: portable even on slow CI machines.
        for field in ('parent_id', 'baseline_id'):
            with self.subTest(field=field):
                count = 1500
                links = {f'e{i}': f'e{i-1}' if i else None for i in range(count)}
                for order in (links, dict(reversed(list(links.items())))):
                    records = self.records(order, field)
                    CountingRecord.reads = 0
                    errors = [d for d in self.inspect(records) if d['severity'] == 'error']
                    self.assertEqual(errors, [])
                    self.assertLessEqual(CountingRecord.reads, count * 12)

    def test_all_small_graphs_preserve_cycle_reachability_and_diagnostic_order(self):
        identifiers = ('a', 'b', 'c')
        for field in ('parent_id', 'baseline_id'):
            for targets in product((None, 'missing', *identifiers), repeat=3):
                links = dict(zip(identifiers, targets))
                expected = []
                for identifier, ancestor in links.items():
                    if ancestor is not None and (ancestor not in links or ancestor == identifier):
                        expected.append((identifier + '.json', 'Invalid ' + field))
                    seen = {identifier}
                    while ancestor in links:
                        if ancestor in seen:
                            expected.append((identifier + '.json', field + ' contains a cycle'))
                            break
                        seen.add(ancestor)
                        ancestor = links[ancestor]
                actual = [(d['path'], d['message']) for d in self.inspect(self.records(links, field))
                          if d['severity'] == 'error' and d['message'] in
                          ('Invalid ' + field, field + ' contains a cycle')]
                self.assertEqual(actual, expected, (field, links))

    def test_overlay_cycle_is_checked_without_mutating_snapshot(self):
        records = self.records({'a': None, 'b': 'a', 'c': 'b'}, 'parent_id')
        before = deepcopy(records)
        overlay = deepcopy(records['a'])
        overlay['parent_id'] = 'c'
        errors = [d for d in self.inspect(records, overlay) if d['severity'] == 'error']
        self.assertEqual([d['message'] for d in errors], ['parent_id contains a cycle'] * 3 +
                         ['Candidate/experiment ancestry contains a cycle'])
        self.assertEqual(records, before)
