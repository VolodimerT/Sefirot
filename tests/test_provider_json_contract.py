"""Owned loopback HTTP responses only; no provider or genuine credentials."""
from datetime import datetime, timezone
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot import football_gateway, football_provider, odds_provider, stake_provider
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


if __name__ == '__main__':
    unittest.main()
