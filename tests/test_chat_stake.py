"""Fail-closed unit tests: Stake never reads odds without a real sealed forecast."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
import chat_stake


VALID_ID = "a" * 64


class StakeChatTests(unittest.TestCase):
    def repository(self, synthetic=False):
        repo = Mock()
        repo.verify.return_value = True
        repo.get.return_value = {"synthetic": synthetic}
        return repo

    def test_input_rejects_unsealed_lookup_without_network(self):
        repo = self.repository()
        with patch.object(chat_stake, "sports_events") as network:
            for arg in ({}, {"prediction_id": "wrong"}, {"fixture": "secret"},
                        {"prediction_id": VALID_ID, "book": "stake"}):
                with self.subTest(arg=arg):
                    with self.assertRaises(ValueError):
                        chat_stake.collect(repo, arg)
            network.assert_not_called()

    def test_synthetic_prediction_rejected_before_network(self):
        repo = self.repository(synthetic=True)
        with patch.object(chat_stake, "sports_events") as network:
            with self.assertRaises(ValueError):
                chat_stake.collect(repo, {"prediction_id": VALID_ID})
            network.assert_not_called()

    def test_seal_gate_rejects_before_any_market_call(self):
        repo = self.repository()
        with patch.object(chat_stake, "require_prematch_seal", side_effect=ValueError("expired")):
            with patch.object(chat_stake, "sports_events") as network:
                with self.assertRaises(ValueError):
                    chat_stake.collect(repo, {"prediction_id": VALID_ID})
                network.assert_not_called()

    def test_sanitized_read_only_snapshot(self):
        repo = self.repository()
        receipt = {"operation_name": "SportTournamentFixtureList", "http_status": 200}
        def mock_report(*args):
            return {"fixture_id": "m", "home": "Home", "away": "Away",
                    "kickoff": "2030-01-01T10:00:00+00:00", "received_at": "2030-01-01T09:00:00+00:00",
                    "stake_event_id": "e", "market_count": 1, "hash": "rawhash",
                    "retrieval_receipts": [receipt]}
        normalized = {"main_quotes": [{"market": {"kind": "DOUBLE_CHANCE", "side": "X2"}, "odds": 1.40}],
                      "small_quotes": [{"raw_name": "Total Corners", "odds": 1.75}],
                      "main_quote_count": 1, "small_quote_count": 1, "hash": "normhash"}
        with patch.object(chat_stake, "require_prematch_seal", return_value={}):
            with patch.object(chat_stake, "sports_events", return_value={"events": [{}], "receipt": receipt}) as network:
                with patch.object(chat_stake, "exact_event", return_value={"slug": "valid"}):
                    with patch.object(chat_stake, "fixture_markets", return_value={"markets": [{}], "receipts": []}):
                        with patch.object(chat_stake, "research_snapshot", side_effect=mock_report):
                            with patch.object(chat_stake, "normalize_snapshot", return_value=normalized):
                                result = chat_stake.collect(repo, {"prediction_id": VALID_ID})
        network.assert_called_once()
        self.assertEqual(result["stage"], "STAKE_SNAPSHOT_RESEARCH")
        self.assertEqual(result["main_quote_count"], 1)
        self.assertFalse(result["monetary_permission"])
        self.assertFalse(result["execution_enabled"])
        self.assertNotIn("STAKE_API_TOKEN", repr(result))


if __name__ == "__main__":
    unittest.main()
