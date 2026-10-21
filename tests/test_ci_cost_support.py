"""CI diagnostics retain numeric attribution, not raw fixture content."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ci_cost_support as support


class CICostSupportTests(unittest.TestCase):
    def test_partition_excludes_overlapping_provider_and_milestones(self):
        events = [dict(kind=k, seconds=s) for k, s in (
            ('zar_cli', 5), ('git', 2), ('training', 1), ('server_shutdown', 1),
            ('provider', 3), ('git_commit', 2), ('approval', 0))]
        row = support.utility_partition(events, 12)
        self.assertEqual(row['partition_seconds']['other'], 3)
        self.assertEqual(sum(row['partition_seconds'].values()), 12)
        self.assertEqual(row['event_counts']['provider'], 1)
        with self.assertRaises(ValueError):
            support.utility_partition(events, 8)

    def test_disabled_diagnostics_never_read_or_write(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(support, 'write') as write:
            support.write_utility_costs(Path('/not/a/fixture'), {}, 1)
            support.write_local_costs({}, 1)
            write.assert_not_called()

    def test_utility_report_has_only_selected_numeric_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            summary = {'trials': [dict(repeat=1, arms={})]}
            for arm in ('direct', 'zar'):
                dest = root / 'fixture/trial-1' / arm
                dest.mkdir(parents=True)
                (dest / 'events.json').write_text(json.dumps([
                    dict(kind='zar_cli', phase='setup', seconds=2, argv=['SECRET'], response='SECRET'),
                    dict(kind='provider', seconds=1, credential='SECRET')]), encoding='utf-8')
                summary['trials'][0]['arms'][arm] = dict(seconds=dict(total=4, setup=3, secret='SECRET'))
            with patch.dict(os.environ, ZAR_CI_COST_DIR=str(root / 'reports')):
                support.write_utility_costs(root / 'fixture', summary, 10)
            text = (root / 'reports/workflow-utility.json').read_text(encoding='utf-8')
            self.assertNotIn('SECRET', text)
            self.assertNotIn(str(root), text)
            report = json.loads(text)
            self.assertEqual(report['trials'][0]['arms']['zar']['setup_other_seconds'], 1)
            self.assertEqual(report['test_elapsed_seconds'], 10)
            self.assertEqual(report['verification_and_test_overhead_seconds'], 2)
            self.assertEqual(report['trials'][0]['arms']['zar']['phase_diagnostics_seconds'], {'setup': 3})

    def test_local_report_filters_unknown_nested_fields(self):
        row = dict(total_seconds=2, partition_seconds=dict(cli=1, worker_other=1, secret='SECRET'),
                   verified=dict(credential='SECRET'), profile=dict(argv='SECRET'))
        summary = dict(configurations={n: dict(profile_cli=n == 'profiled', poll_interval=.01, secret='SECRET')
                                       for n in support.NAMES},
                       trials=[dict(repeat=1, results={n: row for n in support.NAMES}, secret='SECRET')],
                       median={n: row for n in support.NAMES},
                       paired_deltas_seconds=[dict(repeat=1, profiling=0, short_poll=0, secret='SECRET')],
                       source_sha256={'/private/secret': 'SECRET'})
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, ZAR_CI_COST_DIR=temp):
                support.write_local_costs(summary, 9)
            text = (Path(temp) / 'local-loop-costs.json').read_text(encoding='utf-8')
            self.assertNotIn('SECRET', text)
            self.assertNotIn('/private/secret', text)
            report = json.loads(text)
            self.assertEqual(report['verification_and_test_overhead_seconds'], 3)
            self.assertEqual(report['trials'][0]['results']['baseline']['partition_seconds'], {'cli': 1, 'worker_other': 1})
