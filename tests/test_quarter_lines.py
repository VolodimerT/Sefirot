"""Offline regression for no-vig references and research-only quarter payoffs."""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.markets import market_reference, payoff_ev, margin
from sefirot.quarter_lines import quarter_payoff, quarter_review, simulate_express


class FactsFirstMathTests(unittest.TestCase):
    def test_complete_two_way_185_is_fair_reference_200_not_value(self):
        stamp = "2030-01-01T10:00:00+00:00"
        quotes = [{"market": {"kind": "TOTAL", "side": side, "line": 2.5},
                   "bookmaker": "SYNTHETIC_BOOK", "odds": 1.85,
                   "observed_at": stamp, "received_at": stamp, "phase": "FINAL",
                   "rules": "REGULATION_90", "line_id": "same-complete-line"}
                  for side in ("OVER", "UNDER")]
        reference = market_reference(quotes, quotes[0], .5, 0.)
        self.assertEqual(reference["method"], "PROPORTIONAL_COMPLETE_BOOKMAKER_LINE")
        self.assertAlmostEqual(reference["probability"], .5)
        self.assertAlmostEqual(1 / reference["probability"], 2.)
        self.assertAlmostEqual(margin((1.85, 1.85)), 2 / 1.85 - 1)
        # EV uses the quoted 1.85 once; no second deduction of overround.
        self.assertAlmostEqual(100 * payoff_ev(.5, 0., 1.85), -7.5)

    def test_quarter_team_total_settles_half_loss_and_full_win(self):
        one = quarter_payoff("TEAM_TOTAL", "HOME_OVER", 1.25, 1, 0, 1.85)
        self.assertEqual(one["outcomes"], ["PUSH", "LOSS"])
        self.assertAlmostEqual(one["net_per_unit"], -.5)
        two = quarter_payoff("TEAM_TOTAL", "HOME_OVER", 1.25, 2, 0, 1.85)
        self.assertEqual(two["outcomes"], ["WIN", "WIN"])
        self.assertAlmostEqual(two["net_per_unit"], .85)
        under = quarter_payoff("TEAM_TOTAL", "HOME_UNDER", 1.25, 1, 0, 1.85)
        self.assertEqual(under["outcomes"], ["PUSH", "WIN"])
        self.assertAlmostEqual(under["net_per_unit"], .425)
        self.assertFalse(one["monetary_permission"])

    def test_quarter_handicap_and_175_cover_partial_result(self):
        self.assertEqual(quarter_payoff("TOTAL", "OVER", 1.75, 1, 1, 2.)["outcomes"], ["WIN", "PUSH"])
        self.assertEqual(quarter_payoff("HANDICAP", "HOME", -.25, 0, 0, 2.)["outcomes"], ["LOSS", "PUSH"])
        with self.assertRaises(ValueError):
            quarter_payoff("TEAM_TOTAL", "HOME_OVER", 1.5, 1, 0, 1.85)
        with self.assertRaises(ValueError):
            quarter_payoff("TOTAL", "OVER", 1.25, True, 0, 1.85)

    def test_raw_score_mass_does_not_claim_validated_probability_or_ev(self):
        review = quarter_review("TEAM_TOTAL", "HOME_OVER", 1.25, 1.85,
                                {(1, 0): .5, (2, 0): .5})
        self.assertAlmostEqual(review["raw_model_ev_diagnostic"], .175)
        self.assertIsNone(review["validated_probability"])
        self.assertIsNone(review["validated_ev"])
        self.assertEqual(review["class"], "C")
        self.assertEqual(review["decision"], "PASS")
        self.assertEqual(review["stake"], 0.)
        with self.assertRaises(ValueError):
            quarter_review("TOTAL", "OVER", 1.25, 1.85, {(2, 0): .8})

    def test_express_partial_return_exposure_and_correlated_legs(self):
        legs = [
            {"fixture_id": "synthetic-1", "kind": "TOTAL", "side": "OVER",
             "line": 1.25, "home": 1, "away": 0, "odds": 1.85},
            {"fixture_id": "synthetic-2", "kind": "TOTAL", "side": "OVER",
             "line": 1.75, "home": 1, "away": 1, "odds": 2.},
        ]
        result = simulate_express(legs, 100., 100.)
        self.assertAlmostEqual(result["gross_return"], 75.)
        self.assertAlmostEqual(result["net_result"], -25.)
        self.assertEqual(result["stake"], 0.)
        with self.assertRaises(ValueError):
            simulate_express(legs, 101., 100.)
        correlated = [dict(legs[0]), dict(legs[1], fixture_id="synthetic-1")]
        with self.assertRaisesRegex(ValueError, "joint builder"):
            simulate_express(correlated, 100., 100.)


if __name__ == "__main__":
    unittest.main()
