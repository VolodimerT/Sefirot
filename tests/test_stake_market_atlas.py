"""Research-only Stake market atlas: mocked API, no credential/network needed."""
import copy
from datetime import datetime, timedelta, timezone
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sefirot.contracts import digest
from scripts import stake_market_atlas as atlas


NOW = datetime.now(timezone.utc)
stamp = lambda delta: (NOW + timedelta(minutes=delta)).isoformat()


def snapshot(markets=None, **changes):
    markets = markets if markets is not None else [
        {"id": "one", "group": "Main", "template": "1x2", "name": "1x2",
         "outcomes": [{"id": "h", "name": "A", "odds": 1.7, "active": True},
                      {"id": "d", "name": "Draw", "odds": 3.3, "active": True},
                      {"id": "a", "name": "B", "odds": 5.1, "active": True}]},
        {"id": "f", "group": "Fouls", "template": "Total Fouls", "name": "Total Fouls",
         "specifiers": "total=23.5",
         "outcomes": [{"id": "fo", "name": "Over 23.5", "odds": 1.94, "active": True}]},
        {"id": "yc", "group": "Yellow Cards", "template": "1st Half - Yellow Cards",
         "name": "1st Half - Yellow Cards",
         "outcomes": [{"id": "yo", "name": "Over 2.5", "odds": 2.1, "active": False}]},
        {"id": "u", "group": "Unrecognized", "template": "Odd exotic", "name": "X",
         "outcomes": [{"id": "uo", "name": "Something", "odds": 6.2, "active": True}]},
    ]
    obj = {
        "provider": "STAKE_GRAPHQL_EXPERIMENTAL", "status": "RESEARCH_ONLY",
        "fixture_id": "M", "stake_event_id": "E", "home": "A", "away": "B",
        "kickoff": stamp(120), "received_at": stamp(0),
        "market_count": len(markets), "markets": markets,
        "monetary_permission": False, "execution_enabled": False,
    }
    obj.update(changes)
    obj["hash"] = digest({k: v for k, v in obj.items() if k != "hash"})
    return obj


