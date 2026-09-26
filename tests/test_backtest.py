import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot_core import (Fact, SportsOnlySnapshot, HistoricalMatch,
                          BacktestCase, multiclass_brier, walk_forward_1x2)

BASE = datetime(2026, 9, 26, 10, tzinfo=timezone.utc)


def case_at(moment, match_id, home, away, home_goals, away_goals):
    snap = SportsOnlySnapshot(match_id, moment+timedelta(hours=1), moment, (
        Fact("sports.home_team", home, "fixture-feed", moment-timedelta(hours=3), moment-timedelta(hours=2)),
        Fact("sports.away_team", away, "fixture-feed", moment-timedelta(hours=3), moment-timedelta(hours=2)),
    ))
    result = HistoricalMatch(match_id, snap.kickoff, snap.kickoff+timedelta(hours=2),
                             home, away, home_goals, away_goals, "result-feed")
    return BacktestCase(snap, result)


class BacktestSafetyTests(unittest.TestCase):
    def test_brier_known_endpoints(self):
        self.assertEqual(multiclass_brier((1., 0., 0.), 0), 0)
        self.assertEqual(multiclass_brier((1., 0., 0.), 1), 2)
        with self.assertRaises(ValueError):
            multiclass_brier((.6, .6, -.2), 0)

    def test_future_target_result_never_enters_its_own_prediction(self):
        past = tuple(case_at(BASE-timedelta(days=10-n), f"past-{n}",
                             "A" if n%2 else "C", "B" if n%2 else "A", n%3, n%2).eventual_result
                     for n in range(1, 8))
        target = case_at(BASE, "target", "A", "B", 1, 0)
        report = walk_forward_1x2(past+(target.eventual_result,), (target,))
        self.assertEqual(len(report.records), 1)
        self.assertNotIn("target", report.records[0].used_matches)
        self.assertEqual(len(report.records[0].used_matches), len(past))
        self.assertEqual(report.mean_brier, report.records[0].brier)
        changed = case_at(BASE, "target", "A", "B", 0, 7)
        alternate = walk_forward_1x2(past+(changed.eventual_result,), (changed,))
        self.assertEqual(report.records[0].probabilities, alternate.records[0].probabilities)
        self.assertNotEqual(report.mean_brier, alternate.mean_brier)

    def test_unknown_teams_report_insufficient_history_instead_of_made_up_score(self):
        target = case_at(BASE, "target", "A", "B", 2, 1)
        report = walk_forward_1x2((target.eventual_result,), (target,))
        self.assertEqual(report.records, ())
        self.assertEqual(report.insufficient_history, ("target",))
        self.assertIsNone(report.mean_brier)

    def test_mismatched_result_is_rejected(self):
        target = case_at(BASE, "target", "A", "B", 2, 1)
        another = case_at(BASE, "different", "A", "B", 2, 1)
        with self.assertRaises(ValueError):
            walk_forward_1x2((), (BacktestCase(target.snapshot, another.eventual_result),))

    def test_duplicate_case_is_rejected(self):
        target = case_at(BASE, "target", "A", "B", 2, 1)
        with self.assertRaises(ValueError):
            walk_forward_1x2((), (target, target))


if __name__ == "__main__":
    unittest.main()
