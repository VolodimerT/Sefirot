"""Boundary tests for the experimental read-only Stake price snapshot."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sefirot.stake_provider import exact_event, fixture_markets, research_snapshot, sports_events


def fixture():
    start = datetime(2030, 1, 1, 10, tzinfo=timezone.utc)
    stamp = lambda minutes: (start + timedelta(minutes=minutes)).isoformat()
    prediction = {
        "sports": {"match": {"id": "M-STAKE", "home": "Team A", "away": "Team B",
                              "league": "League", "kickoff": stamp(180),
                              "sport": "football", "format": "REGULATION_90"}},
        "sealed_at": stamp(0), "captured_prematch": True, "reconstructed": False,
        "candidates": [],
    }
    event = {
        "id": "stake-event-1", "slug": "team-a-team-b", "name": "Team A - Team B",
        "startTime": stamp(180),
        "sport": {"name": "Soccer", "slug": "soccer"},
        "league": {"name": "League", "slug": "league"},
        "competitors": [{"name": "Team A"}, {"name": "Team B"}],
    }
    markets = [
        {"id": "m1", "name": "1x2", "group": "threeway", "template": "1x2",
         "specifiers": None, "outcomes": [
            {"id": "o1", "name": "Team A", "odds": 1.8, "active": True, "customBetAvailable": True},
            {"id": "o2", "name": "Draw", "odds": 3.6, "active": True, "customBetAvailable": True},
            {"id": "o3", "name": "Team B", "odds": 4.5, "active": True, "customBetAvailable": True},
         ]},
    ]
    return prediction, event, markets, stamp(3)


class Reply:
    status = 200
    def __init__(self, payload): self.payload = payload
    def read(self, limit): return json.dumps(self.payload).encode("utf-8")
    def close(self): pass


class SequenceOpener:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        return Reply(self.payloads.pop(0))


class StakeProviderTests(unittest.TestCase):
    def test_current_fixture_query_uses_auth_and_apollo_headers_without_persisting_token(self):
        prediction, event, _, _ = fixture()
        payload = {"data": {"slugSport": {
            "id": "s1", "name": "Soccer", "slug": "soccer",
            "tournamentList": [{
                "id": "l1", "name": "League", "slug": "league",
                "category": {"id": "c1", "name": "International", "slug": "international",
                             "sport": {"id": "s1", "name": "Soccer", "slug": "soccer"}},
                "fixtureList": [{
                    "id": event["id"], "slug": event["slug"], "name": event["name"],
                    "status": "active", "provider": "x", "extId": "sr:match:1",
                    "data": {"__typename": "SportFixtureDataMatch", "startTime": event["startTime"],
                             "competitors": event["competitors"], "teams": []},
                }],
            }],
        }}}
        opener = SequenceOpener([payload])
        packet = sports_events(first=10, token="DO_NOT_PERSIST", opener=opener)
        self.assertEqual(packet["events"][0]["id"], event["id"])
        req = opener.requests[0]
        self.assertEqual(req.headers.get("X-access-token"), "DO_NOT_PERSIST")
        self.assertEqual(req.headers.get("X-apollo-operation-name"), "SportTournamentFixtureList")
        self.assertNotIn("DO_NOT_PERSIST", json.dumps(packet))
        self.assertFalse(packet["receipt"]["monetary_permission"])

    def test_fixture_markets_two_stage_parses_raw_group_template_and_line(self):
        groups = {"data": {"slugFixture": {"id": "fx", "groups": [
            {"id": "g1", "name": "handicap", "translation": "Handicap", "rank": 1}
        ]}}}
        markets = {"data": {"slugFixture": {"id": "fx", "groups": [{
            "id": "g1", "name": "handicap", "translation": "Handicap", "rank": 1,
            "templates": [{"id": "t1", "extId": "asian-handicap", "rank": 1,
                           "name": "Asian Handicap", "markets": [{
                "id": "m1", "name": "Asian Handicap", "status": "active",
                "extId": "m", "specifiers": "hcp=-1.0", "customBetAvailable": True,
                "provider": "betradar", "outcomes": [
                    {"id": "o1", "active": True, "odds": 1.91, "name": "Team A",
                     "customBetAvailable": True},
                    {"id": "o2", "active": True, "odds": 2.02, "name": "Team B",
                     "customBetAvailable": True},
                ]
            }]}],
        }]}}}
        opener = SequenceOpener([groups, markets])
        packet = fixture_markets("team-a-team-b", token="TOKEN", opener=opener)
        self.assertEqual(packet["market_count"], 1)
        self.assertEqual(packet["markets"][0]["group"], "handicap")
        self.assertEqual(packet["markets"][0]["template"], "Asian Handicap")
        self.assertEqual(packet["markets"][0]["specifiers"], "hcp=-1.0")
        self.assertEqual(packet["markets"][0]["outcomes"][0]["odds"], 1.91)

    def test_exact_fixture_never_swaps_or_fuzzy_matches(self):
        prediction, event, _, received = fixture()
        self.assertEqual(exact_event([event], prediction, received)["id"], event["id"])
        swapped = json.loads(json.dumps(event))
        swapped["competitors"].reverse()
        with self.assertRaises(ValueError): exact_event([swapped], prediction, received)
        fuzzy = json.loads(json.dumps(event))
        fuzzy["competitors"][0]["name"] = "Team A FC"
        with self.assertRaises(ValueError): exact_event([fuzzy], prediction, received)

    def test_research_snapshot_keeps_raw_names_and_blocks_execution(self):
        prediction, event, markets, received = fixture()
        snap = research_snapshot(event, prediction, received, markets, [{"provider": "STAKE_GRAPHQL_EXPERIMENTAL"}])
        self.assertEqual(snap["normalization"], "RAW_STAKE_NAMES_ONLY")
        self.assertEqual(snap["market_count"], 1)
        self.assertEqual(snap["markets"][0]["name"], "1x2")
        self.assertFalse(snap["monetary_permission"])
        self.assertFalse(snap["execution_enabled"])
        self.assertIsNone(snap["provider_market_timestamp"])

    def test_live_time_and_missing_slug_fail_closed(self):
        prediction, event, markets, _ = fixture()
        live = prediction["sports"]["match"]["kickoff"]
        with self.assertRaises(ValueError):
            research_snapshot(event, prediction, live, markets)
        broken = json.loads(json.dumps(event)); broken.pop("slug")
        with self.assertRaises(ValueError):
            exact_event([broken], prediction, prediction["sealed_at"])


if __name__ == "__main__":
    unittest.main()
