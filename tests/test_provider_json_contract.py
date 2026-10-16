"""Owned loopback HTTP responses only; no provider or genuine credentials."""
from datetime import datetime, timezone
from contextlib import redirect_stdout, redirect_stderr
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import io
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot import api_health, football_gateway, football_provider, odds_provider, stake_provider
from sefirot.cli import main
from sefirot.contracts import digest

MARKER = 'OWNED_PRIVATE_JSON_MARKER'
CLIENTS = ('football', 'odds_catalogue', 'odds_events', 'gateway', 'stake')


class ProviderJsonContractTests(unittest.TestCase):
    def setUp(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.calls += 1
                self.send_response(200)
                self.send_header('Content-Length', str(len(self.server.payload)))
                self.end_headers()
                self.wfile.write(self.server.payload)

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.do_GET()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def payload(self, client):
        data = {'errors': [], 'response': {}}
        if client.startswith('odds_'):
            return []
        if client == 'stake':
            return {'data': {}}
        if client == 'gateway':
            return {'ok': True, 'provider': 'API_FOOTBALL_V3',
                'provider_host': football_provider.HOST, 'endpoint': '/status', 'params': {},
                'sports_only': True, 'monetary_permission': False, 'execution_enabled': False,
                'received_at': '2030-01-01T09:00:00+00:00', 'data': data}
        return data

    def call(self, client, raw):
        self.server.payload, self.server.calls = raw, 0
        owner = self
        self.response = None

        class Connection(http.client.HTTPConnection):
            def __init__(inner, *args, **kwargs):
                super().__init__('127.0.0.1', owner.server.server_port, timeout=5)
                owner.addCleanup(inner.close)

            def getresponse(inner):
                owner.response = super().getresponse()
                inner.owned_response = owner.response
                return owner.response

            def close(inner):
                response = getattr(inner, 'owned_response', None)
                if response is not None:
                    response.close()
                super().close()

        class Opener:
            def open(inner, request, timeout):
                conn = Connection()
                conn.request('POST', '/owned', body=request.data,
                             headers={'Content-Type': 'application/json'})
                return conn.getresponse()

        if client == 'football':
            return football_provider.get('status', api_key=MARKER, connection_factory=Connection)
        if client == 'odds_catalogue':
            return odds_provider.sports_catalogue(api_key=MARKER, connection_factory=Connection)
        if client == 'odds_events':
            return odds_provider.events('soccer_owned', api_key=MARKER, connection_factory=Connection)
        if client == 'stake':
            return stake_provider._post_graphql('query Owned { id }', {}, token=MARKER,
                opener=Opener(), operation_name='Owned')
        with patch.dict('os.environ', {'SEFIROT_SPORTS_GATEWAY_URL':
                'https://abcdefghijklmnopqrst.supabase.co/functions/v1/sefirot-sports-gateway'}), \
             patch.object(football_gateway, 'credential', return_value=MARKER):
            return football_gateway.get_sports('status', opener=Opener().open,
                clock=lambda: datetime(2030, 1, 1, 9, tzinfo=timezone.utc))

    def reject(self, client, raw):
        messages = {'football': 'provider returned invalid JSON',
            'odds_catalogue': 'provider returned invalid JSON',
            'odds_events': 'odds provider returned invalid JSON; PASS',
            'gateway': 'sports gateway returned invalid JSON',
            'stake': 'stake provider returned invalid JSON; PASS'}
        with self.assertRaises(ValueError) as caught:
            self.call(client, raw)
        self.assertEqual(str(caught.exception), messages[client])
        self.assertNotIn(MARKER, str(caught.exception))
        self.assertEqual(self.server.calls, 1)
        self.assertTrue(self.response.closed)

    def test_duplicate_root_members_cannot_receive_a_receipt(self):
        for client in CLIENTS:
            payload = json.dumps(self.payload(client)).encode()
            raw = (b'[{"id":"first","id":"second"}]' if client.startswith('odds_')
                   else payload[:-1] + b',"errors":[],"errors":[]}' if client == 'football'
                   else payload[:-1] + b',"data":{},"data":{}}')
            with self.subTest(client=client):
                self.reject(client, raw)

    def test_nested_and_escaped_duplicate_members_are_rejected(self):
        for client in CLIENTS:
            raw = b'{"nested":{"id":"OWNED_PRIVATE_JSON_MARKER","\\u0069d":"second"}}'
            if client.startswith('odds_'):
                raw = b'[' + raw + b']'
            with self.subTest(client=client):
                self.reject(client, raw)

    def test_nonfinite_numbers_and_exponent_overflow_are_rejected(self):
        for client in CLIENTS:
            for number in (b'NaN', b'Infinity', b'-Infinity', b'1e999'):
                payload = json.dumps(self.payload(client)).encode()
                raw = (b'[{"x":' + number + b'}]' if client.startswith('odds_')
                       else payload[:-1] + b',"extra":' + number + b'}')
                with self.subTest(client=client, number=number):
                    self.reject(client, raw)

    def test_json_depth_is_bounded_before_receipt_or_shape_validation(self):
        for client in CLIENTS:
            for depth in (65, 1200):
                with self.subTest(client=client, depth=depth):
                    self.reject(client, b'{"x":' * (depth - 1) + b'{}' + b'}' * (depth - 1))

    def test_invalid_encoding_syntax_and_oversized_integer_have_safe_errors(self):
        for client in CLIENTS:
            for raw in (b'{"x":"\xff"}', b'{"x":', b'{"x":' + b'9' * 5000 + b'}'):
                with self.subTest(client=client, size=len(raw)):
                    self.reject(client, raw)

    def test_valid_responses_preserve_data_hashes_and_single_request(self):
        for client in CLIENTS:
            payload = self.payload(client)
            with self.subTest(client=client):
                packet = self.call(client, json.dumps(payload).encode())
                if client == 'odds_events':
                    self.assertEqual(packet, payload)
                else:
                    expected = payload['data'] if client == 'gateway' else payload
                    self.assertEqual(packet['data'], expected)
                    self.assertEqual(packet['receipt']['payload_hash'], digest(expected))
                self.assertEqual(self.server.calls, 1)
                self.assertTrue(self.response.closed)

    def test_depth_boundary_and_braces_inside_strings_remain_valid(self):
        for nested in (json.loads(b'{"x":' * 61 + b'{}' + b'}' * 61),
                       {'text': '{["' * 1000}):
            for client in CLIENTS:
                payload = self.payload(client)
                if client.startswith('odds_'):
                    payload.append(nested)
                elif client == 'gateway':
                    payload['data']['extra'] = nested
                else:
                    payload['extra'] = nested
                with self.subTest(client=client, nested=type(nested).__name__):
                    self.call(client, json.dumps(payload).encode())
                    self.assertEqual(self.server.calls, 1)
                    self.assertTrue(self.response.closed)

    def with_extra(self, client, extra):
        payload = self.payload(client)
        if client.startswith('odds_'):
            payload.append(extra)
        elif client == 'gateway':
            payload['data']['extra'] = extra
        else:
            payload['extra'] = extra
        return payload

    def test_unpaired_unicode_values_are_rejected_before_hash_or_return(self):
        for client in CLIENTS:
            for value in ('\ud800', '\udfff', 'prefix\udc00suffix', '\ud800\ud800'):
                payload = self.with_extra(client, {'nested': [value]})
                with self.subTest(client=client, escaped=json.dumps(value)):
                    self.reject(client, json.dumps(payload).encode())

    def test_unpaired_unicode_keys_are_rejected_at_every_object_depth(self):
        for client in CLIENTS:
            for key in ('\ud800', '\udfff', 'prefix\udc00suffix'):
                payload = self.with_extra(client, {key: MARKER})
                with self.subTest(client=client, escaped=json.dumps(key)):
                    self.reject(client, json.dumps(payload).encode())

    def test_valid_supplementary_unicode_keeps_exact_payload_hash(self):
        for client in CLIENTS:
            payload = self.with_extra(client, {'球⚽😀': ['Київ', '日本', '𐐀']})
            for escaped in (True, False):
                with self.subTest(client=client, escaped=escaped):
                    packet = self.call(client, json.dumps(payload, ensure_ascii=escaped).encode())
                    if client == 'odds_events':
                        self.assertEqual(packet, payload)
                    else:
                        expected = payload['data'] if client == 'gateway' else payload
                        self.assertEqual(packet['data'], expected)
                        self.assertEqual(packet['receipt']['payload_hash'], digest(expected))
                    self.assertEqual(self.server.calls, 1)
                    self.assertTrue(self.response.closed)

    def test_valid_unicode_is_not_normalized_or_replaced(self):
        for client in CLIENTS:
            hashes = []
            for text in ('é', 'e\u0301', '\ufffd'):
                payload = self.with_extra(client, {'text': text})
                with self.subTest(client=client, text=text):
                    packet = self.call(client, json.dumps(payload).encode())
                    if client == 'odds_events':
                        self.assertEqual(packet, payload)
                    else:
                        expected = payload['data'] if client == 'gateway' else payload
                        self.assertEqual(packet['data'], expected)
                        self.assertEqual(packet['receipt']['payload_hash'], digest(expected))
                        hashes.append(packet['receipt']['payload_hash'])
                    self.assertEqual(self.server.calls, 1)
                    self.assertTrue(self.response.closed)
            if client != 'odds_events':
                self.assertEqual(len(set(hashes)), 3)

    def health_patches(self, raw):
        return (
            patch.object(api_health, 'credential_status', return_value={
                'API_FOOTBALL_KEY': 'MISSING_OR_INVALID',
                'SEFIROT_ODDS_API_KEY': 'CONFIGURED', 'STAKE_API_TOKEN': 'MISSING_OR_INVALID'}),
            patch.object(api_health, 'transport_status', return_value={'credential_configured': False}),
            patch.object(api_health, 'sports_catalogue',
                         side_effect=lambda: self.call('odds_catalogue', raw)),
        )

    def test_cli_malformed_odds_rows_report_failure_without_traceback_or_retry(self):
        for row in (None, MARKER, True, 1, [], {'key': None}, {'key': 1}, {'key': []}):
            raw = json.dumps([{'key': 'soccer_owned'}, row]).encode()
            patches = self.health_patches(raw)
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(kind=type(row).__name__), patches[0], patches[1], patches[2], \
                 patch('sefirot.cli.Repository') as repo, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(['api-health'])
                self.assertEqual(code, 2)
                repo.assert_not_called()
                report = json.loads(stdout.getvalue())
                self.assertEqual(report['status'], 'API_CHECK_FAILED')
                self.assertEqual(report['providers']['the_odds_api']['status'], 'REQUEST_FAILED')
                self.assertEqual(report['providers']['the_odds_api']['reason'], 'NETWORK_OR_PROVIDER_RESPONSE')
                self.assertTrue(report['providers']['the_odds_api']['request_attempted'])
                self.assertFalse(report['admission_ready'])
                self.assertFalse(report['monetary_permission'])
                self.assertFalse(report['execution_enabled'])
                self.assertNotIn(MARKER, stdout.getvalue())
                self.assertEqual(stderr.getvalue(), '')
                self.assertEqual(self.server.calls, 1)
                self.assertTrue(self.response.closed)

    def test_health_valid_and_empty_odds_catalogues_keep_existing_scope(self):
        for rows in ([], [{'key': 'soccer_owned', 'title': '球😀'},
                         {'key': 'tennis_owned'}, {}]):
            raw = json.dumps(rows).encode()
            patches = self.health_patches(raw)
            with self.subTest(rows=len(rows)), patches[0], patches[1], patches[2]:
                report = api_health.check()
                row = report['providers']['the_odds_api']
                self.assertEqual(row['status'], 'OK')
                self.assertEqual(row['sports'], len(rows))
                self.assertEqual(row['football_sports'], 1 if rows else 0)
                self.assertEqual(row['receipt']['payload_hash'], digest(rows))
                self.assertFalse(report['admission_ready'])
                self.assertFalse(report['monetary_permission'])
                self.assertEqual(self.server.calls, 1)
                self.assertTrue(self.response.closed)


if __name__ == '__main__':
    unittest.main()
