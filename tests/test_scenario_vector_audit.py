import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.scenario_vector_audit import audit, divergence_diagnostic, archived_live_quality


def case(**overrides):
    base = {
        "schema": "scenario-vector-case-v1",
        "case_id": "synthetic-1",
        "phase": "POSTMATCH_REVIEW",
        "decision": "PLAY",
        "outcome": "WIN",
        "legs": [
            {"id": "a", "family": "GOALS", "market": "TOTAL_OVER_2.5", "outcome": "WIN"},
            {"id": "b", "family": "GOALS", "market": "BTTS_YES", "outcome": "WIN"},
            {"id": "c", "family": "SIDE", "market": "DOUBLE_CHANCE_X2", "outcome": "WIN"},
        ],
    }
    base.update(overrides)
    return base


class TestScenarioVectorAudit(unittest.TestCase):
    def test_vector_first_and_simple_benchmark(self):
        out = audit(case())
        self.assertEqual(out["vector"]["primary_vector"], "GOALS_WITH_SIDE_GUARD")
        self.assertEqual(out["vector"]["primary_family"], "GOALS")
        self.assertEqual(
            [x["leg_id"] for x in out["vector"]["simple_market_benchmark_candidates"]],
            ["a"],
        )
        self.assertFalse(out["edge_certified"])

    def test_open_activity_builder(self):
        c = case(legs=[
            {"id": "a", "family": "GOALS", "market": "BTTS_YES", "outcome": "WIN"},
            {"id": "b", "family": "CORNERS", "market": "TOTAL_OVER_8.5", "outcome": "WIN"},
        ])
        out = audit(c)
        self.assertEqual(out["vector"]["primary_vector"], "OPEN_ACTIVITY_MIXED")

    def test_policy_divergence_review_and_hard_stop(self):
        review = divergence_diagnostic(
            {"HOME": .55, "DRAW": .25, "AWAY": .20},
            {"HOME": 2.30, "DRAW": 3.20, "AWAY": 3.10},
        )
        self.assertIn(review["status"], {"REVIEW_REQUIRED", "HARD_RESEARCH_STOP"})
        hard = divergence_diagnostic(
            {"HOME": .75, "DRAW": .15, "AWAY": .10},
            {"HOME": 2.60, "DRAW": 3.20, "AWAY": 2.80},
        )
        self.assertEqual(hard["status"], "HARD_RESEARCH_STOP")
        self.assertEqual(hard["canonical_effect"], "NONE_RESEARCH_DIAGNOSTIC_ONLY")

    def test_market_probabilities_are_no_vig(self):
        d = divergence_diagnostic(
            {"HOME": .5, "DRAW": .25, "AWAY": .25},
            {"HOME": 2.0, "DRAW": 4.0, "AWAY": 4.0},
        )
        self.assertAlmostEqual(sum(d["market_no_vig_1x2"].values()), 1.0)
        self.assertEqual(d["status"], "ALIGNED_WITHIN_POLICY_REVIEW_BAND")

    def test_archived_live_volume_without_quality_fails(self):
        q = archived_live_quality({
            "focus_side": "HOME",
            "possession_home": 62,
            "possession_away": 38,
            "shots_home": 10,
            "shots_away": 5,
            "corners_home": 6,
            "corners_away": 5,
            "shots_on_target_home": 3,
            "shots_on_target_away": 3,
        })
        self.assertEqual(q["status"], "NO_QUALITY_CONFIRMATION")
        self.assertFalse(q["usable_for_live_selection"])
        self.assertFalse(q["live_runtime_enabled"])

    def test_archived_live_quality_needs_two_positive_metrics(self):
        q = archived_live_quality({
            "focus_side": "AWAY",
            "shots_on_target_home": 2,
            "shots_on_target_away": 5,
            "xg_home": .6,
            "xg_away": 1.5,
        })
        self.assertEqual(q["status"], "QUALITY_CONFIRMED_POSTHOC")

    def test_pass_win_is_outcome_only_false_negative(self):
        out = audit(case(decision="PASS", outcome="WIN"))
        self.assertEqual(
            out["settlement"]["label"],
            "PASS_WIN_FALSE_NEGATIVE_OUTCOME_ONLY",
        )
        self.assertEqual(
            out["settlement"]["edge_conclusion"],
            "NOT_INFERABLE_FROM_SINGLE_SETTLEMENT",
        )

    def test_live_snapshot_rejected_outside_archive_phase(self):
        with self.assertRaisesRegex(ValueError, "archived live"):
            audit(case(archived_live_snapshot={"focus_side": "HOME"}))

    def test_unknown_fields_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown case fields"):
            audit(case(price=2.0))

    def test_output_is_research_only(self):
        out = audit(case())
        for key in ("monetary_permission", "execution_enabled", "live_runtime_enabled", "edge_certified"):
            self.assertFalse(out[key])
        self.assertEqual(out["stake"], 0.0)


if __name__ == "__main__":
    unittest.main()
