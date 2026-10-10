"""Read-only lineage retains original references and deduplicates corrections."""
from copy import deepcopy
import unittest

from zar.lineage import build_lineage, render_mermaid


def experiment(identifier, *, parent=None, baseline=None, correction=None,
               status='planned', decision=None, code_ref='opaque-code'):
    return dict(id=identifier, revision=1, kind='candidate', parent_id=parent,
                baseline_id=baseline, correction=None if correction is None else dict(supersedes_id=correction),
                code_ref=code_ref, execution=dict(status=status), decision=decision)


def graph(*docs, selected=None):
    return build_lineage(dict(id='project', selected_experiment_id=selected),
                         dict(experiment={doc['id']:doc for doc in docs}))


class LineageCoreTests(unittest.TestCase):
    def test_empty_and_deterministic_with_distinct_parent_baseline_edges(self):
        self.assertEqual(graph()['counts']['execution_count'], 0)
        a=experiment('a'); b=experiment('b', parent='a', baseline='a')
        left=graph(b,a,selected='a'); right=graph(a,b,selected='a')
        self.assertEqual(left,right)
        self.assertEqual([node['id'] for node in left['nodes']], ['a','b'])
        self.assertEqual({edge['type'] for edge in left['edges']}, {'parent','baseline'})
        self.assertTrue(left['nodes'][0]['selected'])
        self.assertEqual(left['nodes'][1]['source'], '.autoresearch/experiments/b.json')

    def test_correction_chain_keeps_raw_states_and_one_execution(self):
        a=experiment('a',status='failed')
        b=experiment('b',correction='a',status='interrupted')
        c=experiment('c',correction='b',status='succeeded',decision=dict(status='keep',validity='valid'))
        cancelled=experiment('cancel',status='cancelled')
        value=graph(c,cancelled,b,a)
        self.assertEqual(value['counts'], dict(record_count=4,execution_count=2,correction_count=2,
                         superseded_count=2,cancelled_count=1,status_counts={'succeeded':1,'cancelled':1}))
        nodes={node['id']:node for node in value['nodes']}
        self.assertEqual(nodes['a']['execution_status'],'failed')
        self.assertEqual(nodes['c']['decision_status'],'keep')
        self.assertEqual(nodes['a']['active_record_id'],'c')
        self.assertEqual(nodes['c']['execution_id'],'a')
        self.assertTrue(nodes['b']['superseded'])
        self.assertFalse(nodes['c']['superseded'])

    def test_stale_references_are_retained_without_retargeting(self):
        a=experiment('a',status='failed'); b=experiment('b',correction='a',status='succeeded')
        child=experiment('child',parent='a',baseline='a')
        value=graph(a,b,child)
        stale=[edge for edge in value['edges'] if edge['target']=='child']
        self.assertEqual(len(stale),2)
        self.assertTrue(all(edge['source']=='a' and edge['source_superseded'] for edge in stale))

    def test_missing_refs_and_cycles_across_all_edge_types_rejected(self):
        for kwargs in [dict(parent='missing'),dict(baseline='missing'),dict(correction='missing')]:
            with self.assertRaisesRegex(ValueError,'Missing'):
                graph(experiment('a',**kwargs))
        # Each edge family is acyclic by itself; their union is cyclic.
        with self.assertRaisesRegex(ValueError,'cycle'):
            graph(experiment('a',baseline='c'),experiment('b',parent='a'),experiment('c',correction='b'))
        with self.assertRaisesRegex(ValueError,'cycle'):
            graph(experiment('a',parent='a'))
        with self.assertRaisesRegex(ValueError,'correction'):
            graph(experiment('a'),experiment('b',correction='a'),experiment('c',correction='a'))

    def test_inputs_unchanged_and_code_ref_not_interpreted(self):
        doc=experiment('a',code_ref='not-a-commit')
        original=deepcopy(doc)
        value=graph(doc)
        self.assertEqual(doc,original)
        self.assertEqual(value['nodes'][0]['code_ref'],'not-a-commit')
        self.assertFalse(value['git_verified'])
        self.assertFalse(value['evidence_checked'])

    def test_long_correction_chain_is_iterative(self):
        docs=[experiment(f'e{index}',correction=f'e{index-1}' if index else None,status='succeeded')
              for index in range(1500)]
        value=graph(*reversed(docs))
        self.assertEqual(value['counts']['execution_count'],1)
        self.assertTrue(all(node['execution_id']=='e0' and node['active_record_id']=='e1499'
                            for node in value['nodes']))
        self.assertEqual(value['counts']['status_counts'],{'succeeded':1})

    def test_mermaid_uses_only_generated_identifiers_and_encodes_labels(self):
        attack='\"]\nclick n0 "javascript:alert(1)"\n```\n%%{init: {}}%%<script>&#34;'
        value=graph(experiment('a',code_ref=attack),experiment('b',parent='a'))
        text=render_mermaid(value)
        self.assertTrue(text.startswith('flowchart TD\n'))
        self.assertIn('n0 -->|parent| n1',text)
        self.assertNotIn(attack,text)
        self.assertNotIn('\nclick',text)
        self.assertNotIn('```',text)
        self.assertNotIn('<script>',text)
        self.assertNotIn('%%{',text)
        self.assertEqual(text.count('\n'),4)


if __name__ == '__main__':
    unittest.main()
