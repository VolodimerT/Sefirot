import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot_core import Fact, SportsOnlySnapshot, ProbabilitySeal, ThreeWayQuote, evaluate_1x2

BASE = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)


def fixture():
    snapshot = SportsOnlySnapshot(
        "demo", BASE + timedelta(hours=2), BASE,
        (Fact("sports.roster", "confirmed", "source-a", BASE - timedelta(hours=1), BASE - timedelta(minutes=30)),),
    )
    seal = ProbabilitySeal.create(snapshot, "demo-v0", BASE + timedelta(minutes=1), (.6, .25, .15))
    quote = ThreeWayQuote("book-a", BASE + timedelta(minutes=2), (1.8, 4.0, 6.0))
    return snapshot, seal, quote


class CoreContractTests(unittest.TestCase):
    def test_numerical_example_and_no_monetary_admission(self):
        snapshot, seal, quote = fixture()
        out = evaluate_1x2(snapshot, seal, quote)
        self.assertAlmostEqual(out["implied"]["home"], 1/1.8)
        self.assertAlmostEqual(out["ev"]["home"], .08)
        self.assertEqual(out["monetary_verdict"], "PASS")

    def test_overround_uses_all_three_prices(self):
        snapshot, seal, _ = fixture()
        quote = ThreeWayQuote("book-a", BASE + timedelta(minutes=2), (2.0, 3.5, 4.0))
        self.assertAlmostEqual(evaluate_1x2(snapshot, seal, quote)["overround"], 1/2+1/3.5+1/4-1)

    def test_future_fact_is_rejected_even_when_event_occurred_earlier(self):
        later_received = Fact("sports.roster", "confirmed", "source-a", BASE-timedelta(hours=1), BASE+timedelta(minutes=1))
        with self.assertRaises(ValueError):
            SportsOnlySnapshot("demo", BASE+timedelta(hours=2), BASE, (later_received,))

    def test_price_cannot_be_read_before_seal_or_after_kickoff(self):
        snapshot, seal, _ = fixture()
        for received in (BASE, BASE+timedelta(hours=2)):
            with self.subTest(received=received), self.assertRaises(ValueError):
                evaluate_1x2(snapshot, seal, ThreeWayQuote("book-a", received, (1.8, 4.0, 6.0)))

    def test_only_a_matching_snapshot_can_be_priced(self):
        snapshot, seal, quote = fixture()
        changed = SportsOnlySnapshot("demo", snapshot.kickoff, snapshot.as_of, snapshot.facts + (
            Fact("sports.injury", "new", "source-b", BASE-timedelta(minutes=5), BASE-timedelta(minutes=2)),))
        with self.assertRaises(ValueError):
            evaluate_1x2(changed, seal, quote)

    def test_price_change_does_not_change_probability_digest(self):
        snapshot, seal, quote = fixture()
        first = evaluate_1x2(snapshot, seal, quote)
        second = evaluate_1x2(snapshot, seal, ThreeWayQuote("book-a", BASE+timedelta(minutes=3), (1.9, 3.8, 5.8)))
        self.assertEqual(first["snapshot_digest"], second["snapshot_digest"])
        self.assertNotEqual(first["ev"], second["ev"])

    def test_invalid_probability_and_odds_do_not_silently_normalize(self):
        snapshot, _, _ = fixture()
        for p in ((.6,.3,.2), (-.1,.6,.5), (float("nan"),.5,.5)):
            with self.subTest(p=p), self.assertRaises(ValueError):
                ProbabilitySeal.create(snapshot, "demo-v0", BASE+timedelta(minutes=1), p)
        for odds in ((1.0,4.0,6.0), (float("inf"),4.0,6.0), (True,4.0,6.0)):
            with self.subTest(odds=odds), self.assertRaises(ValueError):
                ThreeWayQuote("book-a", BASE+timedelta(minutes=2), odds)

    def test_reproducible_digest_and_timezones(self):
        snapshot, seal, quote = fixture()
        equivalent = SportsOnlySnapshot(snapshot.match_id, snapshot.kickoff.astimezone(timezone(timedelta(hours=3))),
                                        snapshot.as_of, snapshot.facts)
        self.assertEqual(snapshot.digest(), equivalent.digest())
        self.assertEqual(evaluate_1x2(snapshot, seal, quote), evaluate_1x2(equivalent, seal, quote))

    def test_naive_clock_and_prematch_boundary_rejected(self):
        with self.assertRaises(ValueError):
            SportsOnlySnapshot("demo", BASE+timedelta(hours=2), BASE.replace(tzinfo=None), ())
        with self.assertRaises(ValueError):
            SportsOnlySnapshot("demo", BASE, BASE, ())

    def test_market_data_cannot_be_injected_as_sports_fact(self):
        with self.assertRaises(ValueError):
            Fact("market.odds", "1.8", "book-a", BASE, BASE)

    def test_direct_seal_constructor_cannot_bypass_validation(self):
        snapshot, seal, _ = fixture()
        with self.assertRaises(ValueError):
            ProbabilitySeal(snapshot.digest(), seal.model_version, seal.sealed_at, (.6, .6, -.2))
        forged_time = ProbabilitySeal(snapshot.digest(), seal.model_version, snapshot.kickoff, seal.probabilities)
        with self.assertRaises(ValueError):
            evaluate_1x2(snapshot, forged_time, ThreeWayQuote("book-a", snapshot.kickoff, (1.8, 4.0, 6.0)))


if __name__ == "__main__":
    unittest.main()
