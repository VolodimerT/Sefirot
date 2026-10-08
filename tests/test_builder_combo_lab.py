"""Regression tests for bounded, research-only same-game combo lab."""
from datetime import datetime, timedelta, timezone
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sefirot.builder_research import builder_contract, joint_probability
from sefirot.contracts import Policy, digest, time
from sefirot.engine import prepare
from sefirot.fixtures import example
from sefirot.markets import market_of
from sefirot.probability import estimate
from scripts.builder_combo_lab import PALETTE, freeze, inspect_stake


START = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)


def prediction():
    case = example(START)
    pred = prepare(case["sports"], case["markets"], Policy())
    pred.update({
        "sealed_at": (time(case["sports"]["as_of"]) + timedelta(minutes=1)).isoformat(),
        "captured_prematch": True, "reconstructed": False,
        "revision": 0, "parent": None, "override_reason": None,
    })
    pred["model_id"] = digest([pred["code_hash"], pred["policy_hash"], None, None])
    pred["id"] = digest({k: v for k, v in pred.items() if k != "id"})
    at = (time(pred["sealed_at"]) + timedelta(minutes=2)).isoformat()
    return pred, at


def stake_snapshot(pred, stamp, *, active=True):
    match = pred["sports"]["match"]
    markets = [{
        "id": "m1", "status": "active", "group": "main",
        "template": "1x2", "name": "1x2", "specifiers": "",
        "outcomes": [
            {"id": "h", "name": match["home"], "odds": 1.65,
             "active": active, "customBetAvailable": True},
            {"id": "d", "name": "Draw", "odds": 3.2,
             "active": active, "customBetAvailable": True},
            {"id": "a", "name": match["away"], "odds": 5.3,
             "active": active, "customBetAvailable": True},
        ],
    }, {
        "id": "m2", "status": "active", "group": "total",
        "template": "Asian Total", "name": "Asian Total",
        "specifiers": "total=2.5",
        "outcomes": [
            {"id": "ov", "name": "Over 2.5", "odds": 2.0,
             "active": True, "customBetAvailable": True},
            {"id": "un", "name": "Under 2.5", "odds": 1.8,
             "active": True, "customBetAvailable": True},
        ],
    }, {
        "id": "m3", "status": "closed", "group": "cards",
        "template": "Yellow Cards", "name": "Yellow Cards",
        "outcomes": [{"id": "yellow", "name": "Over", "odds": None, "active": False}],
    }]
    data = {
        "provider": "STAKE_GRAPHQL_EXPERIMENTAL", "status": "RESEARCH_ONLY",
        "fixture_id": match["id"], "stake_event_id": "E",
        "home": match["home"], "away": match["away"],
        "kickoff": match["kickoff"], "received_at": stamp,
        "markets": markets, "market_count": len(markets),
        "monetary_permission": False, "execution_enabled": False,
    }
    data["hash"] = digest(data)
    return data


class ComboLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pred, cls.at = prediction()
        cls.report = freeze(cls.pred, cls.at)

    def test_freeze_is_price_blind_and_only_same_fixture_goals(self):
        report = self.report
        self.assertEqual(report["schema"], "builder-combo-lab-freeze-v1")
        self.assertEqual(report["enumerated_count"], 680)
        self.assertGreater(report["candidate_count"], 50)
        self.assertLess(report["candidate_count"], 680)
        self.assertEqual(sum(report["rejected_counts"].values())+report["candidate_count"], 680)
        self.assertTrue(all(r["size"] in (2,3) for r in report["candidates"]))
        self.assertTrue(all(r["stake_joint_odds"] is None and r["builder_ev"] is None for r in report["candidates"]))
        self.assertFalse(report["prices_read"])
        self.assertEqual(report["stake"], 0)
        self.assertFalse(report["monetary_permission"])
        self.assertFalse(report["execution_enabled"])

    def test_joint_not_naive_product_and_branch_mass(self):
        rows = self.report["candidates"]
        candidate = next(r for r in rows if r["keys"] == ["1X2:HOME", "BTTS:YES"])
        self.assertGreater(abs(candidate["dependence_gap"]), 1e-6)
        self.assertAlmostEqual(
            sum(candidate["terminal_branch_contributions"].values()),
            candidate["joint_probability_raw"], places=9,
        )
        self.assertLessEqual(candidate["joint_probability_raw"], min(candidate["marginals_raw"]) + 1e-8)
        self.assertLessEqual(candidate["rate_stress_probability_min"], candidate["joint_probability_raw"] + 1e-12)
        self.assertNotEqual(candidate["naive_product_diagnostic_only"], candidate["joint_probability_raw"])

    def test_contradiction_and_redundancy_rejected(self):
        home={"kind":"1X2","side":"HOME"}
        away={"kind":"1X2","side":"AWAY"}
        dc={"kind":"DOUBLE_CHANCE","side":"1X"}
        with self.assertRaisesRegex(ValueError, "contradictory"):
            builder_contract([home, away])
        with self.assertRaisesRegex(ValueError, "redundant"):
            builder_contract([home, dc])
        with self.assertRaisesRegex(ValueError, "PUSH"):
            builder_contract([home, {"kind": "TOTAL", "side": "OVER", "line": 2}])

    def test_mixed_metrics_have_no_fake_joint_distribution(self):
        cross = self.report["cross_metric"]
        self.assertIn("GOALS+CORNERS", cross["families"])
        self.assertIn("GOALS+YELLOW_CARDS", cross["families"])
        self.assertIsNone(cross["joint_probability"])
        self.assertIsNone(cross["joint_ev"])
        self.assertEqual(self.report["joint_calibration_status"], "UNVALIDATED")

    def test_original_hash_and_future_quotes_cannot_rewrite_prediction(self):
        bad = copy.deepcopy(self.pred)
        bad["sports"]["history"][0]["home_goals"] = 30
        with self.assertRaisesRegex(ValueError, "hash"):
            freeze(bad, self.at)
        with self.assertRaises(ValueError):
            freeze(self.pred, self.pred["sports"]["match"]["kickoff"])

    def test_size_specific_freeze_is_complete_without_market_prices(self):
        duo = freeze(self.pred, self.at, sizes=(2,))
        self.assertEqual(duo["enumerated_count"], 120)
        self.assertEqual(duo["sizes"], [2])
        self.assertTrue(all(r["size"] == 2 for r in duo["candidates"]))
        self.assertEqual(duo["palette_hash"], self.report["palette_hash"])

    def test_stake_flags_are_only_leg_eligibility_never_joint_quote(self):
        at = (time(self.at) + timedelta(minutes=1)).isoformat()
        snap = stake_snapshot(self.pred, at)
        out = inspect_stake(self.report, snap)
        self.assertEqual(out["sgm_price_count"], 0)
        self.assertIsNone(out["sgm_accepted_count"])
        self.assertEqual(out["joint_ev_available_count"], 0)
        self.assertTrue(all(r["stake_joint_odds"] is None and r["builder_ev"] is None for r in out["candidates"]))
        self.assertFalse(out["execution_enabled"])
        self.assertFalse(out["monetary_permission"])
        self.assertGreater(out["individually_flagged_combo_count"], 0)

    def test_disabled_outcome_and_unmapped_still_do_not_price_builder(self):
        at = (time(self.at) + timedelta(minutes=1)).isoformat()
        out = inspect_stake(self.report, stake_snapshot(self.pred, at, active=False))
        self.assertEqual(out["individually_flagged_combo_count"], 0)

    def test_wrong_fixture_stale_and_forged_snapshots_rejected(self):
        snap = stake_snapshot(self.pred, (time(self.at)+timedelta(minutes=1)).isoformat())
        wrong = dict(snap)
        wrong["fixture_id"] = "OTHER"
        wrong["hash"] = digest({k:v for k,v in wrong.items() if k != "hash"})
        with self.assertRaisesRegex(ValueError, "fixture mismatch"):
            inspect_stake(self.report, wrong)
        premature = dict(snap)
        premature["received_at"] = self.pred["sealed_at"]
        premature["hash"] = digest({k:v for k,v in premature.items() if k != "hash"})
        with self.assertRaisesRegex(ValueError, "post-freeze"):
            inspect_stake(self.report, premature)
        tampered = copy.deepcopy(snap)
        tampered["markets"][0]["outcomes"][0]["odds"] = 1.01
        with self.assertRaisesRegex(ValueError, "hash"):
            inspect_stake(self.report, tampered)


if __name__ == "__main__":
    unittest.main()
