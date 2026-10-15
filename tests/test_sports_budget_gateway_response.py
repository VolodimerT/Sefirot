"""Keep shared API-Football budget-denial reasons readable but fail closed."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sefirot import football_gateway as gateway
from sefirot import api_health


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
        self.calls = 0

    def open(self, _request, timeout):
        assert timeout == 15
        self.calls += 1
        return self.response


class SportsBudgetResponseTests(unittest.TestCase):
    def _request(self, status, data):
        response = _Response(status, data)
        opener = _Opener(response)
        url = "https://kxqpwgwihtjmqlcxgfxp.supabase.co/functions/v1/sefirot-sports-gateway"
        with patch.dict(gateway.os.environ, {"SEFIROT_SPORTS_GATEWAY_URL": url}), \
             patch.object(gateway, "credential", return_value="SAFE_TEST_TOKEN"):
            try:
                return gateway.get_sports("status", {}, opener=opener.open)
            finally:
                self.assertTrue(response.closed)
                self.assertEqual(opener.calls, 1)

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

    def test_budget_denial_requires_explicit_false_ok(self):
        for value in (True, None, 0, "false"):
            with self.subTest(ok=value), self.assertRaises(ValueError) as e:
                self._request(429, {"ok": value, "error": "SHARED_BUDGET_STOP", "budget_reason": "PAUSED"})
            self.assertNotIsInstance(e.exception, gateway.SportsBudgetGateError)

    def test_malformed_budget_reasons_never_escape_or_become_known_denials(self):
        for reason in (None, True, 7, [], {}, "PRIVATE_UNKNOWN"):
            with self.subTest(reason=reason), self.assertRaises(ValueError) as e:
                self._request(429, {"ok": False, "error": "SHARED_BUDGET_STOP", "budget_reason": reason})
            self.assertNotIsInstance(e.exception, gateway.SportsBudgetGateError)
            self.assertNotIn("PRIVATE_UNKNOWN", str(e.exception))

    def test_native_http_error_429_closes_body_and_preserves_only_enum(self):
        body = io.BytesIO(json.dumps({"ok": False, "error": "SHARED_BUDGET_STOP",
            "budget_reason": "PAUSED", "raw_secret": "OWNED_PRIVATE_MARKER"}).encode())
        def opening(request, timeout):
            raise HTTPError('https://gateway.test/?OWNED_PRIVATE_MARKER', 429,
                            'OWNED_PRIVATE_MARKER', {}, body)
        with patch.dict(gateway.os.environ, {"SEFIROT_SPORTS_GATEWAY_URL":
                'https://abcdefghijklmnopqrst.supabase.co/functions/v1/sefirot-sports-gateway'}), \
             patch.object(gateway, 'credential', return_value='OWNED_TEST_TOKEN'), \
             self.assertRaises(gateway.SportsBudgetGateError) as e:
            gateway.get_sports('status', {}, opener=opening)
        self.assertEqual(e.exception.code, 'SHARED_BUDGET_PAUSED')
        self.assertNotIn('OWNED_PRIVATE_MARKER', str(e.exception))
        self.assertTrue(body.closed)

    def test_health_preserves_fixed_budget_reason_without_claiming_provider_failure(self):
        credentials = {'API_FOOTBALL_KEY': 'MISSING_OR_INVALID',
            'SEFIROT_ODDS_API_KEY': 'MISSING_OR_INVALID', 'STAKE_API_TOKEN': 'MISSING_OR_INVALID'}
        for reason in ('PAUSED', 'BUSY', 'UNFINISHED_ATTEMPT', 'STALE_BUDGET', 'DAILY_LIMIT', 'MINUTE_LIMIT'):
            def request(*args, **kwargs):
                return self._request(429, {'ok': False, 'error': 'SHARED_BUDGET_STOP', 'budget_reason': reason})
            with self.subTest(reason=reason), \
                 patch.object(api_health, 'credential_status', return_value=credentials), \
                 patch.object(api_health, 'transport_status', return_value={'transport': 'SUPABASE_GATEWAY', 'credential_configured': True}), \
                 patch.object(api_health, 'get', side_effect=request) as network:
                result = api_health.check()
            self.assertEqual(result['providers']['api_football']['reason'], 'SHARED_BUDGET_' + reason)
            self.assertEqual(result['status'], 'API_CHECK_FAILED')
            self.assertFalse(result['admission_ready'])
            self.assertFalse(result['monetary_permission'])
            self.assertFalse(result['execution_enabled'])
            self.assertEqual(network.call_count, 1)

    def test_gateway_to_probe_preserves_reason_and_stops_remaining_batch(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        import chat_sports_probe as probe
        for reason in ('PAUSED', 'BUSY', 'UNFINISHED_ATTEMPT', 'STALE_BUDGET', 'DAILY_LIMIT', 'MINUTE_LIMIT'):
            def request(*args, **kwargs):
                return self._request(429, {'ok': False, 'error': 'SHARED_BUDGET_STOP', 'budget_reason': reason})
            with self.subTest(reason=reason), \
                 patch.object(probe, 'get_sports', side_effect=request) as network, \
                 patch.object(probe, 'transport_status', return_value={'transport': 'SUPABASE_GATEWAY'}):
                result = probe.collect({'queries': [{'endpoint': 'status', 'params': {}},
                    {'endpoint': 'fixtures', 'params': {'id': 123}}]})
            self.assertEqual(network.call_count, 1)
            self.assertEqual(len(result['queries']), 1)
            self.assertEqual(result['queries'][0]['reason'], 'SHARED_BUDGET_' + reason)
            self.assertEqual(result['queries'][0]['status'], 'ERROR')
            self.assertFalse(result['monetary_permission'])
            self.assertFalse(result['automatic_execution'])

    def test_constructor_refuses_invalid_reasons_without_arbitrary_text(self):
        for value in ([], {}, 'OWNED_PRIVATE_MARKER'):
            with self.subTest(value=value), self.assertRaises(ValueError) as e:
                gateway.SportsBudgetGateError(value)
            self.assertNotIn('OWNED_PRIVATE_MARKER', str(e.exception))


if __name__ == "__main__":
    unittest.main()
