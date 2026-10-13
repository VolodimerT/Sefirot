"""Synthetic full-time API packets: coverage, missing counts and leakage checks."""
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.cli import main
from sefirot.small_market import review_small_market
from test_operations_upgrade import NOW, packet, row, stamp, reseal


def statistics(fid, value=10, *, hours=-.5, metric='Total Shots', team=1):
    p = packet([{'team': {'id': team, 'name': 'Team A'}, 'statistics': [{'type': metric, 'value': value}]},
                {'team': {'id': 2, 'name': 'Team B'}, 'statistics': [{'type': metric, 'value': 6}]}], hours)
    p['data']['get'] = 'fixtures/statistics'; p['data']['parameters'] = {'fixture': str(fid)}
    p['receipt']['endpoint'] = '/fixtures/statistics'; p['receipt']['parameters'] = {'fixture': str(fid)}
    return reseal(p)


def data(n=13, metric='SHOTS'):
    return {'schema': 'small-market-input-v1', 'as_of': stamp(), 'fixture_id': 100, 'team_id': 1,
            'profile': 'LOWER', 'metric': metric,
            'fixture_packets': [packet([row(100, status='NS', hours=3),
                                       *[row(10+i, hours=-500+i*24) for i in range(n)]], -1)],
            'statistic_packets': [statistics(10+i, 10 if i < 10 else 100) for i in range(n)]}


