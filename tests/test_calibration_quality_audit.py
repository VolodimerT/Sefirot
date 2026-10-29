"""Read-only calibration audit: integrity, paired metrics and failure cases."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sefirot.contracts import digest
from scripts.calibration_quality_audit import audit, _interval


START = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
MARKETS = ("1X2:HOME", "TOTAL:OVER:2.5")


def timestamp(delta):
    return (START + timedelta(days=delta)).isoformat()


def resign(report):
    report["hash"] = digest({k: v for k, v in report.items() if k != "hash"})
    return report


def scorecard(n=60, *, scored=None, role="HOLDOUT", calibrated=True,
              markets=MARKETS, spread_days=True):
    if scored is None: scored = n
    fixtures = []
    observations = []
    for i in range(n):
        match_id = f"fixture-{i:03d}"
        finished = i < scored
        kickoff = timestamp(i if spread_days else 0)
        fixture = {
            "match_id": match_id, "kickoff": kickoff,
            "league": "L1", "competition_profile": "MEN",
            "prediction_id": "prediction-" + match_id if finished else None,
            "status": "SCORED" if finished else "MISSED_PREMATCH_WINDOW",
        }
        fixtures.append(fixture)
        if not finished: continue
        for market in markets:
            observations.append({
                "match_id": match_id, "prediction_id": fixture["prediction_id"],
                "league": fixture["league"],
                "competition_profile": fixture["competition_profile"],
                "kickoff": kickoff, "market": market, "outcome": "WIN",
                "raw": [0.5, 0, 0.5], "base": [0.7, 0, 0.3] if calibrated else [0.5, 0, 0.5],
                "calibration_status": "CALIBRATED_BIN" if calibrated else "UNCALIBRATED",
            })
    report = {
        "schema": "forward-scorecard-v1",
        "role": role, "plan_id": "original-plan-hash",
        "at": timestamp(n + 2),
        "frozen_build": {
            "code_hash": "a" * 64, "model_hash": "b" * 64, "policy_hash": "c" * 64,
            "calibrator_id": "frozen-calibrator" if role == "HOLDOUT" and calibrated else None,
        },
        "fixtures": fixtures, "planned_fixtures": n,
        "scored_fixtures": scored, "fixture_coverage": scored / n,
        "observations": observations,
        "market_observations": len(observations),
        "groups": [
            {"league": "L1", "competition_profile": "MEN", "market": market}
            for market in markets
        ],
        "monetary_permission": False, "execution_enabled": False,
        "holdout_passed": False, "statistical_profitability_proven": False,
        "forecasts_recomputed": 0,
    }
    return resign(report)


class CalibrationQualityAuditTests(unittest.TestCase):
    def test_holdout_pairing_uses_60_distinct_fixtures_not_120_independent_rows(self):
        report = audit(scorecard())
        self.assertEqual(report["status"], "HOLDOUT_DESCRIPTIVE_METRICS_ONLY")
        self.assertEqual(report["planned_fixtures"], 60)
        self.assertEqual(report["distinct_matches_scored"], 60)
        self.assertEqual(report["market_observations"], 120)
        self.assertEqual(report["bins"]["observed_bins"], 2)
        self.assertEqual(report["bins"]["at_or_above_min"], 2)
        self.assertLess(report["paired_all_markets"]["delta_base_minus_raw"]["brier"], 0)
        self.assertLess(report["paired_all_markets"]["delta_base_minus_raw"]["log_loss"], 0)
        self.assertIsNotNone(report["paired_fixture_cluster_brier_interval"])
        self.assertFalse(report["holdout_passed"])
        self.assertFalse(report["monetary_permission"])
        self.assertFalse(report["parameters_modified"])

    def test_17_unscored_calibration_games_is_zero_evidence_not_119_rows(self):
        report = audit(scorecard(n=17, scored=0, role="CALIBRATION", calibrated=False))
        self.assertEqual(report["status"], "NO_SCORABLE_FORECASTS")
        self.assertEqual(report["scored_fixtures"], 0)
        self.assertEqual(report["bins"]["observed_bins"], 0)
        self.assertEqual(report["market_observations"], 0)
        self.assertIsNone(report["paired_all_markets"])
        self.assertIsNone(report["paired_fixture_cluster_brier_interval"])

    def test_training_cohort_only_not_out_of_sample_gain(self):
        report = audit(scorecard(n=30, role="CALIBRATION", calibrated=False))
        self.assertEqual(report["status"], "TRAINING_COHORT_ONLY_NO_OUT_OF_SAMPLE_GAIN")
        self.assertFalse(report["requirements"]["frozen_calibrator_present"])
        self.assertEqual(report["bins"]["at_or_above_min"], 2)
        self.assertFalse(report["training_performed"])

    def test_unscored_fixtures_remain_in_coverage_denominator(self):
        report = audit(scorecard(n=75, scored=60))
        self.assertEqual(report["fixture_coverage"], 0.8)
        self.assertEqual(report["missing_or_unscored_fixtures"], 15)
        more_missing = audit(scorecard(n=80, scored=60))
        self.assertEqual(more_missing["status"], "HOLDOUT_COVERAGE_OR_SAMPLE_INSUFFICIENT")

    def test_holdout_requires_frozen_calibrator(self):
        report = audit(scorecard(n=70, calibrated=False))
        self.assertEqual(report["status"], "HOLDOUT_WITHOUT_FROZEN_CALIBRATOR")

    def test_hash_tampering_is_rejected_even_when_count_unchanged(self):
        s = scorecard(n=3)
        s["observations"][0]["base"][0] = 0.99
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            audit(s)

    def test_broken_fixture_count_and_omitted_market_are_rejected(self):
        s = scorecard(n=5)
        s["planned_fixtures"] = 4
        with self.assertRaisesRegex(ValueError, "denominator"):
            audit(resign(s))
        s = scorecard(n=5)
        s["observations"].pop()
        s["market_observations"] -= 1
        with self.assertRaisesRegex(ValueError, "market omission"):
            audit(resign(s))

    def test_unplanned_fixture_duplicate_and_wrong_prediction_are_rejected(self):
        s = scorecard(n=2)
        s["observations"][0]["match_id"] = "injected-future-fixture"
        with self.assertRaisesRegex(ValueError, "not from"):
            audit(resign(s))
        s = scorecard(n=2)
        s["observations"][1]["market"] = s["observations"][0]["market"]
        with self.assertRaisesRegex(ValueError, "duplicate market"):
            audit(resign(s))
        s = scorecard(n=2)
        s["observations"][0]["prediction_id"] = "different"
        with self.assertRaisesRegex(ValueError, "identity"):
            audit(resign(s))

    def test_impossible_push_vector_and_outcome_rejected(self):
        s = scorecard(n=2)
        s["observations"][0]["raw"] = [0.4, 0.2, 0.4]
        with self.assertRaisesRegex(ValueError, "PUSH probability"):
            audit(resign(s))
        s = scorecard(n=2)
        s["observations"][0]["outcome"] = "PUSH"
        with self.assertRaisesRegex(ValueError, "impossible PUSH"):
            audit(resign(s))

    def test_zero_scored_cannot_fake_calibrated_status_or_training(self):
        s = scorecard(n=5, scored=0, role="CALIBRATION", calibrated=False)
        s["frozen_build"]["calibrator_id"] = "trained-on-holdout"
        with self.assertRaisesRegex(ValueError, "must not reuse"):
            audit(resign(s))

    def test_too_small_sample_no_bootstrap_interval(self):
        report = audit(scorecard(n=12))
        self.assertEqual(report["status"], "HOLDOUT_COVERAGE_OR_SAMPLE_INSUFFICIENT")
        self.assertIsNone(report["paired_fixture_cluster_brier_interval"])

    def test_future_scored_fixture_fails(self):
        s = scorecard(n=2)
        s["fixtures"][0]["kickoff"] = timestamp(20)
        s["observations"][0]["kickoff"] = timestamp(20)
        s["observations"][1]["kickoff"] = timestamp(20)
        with self.assertRaisesRegex(ValueError, "future"):
            audit(resign(s))

    def test_exact_contract_distinguishes_profiles_and_lines(self):
        s = scorecard(n=24)
        out = audit(s)
        self.assertIn("MEN:1X2:HOME:2", {r["bin"] for r in out["bins"]["bins"]})
        self.assertIn("MEN:TOTAL:OVER:2.5:2", {r["bin"] for r in out["bins"]["bins"]})
        self.assertEqual(out["bins"]["bins"][0]["remaining_to_min"], 0)

    def test_one_date_has_no_fake_independent_cluster_ci(self):
        result = audit(scorecard(n=60, spread_days=False))
        self.assertEqual(result["distinct_matches_scored"], 60)
        self.assertIsNone(result["paired_fixture_cluster_brier_interval"])

    def test_recompute_hash_on_wrong_row_cannot_grant_execution(self):
        s = scorecard(n=3)
        s["monetary_permission"] = True
        with self.assertRaisesRegex(ValueError, "research"):
            audit(resign(s))


if __name__ == "__main__":
    unittest.main()
