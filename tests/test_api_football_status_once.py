"""Single-request API-Football probe: no real credential or network required."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.api_football_status_once import probe_once
from sefirot.football_provider import FootballRequestError


def reply(*, active=True, current=1, limit=100):
    return {"data": {"response": {
        "subscription": {"active": active, "plan": "FREE", "account_id": "SECRET_ID_DO_NOT_PRINT"},
        "requests": {"current": current, "limit_day": limit},
    }}, "receipt": {"provider": "API_FOOTBALL_V3", "private": "NEVER_PRINT"}}


class OneShotProviderProbeTests(unittest.TestCase):
    def test_default_never_contacts_provider(self):
        fetch, read = Mock(), Mock()
        result = probe_once(fetch=fetch, credential_reader=read)
        self.assertEqual(result["status"], "NOT_EXECUTED")
        self.assertFalse(result["request_attempted"])
        fetch.assert_not_called()
        read.assert_not_called()

    def test_missing_credential_never_sends_request(self):
        fetch = Mock()
        read = Mock(side_effect=ValueError("KEY_IS_PRIVATE"))
        result = probe_once(confirm=True, fetch=fetch, credential_reader=read)
        self.assertEqual(result["status"], "CREDENTIAL_UNAVAILABLE")
        self.assertNotIn("KEY_IS_PRIVATE", json.dumps(result))
        fetch.assert_not_called()

    def test_active_one_call_drops_sensitive_account_and_raw_body(self):
        fetch = Mock(return_value=reply())
        result = probe_once(confirm=True, fetch=fetch,
                            credential_reader=lambda _: "DUMMY_FAKE_KEY")
        fetch.assert_called_once_with("status")
        self.assertEqual(result["status"], "SUBSCRIPTION_ACTIVE")
        self.assertEqual(result["requests_limit_day"], 100)
        self.assertEqual(result["requests_current"], 1)
        self.assertFalse(result["monetary_permission"])
        self.assertFalse(result["execution_enabled"])
        serialized = json.dumps(result)
        for value in ("DUMMY_FAKE_KEY", "SECRET_ID_DO_NOT_PRINT", "NEVER_PRINT", "FREE"):
            self.assertNotIn(value, serialized)

    def test_suspended_account_stays_sanitized(self):
        fetch = Mock(side_effect=FootballRequestError(
            {"access": "Your account has been suspended", "private": "SENSITIVE_VALUE"}))
        result = probe_once(confirm=True, fetch=fetch, credential_reader=lambda _: "DUMMY")
        self.assertEqual(result["status"], "PROVIDER_REJECTED")
        self.assertEqual(result["reason"], "PROVIDER_ACCOUNT_SUSPENDED")
        self.assertNotIn("SENSITIVE_VALUE", json.dumps(result))
        fetch.assert_called_once_with("status")

    def test_inactive_subscription_not_ready(self):
        fetch = Mock(return_value=reply(active=False))
        result = probe_once(confirm=True, fetch=fetch, credential_reader=lambda _: "DUMMY")
        self.assertEqual(result["status"], "SUBSCRIPTION_INACTIVE")
        self.assertFalse(result["subscription_active"])

    def test_quota_numbers_need_nonnegative_integers(self):
        fetch = Mock(return_value=reply(current="TOKEN_SECRET", limit=-1))
        result = probe_once(confirm=True, fetch=fetch, credential_reader=lambda _: "DUMMY")
        self.assertIsNone(result["requests_current"])
        self.assertIsNone(result["requests_limit_day"])
        self.assertNotIn("TOKEN_SECRET", json.dumps(result))

    def test_connection_failure_cannot_leak_exception_contents(self):
        fetch = Mock(side_effect=ValueError("HTTP private key URL private-token"))
        result = probe_once(confirm=True, fetch=fetch, credential_reader=lambda _: "DUMMY")
        self.assertEqual(result["status"], "PROBE_FAILED")
        self.assertNotIn("private-token", json.dumps(result))
        fetch.assert_called_once_with("status")

    def test_malformed_response_blocks_without_second_attempt(self):
        fetch = Mock(return_value={"data": {"response": None}})
        result = probe_once(confirm=True, fetch=fetch, credential_reader=lambda _: "DUMMY")
        self.assertEqual(result["status"], "PROBE_FAILED")
        fetch.assert_called_once_with("status")


if __name__ == "__main__":
    unittest.main()
