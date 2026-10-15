"""Keep shared API-Football budget-denial reasons readable but fail closed."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sefirot import football_gateway as gateway


class _Response:
    def __init__(self, status, body):
        self.status = status
        self.body = json.dumps(body).encode("utf-8")
        self.closed = False

    def read(self, _limit):
        return self.body

    def close(self):
        self.closed = True


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, _request, timeout):
        assert timeout == 15
        return self.response


class SportsBudgetResponseTests(unittest.TestCase):
    def _request(self, status, data):
        response = _Response(status, data)
        url = "https://kxqpwgwihtjmqlcxgfxp.supabase.co/functions/v1/sefirot-sports-gateway"
        with patch.dict(gateway.os.environ, {"SEFIROT_SPORTS_GATEWAY_URL": url}), \
             patch.object(gateway, "credential", return_value="SAFE_TEST_TOKEN"):
            return gateway.get_sports("status", {}, opener=_Opener(response))

    def test_allowlisted_budget_reasons_preserved_without_upstream_text(self):
        for reason in ("PAUSED", "BUSY", "UNFINISHED_ATTEMPT",
                       "STALE_BUDGET", "DAILY_LIMIT", "MINUTE_LIMIT"):
            with self.subTest(reason=reason):
                with self.assertRaises(gateway.SportsBudgetGateError) as e:
                    self._request(429, {"ok": False, "error": "SHARED_BUDGET_STOP",
                                        "budget_reason": reason, "raw_secret": "DONOTSHOW"})
                self.assertEqual(e.exception.code, "SHARED_BUDGET_" + reason)
                self.assertNotIn("DONOTSHOW", str(e.exception))

    def test_unknown_budget_reason_fails_closed(self):
        with self.assertRaises(ValueError) as e:
            self._request(429, {"ok": False, "error": "SHARED_BUDGET_STOP",
                                "budget_reason": "SECRET_TOKEN_DO_NOT_SHOW"})
        self.assertNotIsInstance(e.exception, gateway.SportsBudgetGateError)
        self.assertNotIn("SECRET_TOKEN", str(e.exception))

    def test_auth_or_network_failure_not_disguised_as_budget_denial(self):
        for status in (401, 502):
            with self.subTest(status=status):
                with self.assertRaises(ValueError) as e:
                    self._request(status, {"ok": False, "error": "SHARED_BUDGET_STOP",
                                            "budget_reason": "PAUSED"})
                self.assertNotIsInstance(e.exception, gateway.SportsBudgetGateError)


if __name__ == "__main__":
    unittest.main()
