"""Synthetic original-response envelopes; no network, live credential or fitting."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from research.gateway_evidence_v44 import inspect
from scripts.gateway_evidence_archive import main
from test_operations_upgrade import row, stamp


def envelope(endpoint='status'):
    params = {} if endpoint == 'status' else {'id': 10}
    body = ({'subscription': {'active': True, 'plan': 'Pro'},
             'requests': {'current': 2, 'limit_day': 7500},
             'account': {'secret': 'PRIVATE_ACCOUNT_SENTINEL'}}
            if endpoint == 'status' else [row(10, status='NS', hours=24)])
    data = {'get': endpoint, 'parameters': {} if endpoint == 'status' else {'id': '10'},
            'errors': [], 'response': body, 'results': 1, 'paging': {'current': 1, 'total': 1}}
    wrapper = {'ok': True, 'provider': 'API_FOOTBALL_V3',
               'provider_host': 'v3.football.api-sports.io', 'endpoint': '/' + endpoint,
               'params': params, 'received_at': stamp(), 'data': data,
               'quota': {'x-ratelimit-requests-limit': '7500',
                         'x-ratelimit-requests-remaining': '7498',
                         'x-ratelimit-limit': '300', 'x-ratelimit-remaining': '299'},
               'sports_only': True, 'monetary_permission': False, 'execution_enabled': False}
    return {'schema': 'sefirot-gateway-call-v1', 'gateway_version': 12,
            'request_started_at': stamp(-.001), 'received_at': stamp(.001),
            'http_status': 200, 'request': {'endpoint': endpoint, 'params': params},
            'response': wrapper}


def raw(call):
    return json.dumps(call).encode('utf-8')


class GatewayEvidenceTests(unittest.TestCase):
    def inspect(self, call):
        return inspect(raw(call), imported_at=stamp(1))

    def test_status_whitelist_never_grants_origin_fit_or_money(self):
        out = self.inspect(envelope())
        self.assertEqual(out['requests']['remaining_day'], 7498)
        self.assertEqual(out['requests']['limit_minute'], 300)
        self.assertEqual(out['source_attestation'], 'OFFLINE_CALLER_SUPPLIED')
        self.assertFalse(out['auth_verified_by_this_process'])
        self.assertFalse(out['fit_allowed'])
        self.assertFalse(out['monetary_permission'])
        self.assertNotIn('PRIVATE_ACCOUNT_SENTINEL', str(out))

    def test_single_fixture_reuses_original_packet_validator(self):
        out = self.inspect(envelope('fixtures'))
        self.assertEqual(out['fixture']['id'], 10)
        self.assertTrue(out['prematch_observed'])
        self.assertNotIn('Team A', str(out))

    def test_postmatch_is_not_prematch(self):
        call = envelope('fixtures')
        call['response']['data']['response'] = [row(10)]
        self.assertFalse(self.inspect(call)['prematch_observed'])

    def test_inactive_and_exhausted_status_blocks(self):
        for inactive in (True, False):
            call = envelope()
            body = call['response']['data']['response']
            if inactive:
                body['subscription']['active'] = False
            else:
                body['requests']['current'] = 7500
            self.assertEqual(self.inspect(call)['status'], 'PROVIDER_GATE_BLOCKED')

    def test_missing_minute_quota_is_not_inferred_from_pro(self):
        call = envelope()
        call['response']['quota'] = {}
        self.assertIsNone(self.inspect(call)['requests']['limit_minute'])
        self.assertIn('MINUTE_QUOTA_UNKNOWN', self.inspect(call)['blockers'])

    def test_zero_quota_header_blocks_despite_positive_body_remaining(self):
        for key in ('x-ratelimit-requests-remaining', 'x-ratelimit-remaining'):
            call = envelope(); call['response']['quota'][key] = '0'
            self.assertEqual(self.inspect(call)['status'], 'PROVIDER_GATE_BLOCKED')

    def test_client_receipt_after_kickoff_not_prematch(self):
        call = envelope('fixtures'); call['received_at'] = stamp(25)
        out = inspect(raw(call), imported_at=stamp(26))
        self.assertFalse(out['prematch_observed'])

    def test_unknown_plan_never_echoes_possible_secret(self):
        call = envelope()
        call['response']['data']['response']['subscription']['plan'] = 'SECRET_PLAN_SENTINEL'
        out = self.inspect(call)
        self.assertEqual(out['subscription']['plan'], 'UNKNOWN')
        self.assertNotIn('SECRET_PLAN_SENTINEL', str(out))
        self.assertEqual(out['status'], 'PROVIDER_GATE_BLOCKED')

    def test_http_200_application_error_rejected(self):
        call = envelope()
        call['response']['data']['errors'] = {'access': 'PRIVATE_ERROR_SENTINEL'}
        with self.assertRaises(ValueError):
            self.inspect(call)

    def test_gateway_errors_never_become_status(self):
        call = envelope()
        call['response']['ok'] = False
        with self.assertRaises(ValueError):
            self.inspect(call)

    def test_chronology_future_import_and_request_inversion(self):
        for field, value in (('request_started_at', stamp(.1)), ('received_at', stamp(-1))):
            call = envelope(); call[field] = value
            with self.assertRaises(ValueError):
                self.inspect(call)
        with self.assertRaises(ValueError):
            inspect(raw(envelope()), imported_at=stamp(-1))

    def test_bool_counters_and_active_string_rejected(self):
        for field, value in (('current', True), ('limit_day', False), ('current', -1)):
            call = envelope(); call['response']['data']['response']['requests'][field] = value
            with self.assertRaises(ValueError):
                self.inspect(call)
        call = envelope(); call['response']['data']['response']['subscription']['active'] = 'true'
        with self.assertRaises(ValueError):
            self.inspect(call)

    def test_conflicting_day_or_minute_counters_rejected(self):
        for key, value in (('x-ratelimit-requests-limit', '100'), ('x-ratelimit-remaining', '301')):
            call = envelope(); call['response']['quota'][key] = value
            with self.assertRaises(ValueError):
                self.inspect(call)

    def test_quota_unknown_headers_and_non_ascii_digits_rejected(self):
        for key, value in (('authorization', 'PRIVATE_HEADER_SENTINEL'), ('x-ratelimit-limit', '３００')):
            call = envelope(); call['response']['quota'][key] = value
            with self.assertRaises(ValueError):
                self.inspect(call)

    def test_fixture_id_or_provider_echo_conflict_rejected(self):
        for target in ('fixture', 'parameters'):
            call = envelope('fixtures')
            if target == 'fixture':
                call['response']['data']['response'][0]['fixture']['id'] = 11
            else:
                call['response']['data']['parameters']['id'] = '11'
            with self.assertRaises(ValueError):
                self.inspect(call)

    def test_boolean_wrapper_parameter_cannot_equal_numeric_identity(self):
        call = envelope('fixtures'); call['request']['params']['id'] = 1
        call['response']['params'] = {'id': True}
        with self.assertRaises(ValueError):
            self.inspect(call)

    def test_multi_fixture_or_incomplete_page_rejected(self):
        for version in ('multi', 'page'):
            call = envelope('fixtures')
            if version == 'multi':
                call['response']['data']['response'].append(row(11))
                call['response']['data']['results'] = 2
            else:
                call['response']['data']['paging']['total'] = 2
            with self.assertRaises(ValueError):
                self.inspect(call)

    def test_no_league_scan_or_request_headers_allowed(self):
        call = envelope('fixtures'); call['request']['params'] = {'league': 9, 'season': 2030}
        with self.assertRaises(ValueError):
            self.inspect(call)
        call = envelope(); call['request']['headers'] = {'secret': 'PRIVATE_REQUEST_SENTINEL'}
        with self.assertRaises(ValueError):
            self.inspect(call)

    def test_byte_hash_changes_with_serialization(self):
        call = envelope()
        a = self.inspect(call)
        b = inspect(json.dumps(call, indent=2).encode(), imported_at=stamp(1))
        self.assertNotEqual(a['raw_sha256'], b['raw_sha256'])
        self.assertEqual(a['response_digest'], b['response_digest'])

    def test_duplicate_json_keys_size_and_nonfinite_rejected(self):
        for value in (b'{"secret":1,"secret":2}', b'{"secret":NaN}', b'x' * 2_000_001):
            with self.assertRaises(ValueError):
                inspect(value, imported_at=stamp(1))

    def test_cli_missing_archive_and_exclusive_private_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'receipt.json'
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--output', str(path)]), 0)
                before = path.read_bytes()
                self.assertEqual(main(['--output', str(path)]), 2)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(json.loads(before)['status'], 'MISSING_ORIGINAL_RESPONSES')
            if os.name == 'posix':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_cli_never_echoes_private_payload_or_error(self):
        with tempfile.TemporaryDirectory() as temp:
            source, target = Path(temp) / 'input.json', Path(temp) / 'output.json'
            call = envelope(); call['response']['data']['errors'] = {'secret': 'PRIVATE_ERROR_SENTINEL'}
            source.write_bytes(raw(call))
            printed = io.StringIO()
            with redirect_stdout(printed), redirect_stderr(printed):
                self.assertEqual(main(['--input', str(source), '--output', str(target)]), 2)
            self.assertNotIn('PRIVATE_ERROR_SENTINEL', printed.getvalue())
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