class StakeMarketAtlasTests(unittest.TestCase):
    def test_lossless_unmapped_raw_lines_are_retained(self):
        original = snapshot()
        report = atlas.make_atlas([original])
        self.assertEqual(report["raw_market_count"], 4)
        self.assertEqual(report["raw_outcome_count"], 6)
        self.assertEqual([m["raw"] for m in report["markets"]], original["markets"])
        self.assertEqual(report["markets"][3]["outcome_mapping"][0]["classification"], "UNMAPPED_RAW")
        self.assertFalse(report["completeness_proven"])
        self.assertFalse(report["execution_enabled"])
        self.assertFalse(report["monetary_permission"])
        self.assertEqual(report["stake"], 0)

    def test_main_fouls_yellow_are_distinct(self):
        report = atlas.make_atlas([snapshot()])
        self.assertEqual(report["markets"][1]["metric_hint"], "FOULS")
        self.assertEqual(report["markets"][2]["metric_hint"], "YELLOW_CARDS")
        self.assertEqual(report["markets"][2]["period_hint"], "FIRST_HALF")
        self.assertFalse(report["markets"][2]["referee_gate_passed"])
        self.assertFalse(report["markets"][1]["probability_model_available"])
        self.assertEqual(report["markets"][0]["outcome_mapping"][0]["classification"], "MAIN_REFERENCE_ONLY")

    def test_snapshot_tampering_or_unknown_provider_rejected(self):
        packet = snapshot()
        packet["markets"][0]["outcomes"][0]["odds"] = 100.0
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            atlas.make_atlas([packet])
        with self.assertRaises(ValueError):
            atlas.make_atlas([snapshot(provider="FAKE")])

    def test_no_live_or_after_kickoff(self):
        with self.assertRaisesRegex(ValueError, "live"):
            atlas.make_atlas([snapshot(received_at=stamp(130))])

    def test_duplicate_fixture_does_not_create_independent_samples(self):
        with self.assertRaisesRegex(ValueError, "duplicate fixture"):
            atlas.make_atlas([snapshot(), snapshot()])

    def test_limit_detection_never_promises_every_market(self):
        many = [
            {"id": f"m{i}", "group": "Main", "template": "Total Corners",
             "template_ext_id": "corners", "name": "Total Corners",
             "outcomes": [{"id": f"o{i}", "name": "Over 5", "odds": 1.7}]}
            for i in range(50)
        ]
        report = atlas.make_atlas([snapshot(many, requested_groups=["Main", "Absent"])])
        self.assertEqual(report["fixtures"][0]["missing_groups"], ["Absent"])
        self.assertTrue(report["coverage_warnings"])
        self.assertEqual(report["fixtures"][0]["market_limit_indicators"][0]["markets"], 50)
        self.assertFalse(report["completeness_proven"])

    def test_mapper_crash_still_retains_unmapped_raw_market(self):
        market = {"id": "bad", "group": "Main", "template": "Asian Total",
                  "name": "Asian Total", "specifiers": "invalid",
                  "outcomes": [{"id": "x", "name": "Over 1.5", "odds": 2.0}]}
        report = atlas.make_atlas([snapshot([market])])
        self.assertEqual(report["raw_market_count"], 1)
        self.assertEqual(report["markets"][0]["raw"]["id"], "bad")
        self.assertEqual(report["markets"][0]["outcome_mapping"][0]["classification"], "UNMAPPED_RAW")
        self.assertTrue(report["fixtures"][0]["normalizer_errors"])

    def test_multiple_fixtures_keep_source_identity(self):
        second = snapshot(fixture_id="M2", stake_event_id="E2")
        report = atlas.make_atlas([snapshot(), second])
        self.assertEqual(report["fixture_count"], 2)
        self.assertEqual(report["raw_market_count"], 8)
        self.assertEqual({r["fixture_id"] for r in report["markets"]}, {"M", "M2"})

    def test_harvest_uses_upcoming_exact_fixture_and_never_live(self):
        now = datetime.now(timezone.utc)
        t = lambda d: (now + timedelta(minutes=d)).isoformat()
        pred = {
            "sports": {"match": {"id": "m", "home": "A", "away": "B",
                        "league": "L", "kickoff": t(140), "sport": "football",
                        "format": "REGULATION_90"}},
            "sealed_at": t(-5), "captured_prematch": True, "reconstructed": False,
        }
        pred["id"] = digest(pred)
        event = {"id": "e", "slug": "a-b", "status": "upcoming", "name": "A-B",
                 "competitors": [{"name": "A"}, {"name": "B"}],
                 "startTime": t(140)}
        group = {"group_names": ["main"], "receipt": {"provider": "STAKE_GRAPHQL_EXPERIMENTAL"}}
        with patch.object(atlas, "sports_events", return_value={
            "events": [event], "receipt": {
                "received_at": t(0), "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
            },
        }) as discovery, patch.object(atlas, "fixture_groups", return_value=group), patch.object(
            atlas, "raw_fixture_markets", return_value={"markets": snapshot()["markets"],
                     "receipts": [], "market_count": 4,
                     "returned_groups": ["main"], "template_cap_groups": []}
        ) as market_fetch:
            raw = atlas.harvest(pred)
        self.assertEqual(discovery.call_args.kwargs["match_type"], "upcoming")
        self.assertEqual(market_fetch.call_args.kwargs["groups"], ["main"])
        self.assertEqual(raw["requested_groups"], ["main"])
        self.assertEqual(raw["market_count"], 4)
        self.assertEqual(atlas.make_atlas([raw])["raw_market_count"], 4)

    def test_retains_empty_or_suspended_markets_and_null_odds(self):
        markets = [
            {"id": "suspended", "name": "Unknown", "group": "Odds",
             "template": "Unknown", "status": "suspended",
             "outcomes": [{"id": "null-price", "name": "None", "odds": None, "active": False}]},
            {"id": "empty", "name": "Unknown2", "group": "Odds",
             "template": "Unknown2", "status": "closed", "outcomes": []},
        ]
        report = atlas.make_atlas([snapshot(markets)])
        self.assertEqual(report["raw_market_count"], 2)
        self.assertEqual(report["raw_outcome_count"], 1)
        self.assertIsNone(report["markets"][0]["raw"]["outcomes"][0]["odds"])
        self.assertEqual(report["markets"][1]["raw"]["outcomes"], [])
        self.assertEqual(report["markets"][0]["outcome_mapping"][0]["classification"], "UNMAPPED_RAW")

    def test_raw_graphql_preserves_null_odds_and_empty_outcomes(self):
        payload = {"data": {"slugFixture": {"id": "e", "groups": [{
            "name": "main", "translation": "Markets", "id": "g1",
            "templates": [{"id": "t", "name": "Some Template", "extId": "ext",
                           "markets": [
                               {"id": "m1", "name": "Suspended", "outcomes": [
                                   {"id": "a", "odds": None, "name": "Yes", "active": False}
                               ]},
                               {"id": "m2", "name": "Empty", "outcomes": []},
                           ]}]
        }]}}}
        with patch.object(atlas, "_post_graphql", return_value={
            "data": payload, "receipt": {"http_status": 200}
        }) as api:
            result = atlas.raw_fixture_markets("exact", ["main"])
        self.assertEqual(result["market_count"], 2)
        self.assertIsNone(result["markets"][0]["outcomes"][0]["odds"])
        self.assertEqual(result["markets"][1]["outcomes"], [])
        self.assertEqual(api.call_args.kwargs["operation_name"], "FixtureGroupMarkets")

    def test_harvest_rejects_unsealed_before_request(self):
        prediction = {"captured_prematch": False, "reconstructed": False,
                      "sports": {"match": {"sport": "football", "format": "REGULATION_90",
                                "home": "A", "away": "B", "kickoff": stamp(50)}},
                      "sealed_at": stamp(-10)}
        prediction["id"] = digest(prediction)
        with patch.object(atlas, "sports_events") as network:
            with self.assertRaises(ValueError):
                atlas.harvest(prediction)
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
