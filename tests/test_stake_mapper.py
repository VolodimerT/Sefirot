"""Tests for conservative Stake market normalization."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sefirot.stake_mapper import normalize_snapshot


def snapshot():
    return {
        "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
        "status": "RESEARCH_ONLY",
        "fixture_id": "M1",
        "stake_event_id": "E1",
        "home": "Cyprus",
        "away": "Latvia",
        "kickoff": "2030-01-01T18:00:00+00:00",
        "received_at": "2030-01-01T15:00:00+00:00",
        "monetary_permission": False,
        "markets": [
            {
                "id": "m-1x2", "group": "main", "template": "1x2", "name": "1x2",
                "specifiers": "", "outcomes": [
                    {"id": "h", "name": "Cyprus", "odds": 1.54, "customBetAvailable": True},
                    {"id": "d", "name": "Draw", "odds": 3.9, "customBetAvailable": True},
                    {"id": "a", "name": "Latvia", "odds": 6.2, "customBetAvailable": True},
                ],
            },
            {
                "id": "m-total", "group": "main", "template": "Asian Total",
                "name": "Asian Total", "specifiers": "total=2.5", "outcomes": [
                    {"id": "o", "name": "Over 2.5", "odds": 2.06},
                    {"id": "u", "name": "Under 2.5", "odds": 1.68},
                ],
            },
            {
                "id": "m-quarter", "group": "main", "template": "Asian Total",
                "name": "Asian Total", "specifiers": "total=2.25", "outcomes": [
                    {"id": "qo", "name": "Over 2.25", "odds": 1.81},
                    {"id": "qu", "name": "Under 2.25", "odds": 1.89},
                ],
            },
            {
                "id": "m-ah", "group": "main", "template": "Asian Handicap",
                "name": "Asian Handicap", "specifiers": "hcp=-1", "outcomes": [
                    {"id": "hh", "name": "Cyprus (-1)", "odds": 1.91},
                    {"id": "aa", "name": "Latvia (1)", "odds": 1.79},
                ],
            },
            {
                "id": "m-dc", "group": "main", "template": "Double Chance",
                "name": "Double Chance", "specifiers": "", "outcomes": [
                    {"id": "dc1", "name": "Cyprus or Latvia", "odds": 1.26},
                    {"id": "dc2", "name": "Draw or Latvia", "odds": 2.43},
                    {"id": "dc3", "name": "Cyprus or Draw", "odds": 1.14},
                ],
            },
            {
                "id": "m-shots", "group": "specials", "template": "Match {count}+ shots",
                "name": "Match 24+ shots", "specifiers": "count=24",
                "outcomes": [{"id": "s", "name": "Yes", "odds": 1.74}],
            },
            {
                "id": "m-corners", "group": "CardsCorners", "template": "Total Corners",
                "name": "Total Corners", "specifiers": "total=8.5",
                "outcomes": [
                    {"id": "co", "name": "Over 8.5", "odds": 1.67},
                    {"id": "cu", "name": "Under 8.5", "odds": 2.10},
                ],
            },
            {
                "id": "m-teamcorners", "group": "CardsCorners",
                "template": "{$competitor1} Corner Range",
                "name": "Cyprus Corner Range", "specifiers": "variant=sr:point_range:7+",
                "outcomes": [
                    {"id": "c1", "name": "0-2", "odds": 7.78},
                    {"id": "c2", "name": "3-4", "odds": 3.49},
                    {"id": "c3", "name": "5-6", "odds": 3.10},
                    {"id": "c4", "name": "7+", "odds": 2.48},
                ],
            },
        ],
    }


class StakeMapperTests(unittest.TestCase):
    def test_maps_supported_main_contracts_and_skips_quarter_lines(self):
        report = normalize_snapshot(snapshot())
        by_key = {row["key"]: row for row in report["main_quotes"]}
        self.assertEqual(by_key["1X2:HOME"]["odds"], 1.54)
        self.assertEqual(by_key["TOTAL:OVER:2.5"]["odds"], 2.06)
        self.assertEqual(by_key["HANDICAP:HOME:-1"]["odds"], 1.91)
        self.assertEqual(by_key["HANDICAP:AWAY:1"]["odds"], 1.79)
        self.assertIn("DOUBLE_CHANCE:1X", by_key)
        self.assertIn("DOUBLE_CHANCE:X2", by_key)
        self.assertIn("DOUBLE_CHANCE:12", by_key)
        self.assertFalse(any(row["key"].endswith(":2.25") for row in report["main_quotes"]))
        self.assertTrue(any(row["reason"] == "UNSUPPORTED_CORE_LINE" for row in report["rejected"]))

    def test_maps_shots_and_corners_research_only(self):
        report = normalize_snapshot(snapshot())
        shots = [row for row in report["small_quotes"] if row["metric"] == "SHOTS"]
        corners = [row for row in report["small_quotes"] if row["metric"] == "CORNERS"]
        self.assertEqual(shots[0]["operator"], "GTE")
        self.assertEqual(shots[0]["threshold"], 24)
        self.assertTrue(any(row["operator"] == "OVER" and row["threshold"] == 8.5 for row in corners))
        self.assertTrue(any(row["category"] == "RANGE" and row["scope"] == "HOME" for row in corners))
        self.assertFalse(report["monetary_permission"])
        self.assertFalse(report["execution_enabled"])
        self.assertEqual(report["settlement_rules"], "UNVERIFIED_PROVIDER_WEB_CONTRACT")

    def test_rejects_non_stake_or_unsafe_snapshot(self):
        bad = snapshot(); bad["provider"] = "OTHER"
        with self.assertRaises(ValueError):
            normalize_snapshot(bad)
        bad = snapshot(); bad["monetary_permission"] = True
        with self.assertRaises(ValueError):
            normalize_snapshot(bad)


if __name__ == "__main__":
    unittest.main()
