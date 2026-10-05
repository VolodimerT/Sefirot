"""Boundary tests for the experimental read-only Stake price snapshot."""
import io
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sefirot.stake_provider import exact_event, research_snapshot, sports_events


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
        "id": "stake-event-1", "name": "Team A - Team B", "startTime": stamp(180),
        "sport": {"name": "Football", "slug": "football"},
        "league": {"name": "League", "slug": "league"},
        "competitors": [{"name": "Team A"}, {"name": "Team B"}],
        "markets": [
            {"name": "1x2", "outcomes": [
                {"name": "Team A", "odds": 1.8},
                {"name": "Draw", "odds": 3.6},
                {"name": "Team B", "odds": 4.5},
            ]},
            {"name": "Both Teams to Score", "outcomes": [
                {"name": "Yes", "odds": 1.9}, {"name": "No", "odds": 1.85},
            ]},
        ],
    }
    return prediction, event, stamp(3)


class Reply:
    status = 200
    def __init__(self, payload): self.payload = payload
    def read(self, limit): return json.dumps(self.payload).encode("utf-8")
    def close(self): pass


class Opener:
    def __init__(self, payload): self.payload = payload; self.request = None
    def open(self, request, timeout): self.request = request; return Reply(self.payload)


class StakeProviderTests(unittest.TestCase):
    def test_graphql_request_uses_header_without_persisting_token(self):
        _, event, _ = fixture()
        payload = {"data": {"sportsEvents": {"edges": [{"node": event}]}}}
        opener = Opener(payload)
        packet = sports_events(first=10, token="DO_NOT_PERSIST", opener=opener)
        self.assertEqual(packet["events"][0]["id"], event["id"])
        self.assertEqual(opener.request.headers.get("X-access-token"), "DO_NOT_PERSIST")
        self.assertNotIn("DO_NOT_PERSIST", json.dumps(packet))
        self.assertFalse(packet["receipt"]["monetary_permission"])

    def test_exact_fixture_never_swaps_or_fuzzy_matches(self):
        prediction, event, received = fixture()
        self.assertEqual(exact_event([event], prediction, received)["id"], event["id"])
        swapped = json.loads(json.dumps(event))
        swapped["competitors"].reverse()
        with self.assertRaises(ValueError): exact_event([swapped], prediction, received)
        fuzzy = json.loads(json.dumps(event))
        fuzzy["competitors"][0]["name"] = "Team A FC"
        with self.assertRaises(ValueError): exact_event([fuzzy], prediction, received)

    def test_research_snapshot_keeps_raw_names_and_blocks_execution(self):
        prediction, event, received = fixture()
        snap = research_snapshot(event, prediction, received, {"provider": "STAKE_GRAPHQL_EXPERIMENTAL"})
        self.assertEqual(snap["normalization"], "RAW_STAKE_NAMES_ONLY")
        self.assertEqual(snap["market_count"], 2)
        self.assertEqual(snap["markets"][0]["name"], "1x2")
        self.assertFalse(snap["monetary_permission"])
        self.assertFalse(snap["execution_enabled"])
        self.assertIsNone(snap["provider_market_timestamp"])

    def test_duplicate_outcome_and_live_time_fail_closed(self):
        prediction, event, received = fixture()
        broken = json.loads(json.dumps(event))
        broken["markets"][0]["outcomes"][1]["name"] = "Team A"
        with self.assertRaises(ValueError): research_snapshot(broken, prediction, received)
        with self.assertRaises(ValueError): research_snapshot(event, prediction, prediction["sports"]["match"]["kickoff"])


if __name__ == "__main__":
    unittest.main()
