#!/usr/bin/env python3
"""Demonstrate record flow with synthetic results; never execute ML commands.

Install ziho-autoresearch first. --output must name a directory that does not
exist. All files and CLI writes stay in that new directory. Decisions here are
fixed demonstration inputs, not an automated research decision policy.
"""

import argparse
from decimal import Decimal
import hashlib
from pathlib import Path
import subprocess
import sys

from zar.codec import dumps, loads


class MockCycle:
    def __init__(self, output, scenario):
        output.mkdir()  # Fail before any write when the destination exists.
        self.output = output
        self.project = output / 'project'
        self.project.mkdir()
        self.store = self.project / '.autoresearch'
        self.scenario = scenario
        self.events = []

    def cli(self, *args):
        result = subprocess.run(
            [sys.executable, '-m', 'zar', *args, '--project', str(self.project), '--json'],
            cwd=self.output, capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        envelope = loads(result.stdout)
        self.events.append(dict(arguments=list(args), exit_code=result.returncode, result=envelope))
        (self.output / 'events.json').write_text(dumps({'events': self.events}), encoding='utf-8')
        if result.returncode or not envelope['ok']:
            raise RuntimeError(f'CLI failed: {args!r}: {result.stdout} {result.stderr}')
        return envelope['data']

    def read(self, relative):
        return loads((self.store / relative).read_text(encoding='utf-8'))

    def draft(self, name, value):
        path = self.store / 'drafts' / name
        path.write_text(dumps(value), encoding='utf-8')
        return str(path)

    def configure(self):
        self.cli('init')
        (self.store / 'drafts').mkdir()
        (self.store / 'evidence').mkdir()
        document = self.read('project.json')
        document.update(
            name='Synthetic research cycle', objective='Verify record flow using mock observations only',
            comparison=dict(id='mock-comparison-v1', dataset_ref='synthetic-data-v1',
                            split_ref='synthetic-split-v1', metric='mock-error', direction='minimize',
                            evaluation_ref='synthetic-evaluator-v1', min_delta=Decimal('0.1')),
            environment=dict(os='other', runtime='synthetic-python', device='synthetic-cpu'),
            commands=[dict(name='train', argv=[sys.executable, 'train.py'], cwd='.')],
            budget=dict(max_experiments=2, max_run_seconds=60), editable_paths=['train.py'],
            next_action='Register supplied synthetic baseline',
        )
        self.cli('project', 'set', '--file', self.draft('project.json', document))
        with (self.store / 'program.md').open('a', encoding='utf-8') as handle:
            handle.write('\n## Mock example interpretation\n\n'
                         'Synthetic observations only: no dataset or ML execution exists. '
                         'The sentinel train.py must never run. Manual SHA-256 code identities '
                         'identify its bytes; they do not claim Git or execution verification. '
                         'Comparison settings and next action are in project.json.\n')

    def observe(self, identifier, score, scope, baseline=None):
        # This file is a sentinel, not a model; invoking it would leave a marker.
        source = (f'# Synthetic code identity: {identifier}\n'
                  'from pathlib import Path\n'
                  'Path("TRAINING_WAS_EXECUTED").write_text("unexpected execution")\n'
                  'raise RuntimeError("Mock cycle must never execute this file")\n')
        code = self.project / 'train.py'
        code.write_text(source, encoding='utf-8')
        review_id = identifier + '-review'
        review = dict(id=review_id, supersedes_id=None,
                      code_ref='sha256:' + hashlib.sha256(code.read_bytes()).hexdigest(),
                      data_ref='synthetic-data-v1', items=[dict(
                          id='mock-scope', topic='Execution scope', applicability='Synthetic demonstration only',
                          observation='Sentinel code is recorded but must never execute',
                          assessment='unverifiable', evidence=[], limitation='No real data or ML execution',
                          next_action='Use supplied mock observations only')])
        self.cli('review', 'add', '--file', self.draft(review_id + '.json', review))
        plan = dict(
            id=identifier, kind='performance' if baseline else 'baseline',
            hypothesis='Synthetic candidate observation' if baseline else 'Synthetic reference observation',
            parent_id=baseline, baseline_id=baseline,
            code_ref='sha256:' + hashlib.sha256(code.read_bytes()).hexdigest(),
            config_ref='synthetic-config-v1', command=self.read('project.json')['commands'][0],
            review_ids=[review_id], run_context=dict(scope=scope, seed=42, budget_ref='mock-60-seconds-v1'),
        )
        self.cli('experiment', 'create', '--file', self.draft(identifier + '-plan.json', plan))
        document = self.read(f'experiments/{identifier}.json')
        start = '2026-01-01T00:02:00Z' if baseline else '2026-01-01T00:00:00Z'
        finish = '2026-01-01T00:03:00Z' if baseline else '2026-01-01T00:01:00Z'
        document['execution'].update(status='running', started_at=start)
        self.cli('experiment', 'update', identifier, '--file', self.draft(identifier + '-running.json', document))
        log = self.store / 'evidence' / (identifier + '.txt')
        log.write_text(f'SIMULATED ONLY; NO TRAINING EXECUTED\nexperiment={identifier}\n'
                       f'scope={scope}\nscore={score}\nstart={start}\nfinish={finish}\n', encoding='utf-8')
        evidence = dict(kind='file', ref=log.relative_to(self.project).as_posix(),
                        locator='Entire synthetic observation', sha256=hashlib.sha256(log.read_bytes()).hexdigest())
        document = self.read(f'experiments/{identifier}.json')
        document['execution'].update(
            status='succeeded', finished_at=finish, exit_code=0, score=Decimal(score),
            evidence=[evidence], note='SIMULATED observation and timestamps; no ML command executed.',
        )
        self.cli('experiment', 'update', identifier, '--file', self.draft(identifier + '-result.json', document))
        return evidence

    def decide(self, identifier, status, validity, reason, evidence, next_action=None):
        record = self.read(f'experiments/{identifier}.json')
        value = dict(revision=record['revision'], decision=dict(
            status=status, validity=validity, reason=reason, evidence=[evidence], next_action=next_action))
        self.cli('experiment', 'decide', identifier, '--file', self.draft(identifier + '-decision.json', value))

    def select(self, identifier, next_action):
        document = self.read('project.json')
        document.update(selected_experiment_id=identifier, next_action=next_action)
        self.cli('project', 'set', '--file', self.draft('selection.json', document))

    def run(self):
        self.configure()
        base_evidence = self.observe('mock-baseline', '1.2', 'full')
        self.decide('mock-baseline', 'keep', 'valid',
                    'Accept supplied synthetic reference for the mock exercise only.', base_evidence)
        self.select('mock-baseline', 'Compare the synthetic candidate')
        scope = 'proxy' if self.scenario == 'scope-mismatch' else 'full'
        candidate_evidence = self.observe('mock-candidate', '1.1', scope, 'mock-baseline')
        comparison = self.cli('experiment', 'compare', 'mock-baseline', 'mock-candidate')
        if self.scenario == 'scope-mismatch':
            if comparison['comparable'] or 'scope_mismatch' not in comparison['reasons']:
                raise RuntimeError('Expected an incomparable synthetic pair')
            action = 'Mock budget exhausted; retain candidate evidence and review scope before any new run.'
            self.decide('mock-candidate', 'hold', 'not_comparable',
                        'Synthetic proxy/full scopes differ; scores cannot support adoption.',
                        candidate_evidence, action)
            self.select('mock-baseline', action)
        else:
            if not comparison['comparable'] or comparison['improvement'] != Decimal('0.1'):
                raise RuntimeError('Expected an exact 0.1 synthetic improvement')
            self.decide('mock-candidate', 'keep', 'valid',
                        'Supplied comparable mock observations satisfy this demonstration; no ML validity claim.',
                        candidate_evidence)
            self.select('mock-candidate', 'Mock cycle complete; no training or submission performed.')
        prediction = self.project / 'mock-predictions.csv'
        prediction.write_text('id,prediction\nsynthetic-1,0.5\n', encoding='utf-8')
        artifact_hash = hashlib.sha256(prediction.read_bytes()).hexdigest()
        candidate = self.read('experiments/mock-candidate.json')
        candidate['execution']['artifacts'].append(dict(
            role='submission', path=prediction.name, sha256=artifact_hash,
            code_ref=candidate['code_ref'], config_ref=candidate['config_ref'],
            evidence=[candidate_evidence]))
        self.cli('experiment', 'update', 'mock-candidate',
                 '--file', self.draft('candidate-artifact.json', candidate))
        submission = dict(id='mock-submission', supersedes_id=None,
            experiment_id='mock-candidate', competition='synthetic-competition', external_id='synthetic-entry',
            artifact=dict(path=prediction.name, sha256=artifact_hash), leaderboard='mock-public',
            metric='mock-error', direction='minimize', score=Decimal('1.15'),
            submitted_at='2026-01-01T00:04:00Z', observed_at='2026-01-01T00:05:00Z',
            evidence=[dict(kind='user_report', ref='SIMULATED external score; no actual submission',
                           locator=None, sha256=None)])
        self.cli('submission', 'add', '--file', self.draft('mock-submission.json', submission))
        report = self.cli('report', '--output', 'summary.md')
        context = self.cli('context', '--experiment', 'mock-candidate')
        (self.output / 'context.json').write_text(dumps(context), encoding='utf-8')
        candidate = self.read('experiments/mock-candidate.json')
        page = self.cli('evidence', 'read', '--kind', 'experiment', '--id', 'mock-candidate',
                        '--pointer', '/execution/evidence/0', '--revision', str(candidate['revision']),
                        '--max-lines', '2')
        (self.output / 'evidence-page.json').write_text(dumps(page), encoding='utf-8')
        self.cli('check')
        state = self.cli('status')
        selected = self.read(f"experiments/{state['selected_experiment_id']}.json")
        candidate = self.read('experiments/mock-candidate.json')
        workspace_ref = 'sha256:' + hashlib.sha256((self.project / 'train.py').read_bytes()).hexdigest()
        summary = dict(
            simulated=True, scenario=self.scenario, project=str(self.project),
            comparison=comparison, decision=candidate['decision'],
            selected_experiment_id=state['selected_experiment_id'],
            selected_code_ref=selected['code_ref'], workspace_code_ref=workspace_ref,
            workspace_matches_selection=workspace_ref == selected['code_ref'],
            unfinished=state['unfinished'], budget_used=state['budget_used'],
            next_action=state['next_action'], report=report['output'],
            limitation='Synthetic observations only; registered reviews/results and report are mock artifacts, not ML validity. No ML, Git commits or external submission. '
                       'The hold example preserves candidate workspace bytes separately from the baseline selection.',
        )
        (self.output / 'summary.json').write_text(dumps(summary), encoding='utf-8')
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory under an existing parent')
    parser.add_argument('--scenario', choices=('comparable', 'scope-mismatch'), default='comparable')
    args = parser.parse_args()
    try:
        summary = MockCycle(args.output.absolute(), args.scenario).run()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f'Mock cycle failed; existing or partial files preserved: {exc}\n')
    print(dumps(summary, ensure_ascii=True), end='')


if __name__ == '__main__':
    main()
