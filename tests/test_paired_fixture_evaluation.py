"""Owned correlated-market regressions; synthetic evidence never certifies a model."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import Policy
from sefirot.feedback import compare_versions
from sefirot.service import Service


def pairs(fixtures=60, markets=1, days=10, delta=.2):
    old = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(fixtures):
        for market in range(markets):
            old.append({'match_id': str(i), 'market': str(market),
                        'model_id': 'old', 'outcome': 'WIN', 'brier': .4,
                        'kickoff': (start + timedelta(days=i % days)).isoformat()})
    new = [{**r, 'model_id': 'new', 'brier': r['brier'] - delta} for r in old]
    return old, new


class PairedFixtureEvaluationTests(unittest.TestCase):
    def test_nine_fixtures_seven_markets_do_not_satisfy_holdout(self):
        for delta in (.2, -.2):
            old, new = pairs(9, 7, 9, delta)
            report = compare_versions(old, new, Policy())
            self.assertEqual(report['recommendation'], 'KEEP_SHADOW')
            self.assertEqual(report['n'], 63)  # Backwards-compatible row count.
            self.assertEqual(report['distinct_fixtures'], 9)
            self.assertEqual(report['date_blocks'], 9)
            self.assertIn('HOLDOUT_FIXTURES_TOO_SMALL', report['limitations'])

    def test_single_date_does_not_become_sixty_independent_days(self):
        old, new = pairs(days=1)
        report = compare_versions(old, new, Policy())
        self.assertEqual(report['recommendation'], 'KEEP_SHADOW')
        self.assertIsNone(report['interval'])
        self.assertEqual(report['date_blocks'], 1)

    def test_missing_kickoff_never_uses_result_receipt_as_game_date(self):
        old, new = pairs()
        for r in old + new:
            r.pop('kickoff')
            r['received_at'] = '2026-01-30T00:00:00Z'
        report = compare_versions(old, new, Policy())
        self.assertEqual(report['recommendation'], 'KEEP_SHADOW')
        self.assertIsNone(report['interval'])
        self.assertIn('KICKOFF_DATE_UNAVAILABLE', report['limitations'])

    def test_minimum_date_blocks_reuses_existing_exploratory_method(self):
        old, new = pairs(days=7)
        report = compare_versions(old, new, Policy())
        self.assertEqual(report['recommendation'], 'KEEP_SHADOW')
        self.assertIsNone(report['interval'])

    def test_sixty_distinct_fixtures_and_ten_dates_can_review_not_certify(self):
        old, new = pairs()
        for records, expected in (((old, new), 'REVIEW_PROMOTION'),
                                  ((new, old), 'ROLLBACK')):
            report = compare_versions(*records, Policy())
            self.assertEqual(report['recommendation'], expected)
            self.assertEqual(report['distinct_fixtures'], 60)
            self.assertFalse(report['certifies_model'])
            self.assertIn('UTC-day cluster bootstrap', report['interval_method'])

    def test_fixture_mean_not_market_volume_weights_improvement(self):
        old, new = pairs(60, 1, 10, 0.)
        new[0]['brier'] = .1
        for j in range(1, 7):
            old.append({**old[0], 'market': str(j)})
            new.append({**new[0], 'market': str(j)})
        report = compare_versions(old, new, Policy())
        self.assertAlmostEqual(report['improvement'], .3 / 60)
        self.assertEqual(report['n'], 66)

    def test_duplicate_markets_do_not_narrow_date_cluster_interval(self):
        old, new = pairs()
        for i, r in enumerate(new):
            r['brier'] = .4 - (.2 if i % 10 < 5 else -.1)
        first = compare_versions(old, new, Policy())
        many_old = [{**r, 'market': str(j)} for r in old for j in range(7)]
        many_new = [{**r, 'market': str(j)} for r in new for j in range(7)]
        repeated = compare_versions(many_old, many_new, Policy())
        self.assertEqual(first['interval'], repeated['interval'])
        self.assertEqual(first['improvement'], repeated['improvement'])
        self.assertLess(first['interval'][0], first['interval'][1])

    def test_kickoff_identity_must_match_across_models_and_markets(self):
        old, new = pairs(markets=2)
        new[0]['kickoff'] = '2026-01-20T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'kickoff'):
            compare_versions(old, new, Policy())
        old, new = pairs(markets=2)
        old[0]['kickoff'] = new[0]['kickoff'] = '2026-01-20T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'kickoff'):
            compare_versions(old, new, Policy())

    def test_utc_date_uses_instant_not_timestamp_prefix(self):
        old, new = pairs()
        for records in (old, new):
            records[0]['kickoff'] = '2026-01-02T01:00:00+02:00'
        self.assertEqual(compare_versions(old, new, Policy())['date_blocks'], 10)

    def test_equivalent_offsets_preserve_paired_fixture_identity(self):
        old, new = pairs(markets=2)
        expected = compare_versions(old, new, Policy())
        for r in new:
            stamp = datetime.fromisoformat(r['kickoff'])
            r['kickoff'] = stamp.astimezone(timezone(timedelta(hours=3))).isoformat()
        self.assertEqual(compare_versions(old, new, Policy()), expected)

    def test_unpaired_rows_do_not_count_towards_fixture_minimum(self):
        old, new = pairs(59)
        old.append({**old[0], 'match_id': 'old-only'})
        new.append({**new[0], 'match_id': 'new-only'})
        report = compare_versions(old, new, Policy())
        self.assertEqual(report['distinct_fixtures'], 59)
        self.assertEqual(report['unpaired_old'], 1)
        self.assertEqual(report['unpaired_new'], 1)
        self.assertEqual(report['recommendation'], 'KEEP_SHADOW')

    def test_empty_pairs_have_no_invented_interval(self):
        report = compare_versions([], [], Policy())
        self.assertEqual(report['recommendation'], 'KEEP_SHADOW')
        self.assertIsNone(report['interval'])
        self.assertEqual(report['distinct_fixtures'], 0)

    def test_non_finite_and_boolean_scores_are_refused(self):
        for value in (float('nan'), float('inf'), True, -.1, 1.1):
            old, new = pairs()
            new[0]['brier'] = value
            with self.assertRaises(ValueError):
                compare_versions(old, new, Policy())

    def test_results_are_deterministic_order_independent_and_leave_inputs_untouched(self):
        old, new = pairs(markets=3)
        before = deepcopy((old, new))
        first = compare_versions(old, new, Policy())
        self.assertEqual(first, compare_versions(old[::-1], new[::-1], Policy()))
        self.assertEqual((old, new), before)

    def test_correlated_small_cohort_cannot_trigger_service_rollback(self):
        old, new = pairs(9, 7, 9, -.2)
        service = object.__new__(Service)
        service.policy = Policy()
        service._time = Mock()
        service._records = Mock(return_value=old + new)
        service.repo = MagicMock()
        service.repo.all.return_value = [{'model_id': 'new', 'at': '2026-02-01T00:00:00Z', 'id': 'route'}]
        service.repo.transaction.return_value.__enter__ = Mock()
        service.repo.transaction.return_value.__exit__ = Mock(return_value=False)
        service.activate = Mock()
        report = service.compare_and_rollback('old', 'new', '2026-02-02T00:00:00Z')
        self.assertFalse(report['rolled_back'])
        service.activate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
