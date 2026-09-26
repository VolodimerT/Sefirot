import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot_core import (Fact, SportsOnlySnapshot, ThreeWayQuote, HistoricalMatch,
                          InsufficientHistory, estimate_1x2, seal_estimate, evaluate_1x2)

BASE = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)


def fixture():
    snapshot = SportsOnlySnapshot("target", BASE+timedelta(hours=3), BASE, (
        Fact("sports.home_team", "A", "fixture-feed", BASE-timedelta(days=1), BASE-timedelta(hours=2)),
        Fact("sports.away_team", "B", "fixture-feed", BASE-timedelta(days=1), BASE-timedelta(hours=2)),
    ))
    history = tuple(HistoricalMatch(
        f"past-{n}", BASE-timedelta(days=10-n), BASE-timedelta(days=10-n)+timedelta(hours=2),
        "A" if n%2 else "C", "B" if n%2 else "A", n%3, (n+1)%2, "results-feed")
        for n in range(1,8))
    return snapshot, history


class IndependentHistoryTests(unittest.TestCase):
    def test_probability_is_finite_sums_to_one_and_explicitly_uncalibrated(self):
        snapshot, history = fixture()
        result = estimate_1x2(snapshot, history)
        self.assertAlmostEqual(sum(result.probabilities), 1.0)
        self.assertTrue(all(0 <= lo <= p <= hi <= 1
                            for lo,p,hi in zip(result.low,result.probabilities,result.high)))
        self.assertEqual(result.interval_status, "UNCALIBRATED")
        self.assertGreaterEqual(result.min_team_games, 3)

    def test_future_results_and_late_receipts_never_change_past_prediction(self):
        snapshot, history = fixture()
        base = estimate_1x2(snapshot, history)
        future = HistoricalMatch("future", BASE+timedelta(days=1), BASE+timedelta(days=1,hours=3),
                                 "A", "B", 99, 0, "feed")
        late = HistoricalMatch("late", BASE-timedelta(hours=4), BASE+timedelta(minutes=1),
                               "A", "B", 0, 99, "feed")
        compare = estimate_1x2(snapshot, history+(future, late))
        self.assertEqual(compare.probabilities, base.probabilities)
        self.assertEqual(compare.used_matches, base.used_matches)
        self.assertEqual(compare.excluded_future, 2)

    def test_earlier_received_result_can_update_next_version(self):
        snapshot, history = fixture()
        extra = HistoricalMatch("new", BASE-timedelta(hours=4), BASE-timedelta(hours=1),
                                "A", "B", 6, 0, "feed")
        new = estimate_1x2(snapshot, history+(extra,))
        self.assertIn("new", new.used_matches)
        self.assertNotEqual(new.probabilities, estimate_1x2(snapshot, history).probabilities)

    def test_no_unseen_team_is_silently_assigned_a_confident_rating(self):
        snapshot, history = fixture()
        unknown = SportsOnlySnapshot("target", snapshot.kickoff, snapshot.as_of, (
            snapshot.facts[0], Fact("sports.away_team", "NEW", "fixture-feed",
                                    BASE-timedelta(days=1), BASE-timedelta(hours=2))))
        with self.assertRaises(InsufficientHistory):
            estimate_1x2(unknown, history)

    def test_model_to_seal_to_price_keeps_the_monetary_gate_closed(self):
        snapshot, history = fixture()
        estimate = estimate_1x2(snapshot, history)
        seal = seal_estimate(snapshot, estimate, BASE+timedelta(minutes=1))
        quote = ThreeWayQuote("book", BASE+timedelta(minutes=2), (1.8, 4.0, 6.0))
        report = evaluate_1x2(snapshot, seal, quote)
        self.assertEqual(report["monetary_verdict"], "PASS")
        self.assertEqual(report["interval_status"], "UNCALIBRATED")
        self.assertTrue(all(report["ev_low"][key] <= report["ev"][key] <= report["ev_high"][key]
                            for key in ("home", "draw", "away")))

    def test_history_validations_and_duplicate_match_ids(self):
        snapshot, history = fixture()
        with self.assertRaises(ValueError):
            estimate_1x2(snapshot, history+(history[0],))
        with self.assertRaises(ValueError):
            HistoricalMatch("bad", BASE, BASE-timedelta(seconds=1), "A", "B", 1, 0, "feed")
        with self.assertRaises(ValueError):
            HistoricalMatch("bad", BASE, BASE+timedelta(hours=1), "A", "B", -1, 0, "feed")

    def test_utc_normalization_and_deterministic_order(self):
        snapshot, history = fixture()
        equivalent = SportsOnlySnapshot(snapshot.match_id, snapshot.kickoff,
                                        snapshot.as_of.astimezone(timezone(timedelta(hours=3))), snapshot.facts)
        self.assertEqual(estimate_1x2(snapshot, history), estimate_1x2(equivalent, tuple(reversed(history))))


if __name__ == "__main__":
    unittest.main()
