"""V7 coverage, chronology and queue regressions on a dedicated SQLite repo."""
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest

from test_football_pipeline import fixture, packet, stats, NOW
from research import football_pipeline as pipeline
from research.football_intelligence_v7.data import inspect
from research.football_intelligence_v7.tactical import profile
from sefirot.contracts import canonical, digest
from sefirot.repository import Repository


class V7DataTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Repository(Path(directory.name) / 'sources.sqlite')
        self.addCleanup(self.repo.close)

    def put(self, value, imported_at=NOW):
        return pipeline.ingest(self.repo, canonical(value).encode(), imported_at=imported_at)

    def test_local_availability_and_ft_gate(self):
        self.put(packet())
        self.put(stats(), '2026-10-17T12:05:00Z')
        early = inspect(self.repo, [(39, 2026)], as_of=NOW)
        self.assertEqual(early['leagues'][0]['paired_fields']['SHOTS'], 0)
        self.assertEqual(early['queue']['queries'][-1]['params'], {'fixture': 10})
        late = inspect(self.repo, [(39, 2026)], as_of='2026-10-17T12:06:00Z')
        league = late['leagues'][0]
        self.assertEqual(league['field_denominator_ft'], 1)
        self.assertEqual(league['paired_fields']['SHOTS'], 1)
        self.assertEqual(league['paired_fields']['SOT'], 0)
        self.assertFalse(any(q['endpoint'] == 'fixtures/statistics' for q in late['queue']['queries']))
        team = next(row for row in late['teams'] if row['team_id'] == 1)
        self.assertEqual(team['coverage']['CORNERS'], 1)
        views = profile(late, 20)
        self.assertEqual(views['venue_split']['home']['evidence']['SHOT_VOLUME']['mean'], 12)
        self.assertEqual(views['venue_split']['away']['evidence']['CHANCE_QUALITY_XG']['mean'], None)
        self.assertTrue(views['venue_split']['home']['evidence']['SHOT_VOLUME']['source_ids'])
        self.assertEqual(views['tactical_fit'], 'UNVERIFIED')
        self.assertEqual(views['decision'], 'PASS')

    def test_post_ft_statistics_conflicts_exclude_field(self):
        self.put(packet())
        wrong = stats()
        wrong['data']['response'][0]['statistics'][1]['value'] = 5
        wrong['receipt']['payload_hash'] = digest(wrong['data'])
        self.put(wrong)
        self.put(stats())
        result = inspect(self.repo, [(39, 2026)], as_of=NOW)
        self.assertEqual(result['leagues'][0]['paired_fields']['SHOTS'], 0)
        self.assertEqual(result['leagues'][0]['paired_fields']['CORNERS'], 1)
        self.assertEqual(result['fixtures'][0]['stat_issue'], 'STATISTICS_FIELD_CONFLICT')

    def test_live_count_and_reimport_cannot_stand_in_for_history(self):
        self.put(packet())
        live = stats('2026-10-14T12:15:00Z')
        self.put(live)
        retry = self.put(live, '2026-10-17T13:00:00Z')
        self.assertFalse(retry['added_source'])
        result = inspect(self.repo, [(39, 2026)], as_of='2026-10-17T13:01:00Z')
        self.assertEqual(result['leagues'][0]['paired_fields']['SHOTS'], 0)
        self.assertEqual(sum(q['endpoint'] == 'fixtures/statistics' for q in result['queue']['queries']), 0)

    def test_priority_context_before_history_then_lineup_and_ft(self):
        self.put(packet(rows=[fixture(20, 'NS'), fixture(21, 'NS')]))
        def read(at):
            return inspect(self.repo, [(39, 2026)], as_of=at)['queue']
        queue = read('2026-10-18T11:00:00Z')
        self.assertEqual([(q['category'], q['params']) for q in queue['queries'][:2]],
                         [('CONTEXT', {'id': 20}), ('CONTEXT', {'id': 21})])
        self.put(packet('fixtures', {'id': 20}, [fixture(20, 'NS')], '2026-10-18T11:05:00Z'),
                 '2026-10-18T11:06:00Z')
        coverage = [{'league': {'id': 39}, 'seasons': [{'year': 2026, 'coverage': {'fixtures': {'lineups': True}}}]}]
        self.put(packet('leagues', {'id': 39, 'season': 2026}, coverage, '2026-10-18T11:06:00Z'),
                 '2026-10-18T11:07:00Z')
        queue = read('2026-10-18T11:08:00Z')
        self.assertTrue(any(q['category'] == 'LINEUPS' and q['params'] == {'fixture': 20}
                            for q in queue['queries']))
        self.assertFalse(any(q['category'] in ('LINEUPS','CONTEXT')
                             for q in read('2026-10-18T11:40:00Z')['queries']))
        self.assertTrue(any(q['category'] == 'FT' for q in read('2026-10-18T15:15:00Z')['queries']))
        self.assertFalse(any(q['category'] == 'FT' for q in read('2026-10-21T15:15:00Z')['queries']))

    def test_unresolved_query_stays_parked_across_days(self):
        self.put(packet())
        intent = {'schema': pipeline.ATTEMPT, 'id': 'test-bounded-intent', 'at': NOW,
                  'query': {'endpoint': 'fixtures/statistics', 'params': {'fixture': 10}},
                  'league': 39, 'season': 2026}
        with self.repo.transaction():
            pipeline._append(self.repo, intent)
        for at in [NOW, '2026-10-19T12:00:00Z']:
            queue = inspect(self.repo, [(39, 2026)], as_of=at)['queue']
            self.assertEqual(queue['unresolved_queries'], 1)
            self.assertFalse(any(q['endpoint'] == 'fixtures/statistics' for q in queue['queries']))
            self.assertFalse(queue['execution_enabled'])

    def test_future_qc_failure_does_not_change_frozen_queue(self):
        self.put(packet())
        before = inspect(self.repo, [(39, 2026)], as_of=NOW)['queue']
        bad = stats()
        bad['receipt']['payload_hash'] = 'a' * 64
        self.assertFalse(self.put(bad, '2026-10-17T13:00:00Z')['accepted'])
        self.assertEqual(inspect(self.repo, [(39, 2026)], as_of=NOW)['queue'], before)
        later = inspect(self.repo, [(39, 2026)], as_of='2026-10-17T13:01:00Z')['queue']
        self.assertTrue(later['quality_fenced'])
        self.assertEqual(later['queries'], [])

    def test_lineup_requires_two_full_XI_before_start(self):
        self.put(packet())
        lineups = [{'team': {'id': tid}, 'startXI': [{'player': {'id': tid*100+i}}
                    for i in range(11)]} for tid in (1, 2)]
        p = packet('fixtures/lineups', {'fixture': 20}, lineups, '2026-10-18T11:00:00Z')
        p['data']['response'][0]['startXI'][0]['player']['id'] = True
        p['receipt']['payload_hash'] = digest(p['data'])
        self.put(p, '2026-10-18T11:01:00Z')
        before = inspect(self.repo, [(39, 2026)], as_of='2026-10-18T11:10:00Z')
        self.assertEqual(before['leagues'][0]['prematch_lineups'], 0)
        p['data']['response'][0]['startXI'][0]['player']['id'] = 100
        p['receipt']['payload_hash'] = digest(p['data'])
        self.put(p, '2026-10-18T12:02:00Z')
        before = inspect(self.repo, [(39, 2026)], as_of='2026-10-18T11:59:00Z')
        self.assertEqual(before['leagues'][0]['prematch_lineups'], 0)


    def test_bound_complete_lineup_retains_original_source_id(self):
        self.put(packet())
        observed = '2026-10-18T11:00:00Z'
        lineups = [{'team': {'id': tid}, 'startXI': [{'player': {'id': tid*100+i}}
                    for i in range(11)]} for tid in (1, 2)]
        accepted = self.put(packet('fixtures/lineups', {'fixture': 20}, lineups, observed), observed)
        result = inspect(self.repo, [(39, 2026)], as_of='2026-10-18T11:15:00Z')
        self.assertEqual(result['leagues'][0]['prematch_lineups'], 1)
        self.assertEqual(profile(result, 20)['lineup_source_ids'], [accepted['source_id']])


class V7SettlementTests(unittest.TestCase):
    def test_node_reference_and_production_grade_parity(self):
        root = Path(__file__).resolve().parents[1]
        run = subprocess.run([shutil.which('node') or 'node', '--test',
                              'research/football_intelligence_v7/settlement_reference.test.mjs'],
                             cwd=root, capture_output=True, encoding='utf-8', timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
