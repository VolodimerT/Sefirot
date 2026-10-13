"""Research API-Football chat probe never exposes credentials or places bets."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"src"),str(ROOT/"scripts")]
import chat_sports_probe as probe


class ProbeTests(unittest.TestCase):
    def test_refuses_unbounded_or_unsupported_requests_before_network(self):
        bad = [
            {}, {"endpoint":"odds","params":{}},
            {"endpoint":"fixtures","params":{"date":"2026-10-13"}},
            {"endpoint":"fixtures/statistics","params":{"fixture":"wrong"}},
            {"endpoint":"fixtures","params":{"team":1,"last":100}},
            {"endpoint":"fixtures/lineups","params":{"fixture":1,"token":"X"}},
        ]
        with patch.object(probe, "get_sports") as network:
            for q in bad:
                with self.subTest(q=q):
                    with self.assertRaises(ValueError):
                        probe.collect({"queries":[q]})
            network.assert_not_called()

    def test_collects_fixture_statistics_with_receipt_and_no_secret(self):
        packet = {
            "data":{"response":[
                {"team":{"id":1,"name":"Home"},"statistics":[
                    {"type":"Corner Kicks","value":7},
                    {"type":"Shots on Goal","value":4},
                    {"type":"Yellow Cards","value":2},
                    {"type":"Secret Extra","value":"NOPE"}]},
                {"team":{"id":2,"name":"Away"},"statistics":[
                    {"type":"Corner Kicks","value":3},
                    {"type":"Fouls","value":12}]}
            ]},
            "receipt":{"provider":"API_FOOTBALL_V3","provider_host":"v3.football.api-sports.io",
                       "endpoint":"/fixtures/statistics","parameters":{"fixture":123},
                       "received_at":"2026-10-13T06:00:00Z","payload_hash":"abc",
                       "http_status":200,"quota":{"x-requests-remaining":"50"}},
        }
        with patch.object(probe,"get_sports",return_value=packet) as network, \
             patch.object(probe,"transport_status",return_value={"transport":"SUPABASE_GATEWAY","credential_configured":True}):
            result=probe.collect({"queries":[{"endpoint":"fixtures/statistics","params":{"fixture":123}}]})
        network.assert_called_once_with("fixtures/statistics",{"fixture":123},require_shared_budget=True)
        self.assertEqual(result["queries"][0]["count"],2)
        self.assertEqual(result["queries"][0]["rows"][0]["statistics"]["Corner Kicks"],7)
        self.assertNotIn("Secret Extra",repr(result))
        self.assertFalse(result["monetary_permission"])
        self.assertFalse(result["execution_enabled"])

    def test_auth_failure_does_not_retry_or_disclose_error_text(self):
        with patch.object(probe,"get_sports",side_effect=ValueError("TOKEN_SECRET_DO_NOT_PRINT")) as network, \
             patch.object(probe,"transport_status",return_value={"credential_configured":False}):
            result=probe.collect({"queries":[
                {"endpoint":"status","params":{}},
                {"endpoint":"fixtures","params":{"id":123}},
            ]})
        self.assertEqual(network.call_count,1)
        self.assertEqual(result["queries"][0]["reason"],"PROVIDER_TRANSPORT_OR_AUTH_UNAVAILABLE")
        self.assertNotIn("TOKEN_SECRET_DO_NOT_PRINT",repr(result))


if __name__=="__main__":
    unittest.main()

