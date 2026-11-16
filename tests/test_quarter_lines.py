"""Offline regression for no-vig references and research-only quarter payoffs."""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.markets import market_reference, payoff_ev, margin
from sefirot.quarter_lines import quarter_payoff, quarter_review, simulate_express, review_independent_express
from sefirot.contracts import Policy, digest
from sefirot.fixtures import example
from sefirot.market_grid import create_grid
from sefirot.repository import Repository
from sefirot.service import Service
from datetime import datetime, timedelta, timezone


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

    def test_sealed_express_review_is_math_only_and_rejects_same_fixture(self):
        now = datetime(2030, 1, 1, 10, tzinfo=timezone.utc)
        policy = Policy(); repo = Repository(':memory:')
        try:
            service = Service(repo, policy, lambda: now)
            legs = []
            for fid in ('synthetic-one', 'synthetic-two'):
                case = example(at=now, match_id=fid)
                prediction = service.capture(case['sports'], case['markets'])
                grid_at = (now + timedelta(minutes=1)).isoformat()
                quote_at = (now + timedelta(minutes=2)).isoformat()
                grid = create_grid(prediction, policy, grid_at)
                quotes = [{'market': {'kind': 'TOTAL', 'side': side, 'line': 2.5},
                           'bookmaker': 'SYNTHETIC_BOOK', 'odds': 1.85,
                           'observed_at': quote_at, 'received_at': quote_at,
                           'phase': 'FINAL', 'rules': 'REGULATION_90',
                           'line_id': 'complete-total'} for side in ('OVER', 'UNDER')]
                receipt = {'provider': 'THE_ODDS_API_V4', 'quotes_hash': digest(quotes),
                           'grid_hash': grid['hash'], 'fixture_id': fid,
                           'bookmaker': 'SYNTHETIC_BOOK', 'received_at': quote_at}
                legs.append({'grid': grid, 'prediction': prediction, 'quotes': quotes,
                             'receipt': receipt, 'market_key': 'TOTAL:OVER:2.5',
                             'line_id': 'complete-total'})
            review = review_independent_express(legs, policy, quote_at)
            self.assertAlmostEqual(review['raw_expected_gross_if_independent'],
                                   review['legs'][0]['raw_expected_gross'] * review['legs'][1]['raw_expected_gross'])
            self.assertEqual(review['quoted_full_win_odds_product_diagnostic'], 1.85**2)
            self.assertIsNone(review['actual_combined_bookmaker_price'])
            self.assertIsNone(review['validated_ev'])
            self.assertEqual(review['independence'], 'ASSUMED_NOT_ESTABLISHED')
            self.assertIn('SHARED_TEAM_ACROSS_FIXTURES', review['correlation_risks'])
            self.assertEqual((review['class'], review['decision'], review['stake']), ('C', 'PASS', 0.))
            self.assertEqual(repo.all('decisions'), [])
            self.assertTrue(repo.verify())
            with self.assertRaisesRegex(ValueError, 'same-fixture'):
                review_independent_express([legs[0], legs[0]], policy, quote_at)
            broken = dict(legs[1], receipt={**legs[1]['receipt'], 'quotes_hash': 'bad'})
            with self.assertRaisesRegex(ValueError, 'API receipt'):
                review_independent_express([legs[0], broken], policy, quote_at)
            with self.assertRaises(ValueError):
                review_independent_express(legs, policy, (now + timedelta(minutes=120)).isoformat())
        finally:
            repo.close()


if __name__ == "__main__":
    unittest.main()
