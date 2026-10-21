"""Each verification checks every unique Git evidence path without cross-call caching."""
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

FIXTURE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/benchmark_workflow_utility.py'))


class WorkflowGitVerificationTests(unittest.TestCase):
    def make_fixture(self, arm):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        output = Path(temp.name)
        project = output / 'project'
        (project / 'evidence').mkdir(parents=True)
        save, digest = FIXTURE['save'], FIXTURE['digest']
        for name, seed, count in [('train.json', 42, 96), ('holdout.json', 2026, 64)]:
            save(project / name, FIXTURE['DATASET'](seed, count))
        (project / 'evaluate.py').write_text(FIXTURE['EVALUATOR'], encoding='utf-8')
        train = FIXTURE['load'](project / 'train.json')
        holdout = FIXTURE['load'](project / 'holdout.json')
        mx = sum(x for x, y in train) / len(train)
        my = sum(y for x, y in train) / len(train)
        slope = sum((x-mx)*(y-my) for x, y in train) / sum((x-mx)**2 for x, y in train)
        scores = [sum((my-y)**2 for x, y in holdout) / len(holdout),
                  sum((my+slope*(x-mx)-y)**2 for x, y in holdout) / len(holdout)]
        protected = {name: digest(project / name) for name in FIXTURE['PROTECTED']}
        checkpoint = dict(state='complete', protected=protected)
        evidence, ledger, sources, head = [], [], {}, {}
        for index, mode in enumerate(('baseline', 'candidate')):
            source = FIXTURE['BASELINE' if mode == 'baseline' else 'CANDIDATE']
            source_hash = hashlib.sha256(source.encode()).hexdigest()
            sha = mode + '-commit'
            sources[sha + ':model.py'] = source.encode()
            save(project / (mode + '.json'), {'mse': scores[index]})
            refs = {mode + '.json': digest(project / (mode + '.json')), **protected}
            record = dict(id=mode, baseline_id=None if index == 0 else 'baseline')
            if arm == 'direct':
                record.update(score=scores[index], decision='keep', model_sha256=source_hash,
                              evidence=refs, approved=True, plan={'mode': mode})
            else:
                snapshot = {name: {'sha256': hashlib.sha256(content.encode()).hexdigest(), 'content': content}
                            for name, content in (('model.py', source), ('evaluate.py', FIXTURE['EVALUATOR']))}
                identity = hashlib.sha256((json.dumps(snapshot, ensure_ascii=False) + '\n').encode()).hexdigest()
                record.update(code_ref='source-sha256:' + identity, decision={'status': 'keep'},
                    execution=dict(score=scores[index], status='succeeded',
                                   evidence=[dict(ref=k, sha256=v) for k, v in refs.items()]))
            checkpoint[mode + '_record'] = mode + '-record.json'
            save(project / (mode + '-record.json'), record)
            save(project / 'evidence' / (mode + '-record.json'), record)
            (project / 'evidence' / (mode + '-model.py')).write_text(source, encoding='utf-8')
            if index == 0:
                (output / 'paused-baseline-record.json').write_bytes((project / (mode + '-record.json')).read_bytes())
            evidence.append(dict(mode=mode, id=mode, baseline_id=record['baseline_id'],
                                 score=scores[index], decision='keep', model_sha256=source_hash, source_commit=sha))
            ledger.append(json.dumps(dict(metric_file=mode + '.json', score=scores[index])))
        (project / 'model.py').write_text(FIXTURE['CANDIDATE'], encoding='utf-8')
        (project / 'executions.jsonl').write_text('\n'.join(ledger) + '\n', encoding='utf-8')
        (output / 'paused-executions.jsonl').write_bytes((project / 'executions.jsonl').read_bytes())
        checkpoint['execution_sha256'] = digest(project / 'executions.jsonl')
        selected = {'selected_experiment_id': 'candidate'}
        if arm == 'zar':
            (project / '.autoresearch').mkdir()
        save(project / ('.autoresearch/project.json' if arm == 'zar' else 'direct-project.json'), selected)
        save(project / 'evidence/selected.json', selected)
        save(output / 'checkpoint.json', checkpoint)
        save(output / 'evidence.json', evidence)
        save(output / 'events.json',
             [dict(kind='provider', mode=mode, role=role) for mode in ('baseline', 'candidate') for role in FIXTURE['ROLES']]
             + [dict(kind=kind) for kind in ('approval', 'git_commit') for _ in range(4)])
        # Independent expected union: two records and source snapshots per mode,
        # two metrics, one selection, and three shared protected inputs.
        expected = {'evidence/selected.json', *FIXTURE['PROTECTED']}
        for mode in ('baseline', 'candidate'):
            expected.update((mode + '-record.json', mode + '.json',
                             'evidence/' + mode + '-record.json', 'evidence/' + mode + '-model.py'))
        head = {'HEAD:' + name: (project / name).read_bytes() for name in expected}
        calls = []
        def git(argv, **kwargs):
            calls.append(argv)
            if argv == ['git', 'rev-list', '--count', 'HEAD']:
                return SimpleNamespace(stdout='4\n')
            self.assertEqual(argv[:2], ['git', 'show'])
            return SimpleNamespace(stdout=(head if argv[2].startswith('HEAD:') else sources)[argv[2]])
        return output, expected, head, calls, git

    def test_each_unique_path_is_checked_once_per_verification(self):
        for arm in ('direct', 'zar'):
            with self.subTest(arm=arm):
                output, expected, head, calls, git = self.make_fixture(arm)
                with patch.object(FIXTURE['subprocess'], 'run', side_effect=git):
                    FIXTURE['verify_arm'](output, arm)
                actual = [argv[2][5:] for argv in calls if argv[:2] == ['git', 'show'] and argv[2].startswith('HEAD:')]
                self.assertCountEqual(actual, expected)
                self.assertEqual(len(calls), len(expected) + 3)  # two historical sources + milestone count

    def test_changed_git_evidence_is_detected_on_next_verification(self):
        for arm in ('direct', 'zar'):
            with self.subTest(arm=arm):
                output, expected, head, calls, git = self.make_fixture(arm)
                with patch.object(FIXTURE['subprocess'], 'run', side_effect=git):
                    FIXTURE['verify_arm'](output, arm)
                    head['HEAD:evidence/selected.json'] = b'changed committed bytes'
                    with self.assertRaisesRegex(RuntimeError, 'Git does not retain'):
                        FIXTURE['verify_arm'](output, arm)