class SmallMarketTests(unittest.TestCase):
    def review(self, d=None): return review_small_market(d or data(), stamp())

    def test_long_and_recent_are_disjoint_and_shrink_towards_long(self):
        out = self.review()
        self.assertEqual(out['long_fixture_ids'], list(range(10, 20)))
        self.assertEqual(out['recent_fixture_ids'], [20, 21, 22])
        self.assertFalse(set(out['long_fixture_ids']) & set(out['recent_fixture_ids']))
        self.assertEqual(out['long_mean'], 10)
        self.assertEqual(out['recent_mean'], 100)
        self.assertAlmostEqual(out['shrunk_recent_mean'], 10+90*3/13)
        self.assertEqual(out['status'], 'DESCRIPTIVE_RESEARCH_ONLY')
        self.assertIsNone(out['probability']); self.assertIsNone(out['ev'])
        self.assertEqual(out['stake'], 0.)
        self.assertIn('SMALL_MARKET_MODEL_UNVALIDATED', out['blockers'])

    def test_three_good_games_cannot_supply_a_long_baseline(self):
        out = self.review(data(3))
        self.assertIsNone(out['long_mean']); self.assertIsNone(out['shrunk_recent_mean'])
        self.assertEqual(out['status'], 'INSUFFICIENT_BASELINE')
        self.assertIn('LONG_BASELINE_INSUFFICIENT', out['blockers'])

    def test_null_is_missing_but_zero_is_real_observation(self):
        d = data(); d['statistic_packets'][0] = statistics(10, None); d['statistic_packets'][1] = statistics(11, 0)
        out = self.review(d)
        self.assertEqual(out['eligible_games'], 12)
        self.assertEqual(out['exclusion_reasons']['NULL_OR_MISSING_STATISTIC'], 1)
        self.assertEqual(next(r['count'] for r in out['observations'] if r['fixture_id'] == 11), 0)

    def test_repeated_snapshots_do_not_multiply_matches_and_corrections_quarantined(self):
        d = data(); d['statistic_packets'].append(copy.deepcopy(d['statistic_packets'][0]))
        d['fixture_packets'].append(copy.deepcopy(d['fixture_packets'][0]))
        self.assertEqual(self.review(d)['eligible_games'], 13)
        d['statistic_packets'].append(statistics(10, 99))
        out = self.review(d)
        self.assertEqual(out['eligible_games'], 12)
        self.assertEqual(out['exclusion_reasons']['STATISTICS_REVISION_CONFLICT'], 1)

    def test_wrong_team_and_missing_post_ft_statistics_do_not_fill_history(self):
        d = data(); d['statistic_packets'][0] = statistics(10, team=99)
        d['statistic_packets'][1] = statistics(11, hours=-2)
        out = self.review(d)
        self.assertEqual(out['eligible_games'], 11)
        self.assertEqual(out['exclusion_reasons']['STATISTICS_TEAM_MISMATCH'], 1)
        self.assertEqual(out['exclusion_reasons']['NO_POST_FT_STATISTICS'], 1)

    def test_future_packet_and_old_game_excluded_before_aggregation(self):
        d = data(); d['statistic_packets'][0] = statistics(10, hours=1)
        d['fixture_packets'][0]['data']['response'][2] = row(11, hours=-24*731)
        reseal(d['fixture_packets'][0]); out = self.review(d)
        self.assertEqual(out['future_packets_excluded'], 1)
        self.assertEqual(out['eligible_games'], 11)
        self.assertEqual(out['exclusion_reasons']['HISTORY_CUTOFF'], 1)

    def test_aet_live_cancelled_foreign_league_and_score_correction_excluded(self):
        d = data()
        for index, status in enumerate(('AET', '1H', 'CANC')):
            d['fixture_packets'][0]['data']['response'][index+1]['fixture']['status']['short'] = status
        d['fixture_packets'][0]['data']['response'][4]['league']['id'] = 99
        reseal(d['fixture_packets'][0]); d['fixture_packets'].append(packet([row(14, hours=-404, score=(0, 0))], -.7))
        out = self.review(d)
        self.assertEqual(out['eligible_games'], 8)
        self.assertEqual(out['exclusion_reasons']['NOT_REGULATION_FT'], 3)
        self.assertEqual(out['exclusion_reasons']['RESULT_REVISION_CONFLICT'], 1)

    def test_half_error_partial_duplicate_type_negative_bool_string_rejected(self):
        for change in ('half', 'errors', 'paging', 'duplicate', 'negative', 'bool', 'string', 'count', 'credential'):
            d = data(); p = d['statistic_packets'][0]
            if change == 'half': p['receipt']['parameters']['half'] = '1'
            if change == 'errors': p['data']['errors'] = {'plan': 'restricted'}
            if change == 'paging': p['data']['paging']['total'] = 2
            if change == 'duplicate': p['data']['response'][0]['statistics'] *= 2
            if change in ('negative', 'bool', 'string'): p['data']['response'][0]['statistics'][0]['value'] = {'negative': -1, 'bool': True, 'string': '10'}[change]
            if change == 'count': p['data']['results'] = 0
            if change == 'credential': p['receipt']['parameters']['apiKey'] = 'secret-test'
            reseal(p)
            with self.subTest(change=change), self.assertRaises(ValueError): self.review(d)

    def test_cards_referee_gate_cannot_be_satisfied_by_fouls(self):
        d = data(metric='CARDS')
        out = self.review(d)
        self.assertEqual(out['eligible_games'], 0)
        self.assertIn('REFEREE_GATE_UNSUPPORTED', out['blockers'])
        d['statistic_packets'] = [statistics(10+i, 4, metric='Yellow Cards') for i in range(13)]
        self.assertIn('REFEREE_GATE_UNSUPPORTED', self.review(d)['blockers'])

    def test_shots_sot_corners_fouls_are_distinct_types(self):
        for key, metric in (('SOT', 'Shots on Goal'), ('CORNERS', 'Corner Kicks'), ('FOULS', 'Fouls')):
            d = data(metric=key)
            self.assertEqual(self.review(d)['eligible_games'], 0)
            d['statistic_packets'] = [statistics(10+i, 4, metric=metric) for i in range(13)]
            self.assertEqual(self.review(d)['eligible_games'], 13)

    def test_live_target_future_cutoff_wrong_team_and_manual_odds_rejected(self):
        for change in ('live', 'future', 'team', 'manual', 'identity'):
            d = data()
            if change == 'live': d['fixture_packets'][0]['data']['response'][0]['fixture']['status']['short'] = '1H'; reseal(d['fixture_packets'][0])
            if change == 'future': d['as_of'] = stamp(1)
            if change == 'team': d['team_id'] = 99
            if change == 'manual': d['odds'] = 1.77
            if change == 'identity': d['fixture_packets'].append(packet([row(100, home=99, status='NS', hours=3)], -.5))
            with self.subTest(change=change), self.assertRaises(ValueError): self.review(d)

    def test_outlier_and_venue_are_diagnostics_not_admission(self):
        d = data(); d['statistic_packets'][0] = statistics(10, 200)
        out = self.review(d)
        self.assertEqual(out['largest_long_fixture_id'], 10)
        self.assertEqual(out['mean_without_largest_long'], 10)
        self.assertGreater(out['long_mean'], out['mean_without_largest_long'])
        self.assertFalse(out['monetary_permission']); self.assertFalse(out['holdout_eligible'])

    def test_next_opponent_allowed_uses_other_team_count_and_missing_remains_missing(self):
        out = self.review()
        allowed = out['opponent_allowed_baseline']
        self.assertEqual(allowed['team_id'], 2)
        self.assertEqual(allowed['long_mean'], 10)
        self.assertEqual(allowed['recent_mean'], 100)
        self.assertTrue(allowed['sufficient_long_baseline'])
        d = data()
        # Only the target team block is available: next-opponent history is absent.
        for p in d['statistic_packets']:
            p['data']['response'].pop(); p['data']['results'] = 1; reseal(p)
        out = self.review(d)
        self.assertEqual(out['eligible_games'], 13)
        self.assertIsNone(out['opponent_allowed_baseline']['long_mean'])
        self.assertIn('OPPONENT_ALLOWED_BASELINE_INSUFFICIENT', out['blockers'])

    def test_receipt_cannot_rebind_statistics_to_a_different_fixture(self):
        d = data(); d['statistic_packets'][0]['receipt']['parameters']['fixture'] = '999'
        with self.assertRaisesRegex(ValueError, 'query differs'): self.review(d)

    def test_cli_creates_report_without_ledger_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); inp = root/'input.json'; out = root/'review.json'; db = root/'absent.sqlite'
            inp.write_text(json.dumps(data()), encoding='utf-8')
            with patch('sefirot.cli.datetime') as clock, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                clock.now.return_value = NOW
                self.assertEqual(main(['--db', str(db), 'small-market-review', str(inp), '--output', str(out)]), 0)
                self.assertEqual(main(['--db', str(db), 'small-market-review', str(inp), '--output', str(out)]), 2)
            self.assertFalse(db.exists()); self.assertIsNone(json.loads(out.read_text())['probability'])
