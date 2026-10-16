"""Owned offline counterexamples; no genuine Stake access or settlement proof."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from sefirot.contracts import digest
from sefirot.stake_mapper import normalize_snapshot
from scripts.stake_market_atlas import make_atlas
from test_stake_mapper import snapshot


def single(index=6):
    obj = snapshot()
    obj["markets"] = [obj["markets"][index]]
    return obj


def atlas_for(obj):
    obj = deepcopy(obj)
    obj.update(execution_enabled=False, market_count=len(obj["markets"]))
    obj["hash"] = digest(obj)
    return make_atlas([obj])


class StakeNormalizationIntegrityTests(unittest.TestCase):
    def test_duplicate_specifiers_never_choose_a_line(self):
        for index, key, value in ((1, "total", "2.5"), (6, "total", "8.5"),
                                  (3, "hcp", "-1"), (5, "count", "24")):
            for spec in (f"{key}=12.5|{key}={value}",
                         f"{key}={value}& {key} ={value}"):
                with self.subTest(index=index, spec=spec):
                    obj = single(index); obj["markets"][0]["specifiers"] = spec
                    with self.assertRaises(ValueError):
                        normalize_snapshot(obj)

    def test_malformed_specifiers_never_disappear(self):
        for spec in (False, 0, [], {}, "invalid", "total=2.5|period", "=2.5", "total="):
            with self.subTest(spec=spec):
                obj = single(1); obj["markets"][0]["specifiers"] = spec
                with self.assertRaises(ValueError):
                    normalize_snapshot(obj)

    def test_small_total_requires_exact_line_and_complete_partition(self):
        for names in (("Over 12.5", "Under 12.5"), ("Over 8.5 first half", "Under 8.5"),
                      ("Over 8.5", "Over 8.5"), ("Over 8.5",),
                      ("Over 8.5", "Under 8.5", "Under 8.5")):
            with self.subTest(names=names):
                obj = single(); market = obj["markets"][0]
                market["outcomes"] = [{"id": str(i), "name": n, "odds": 2.0}
                                      for i, n in enumerate(names)]
                with self.assertRaises(ValueError):
                    normalize_snapshot(obj)

    def test_small_scope_cannot_be_overridden_by_generic_template(self):
        for index in (5, 6, 7):
            for change in ({"group": "1st Half"}, {"group": "Extra Time"},
                           {"group": "UNKNOWN"}, {"group": None},
                           {"specifiers": snapshot()["markets"][index]["specifiers"] + "|period=1"}):
                with self.subTest(index=index, change=change):
                    obj = single(index); obj["markets"][0].update(change)
                    with self.assertRaises(ValueError):
                        normalize_snapshot(obj)

    def test_shots_count_must_agree_with_name(self):
        for spec in ("count=25", "count=24.5", "", "count=nan"):
            with self.subTest(spec=spec):
                obj = single(5); obj["markets"][0]["specifiers"] = spec
                with self.assertRaises(ValueError):
                    normalize_snapshot(obj)

    def test_malformed_outcomes_fail_safely_and_atlas_preserves_raw(self):
        for index in (0, 5, 6, 7):
            for outcomes in ([True], [None], [7], [[]], {}, False, "bad"):
                with self.subTest(index=index, outcomes=outcomes):
                    obj = single(index); obj["markets"][0]["outcomes"] = outcomes
                    with self.assertRaises(ValueError):
                        normalize_snapshot(obj)
                    atlas = atlas_for(obj)
                    self.assertEqual(atlas["markets"][0]["raw"], obj["markets"][0])
                    self.assertIn("NORMALIZATION_UNAVAILABLE",
                                  [e["error"] for e in atlas["fixtures"][0]["normalizer_errors"]])

    def test_status_and_active_survive_without_claiming_availability(self):
        for status, active in (("suspended", False), ("active", True), (None, None)):
            with self.subTest(status=status, active=active):
                obj = snapshot()
                for market in obj["markets"]:
                    market["status"] = status
                    for outcome in market["outcomes"]:
                        outcome["active"] = active
                report = normalize_snapshot(obj)
                for row in report["main_quotes"] + report["small_quotes"]:
                    self.assertEqual(row["raw_market_status"], status)
                    self.assertIs(row["raw_outcome_active"], active)
                    self.assertEqual(row["availability"], "NOT_VERIFIED")
                self.assertFalse(report["monetary_permission"])
                self.assertFalse(report["execution_enabled"])

    def test_valid_values_and_original_snapshot_are_preserved(self):
        obj = snapshot(); before = deepcopy(obj)
        report = normalize_snapshot(obj)
        self.assertEqual(obj, before)
        self.assertEqual(report["main_quote_count"], 10)
        self.assertEqual(report["small_quote_count"], 7)
        for row in report["main_quotes"] + report["small_quotes"]:
            self.assertIsNone(row["raw_market_status"])
            self.assertIsNone(row["raw_outcome_active"])
        for template, period in (("Total Corners", "REGULATION_90"),
                                 ("Total Cards", "REGULATION_90"),
                                 ("1st Half - Total Corners", "FIRST_HALF"),
                                 ("1st Half - Total Cards", "FIRST_HALF")):
            obj = single(); obj["markets"][0].update(template=template, name=template)
            quotes = normalize_snapshot(obj)["small_quotes"]
            self.assertEqual([(q["period"], q["threshold"]) for q in quotes], [(period, 8.5)] * 2)

    def test_ambiguous_markets_remain_lossless_raw_in_atlas(self):
        cases = []
        obj = single(); obj["markets"][0]["outcomes"][0]["name"] = "Over 12.5"; cases.append(obj)
        obj = single(); obj["markets"][0]["group"] = "1st Half"; cases.append(obj)
        obj = single(1); obj["markets"][0]["specifiers"] = "total=12.5|total=2.5"; cases.append(obj)
        for obj in cases:
            with self.subTest(market=obj["markets"][0]):
                before = deepcopy(obj)
                atlas = atlas_for(obj)
                self.assertEqual(obj, before)
                self.assertEqual(atlas["raw_market_count"], 1)
                self.assertEqual(atlas["markets"][0]["raw"], obj["markets"][0])
                self.assertTrue(all(o["classification"] == "UNMAPPED_RAW"
                                    for o in atlas["markets"][0]["outcome_mapping"]))
                self.assertFalse(atlas["monetary_permission"])


if __name__ == "__main__":
    unittest.main()
