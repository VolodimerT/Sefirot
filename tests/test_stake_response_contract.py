"""Actual owned loopback HTTP bytes; no Stake, credential or account access."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot import stake_provider
from sefirot.cli import main
from sefirot.contracts import digest

MARKER = 'SYNTHETIC_PRIVATE_MARKER'


class StakeResponseContractTests(unittest.TestCase):
    def setUp(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                raw = self.server.payload
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.payload = b'{}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def opener(self, raw):
        self.server.payload = raw
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        self.addCleanup(connection.close)

        class OwnedOpener:
            calls = 0
            response = None

            def open(inner, request, timeout):
                inner.calls += 1
                connection.request('POST', '/owned-stake', body=request.data,
                                   headers={'Content-Type': 'application/json'})
                inner.response = connection.getresponse()
                return inner.response

        return OwnedOpener()

    def call(self, opener, *, catalogue=False):
        if catalogue:
            return stake_provider.sports_events(first=5, token='OWNED_TEST_TOKEN', opener=opener)
        return stake_provider._post_graphql('query Synthetic { id }', {},
            token='OWNED_TEST_TOKEN', opener=opener, operation_name='Synthetic')

    def rejected(self, raw, code, *, catalogue=False):
        opener = self.opener(raw)
        with self.assertRaises(stake_provider.StakeRequestError) as caught:
            self.call(opener, catalogue=catalogue)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(MARKER, str(caught.exception))
        self.assertEqual(opener.calls, 1)
        self.assertTrue(opener.response.closed)

    def catalogue(self):
        return {'data': {'slugSport': {'tournamentList': [{'fixtureList': [{
            'id': 'synthetic-fixture', 'slug': 'synthetic-slug',
            'data': {'competitors': [{'name': 'A'}, {'name': 'B'}]}}]}]}}}

    def test_duplicate_members_never_receive_a_canonical_receipt(self):
        for raw in (
            b'{"data":{},"data":{"private":"SYNTHETIC_PRIVATE_MARKER"}}',
            b'{"data":{"id":"a","id":"b"}}',
            b'{"data":{},"\\u0064ata":{}}',
        ):
            with self.subTest(raw=raw):
                self.rejected(raw, 'INVALID_JSON')

    def test_nonfinite_constants_and_overflow_are_fixed_json_failures(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e999'):
            with self.subTest(value=value):
                self.rejected(('{"data":{"value":' + value + '}}').encode(), 'INVALID_JSON')

    def test_excessive_nesting_is_rejected_before_receipt_hashing(self):
        for depth in (65, 1200):
            with self.subTest(depth=depth):
                self.rejected(b'{"x":' * (depth - 1) + b'{"leaf":0}' + b'}' * (depth - 1),
                              'INVALID_JSON')

    def test_bounded_json_and_string_braces_keep_the_original_payload_hash(self):
        for raw in (b'{"x":' * 63 + b'{"leaf":0}' + b'}' * 63,
                    json.dumps({'data': {'text': '{["' * 1000}}).encode()):
            with self.subTest(size=len(raw)):
                opener = self.opener(raw)
                packet = self.call(opener)
                self.assertEqual(packet['data'], json.loads(raw))
                self.assertEqual(packet['receipt']['payload_hash'], digest(json.loads(raw)))
                self.assertEqual(packet['receipt']['provider'], 'STAKE_GRAPHQL_EXPERIMENTAL')
                self.assertFalse(packet['receipt']['monetary_permission'])
                self.assertEqual(opener.calls, 1)
                self.assertTrue(opener.response.closed)

    def test_malformed_fixture_data_is_not_an_unhandled_attribute_error(self):
        for value in ([MARKER], MARKER, True, 1):
            payload = self.catalogue()
            payload['data']['slugSport']['tournamentList'][0]['fixtureList'][0]['data'] = value
            with self.subTest(kind=type(value).__name__):
                self.rejected(json.dumps(payload).encode(), 'INVALID_RESPONSE', catalogue=True)

    def test_malformed_containers_are_not_a_successful_empty_catalogue(self):
        for location in ('tournament', 'fixture', 'fixture_list', 'competitors'):
            payload = self.catalogue()
            tournaments = payload['data']['slugSport']['tournamentList']
            if location == 'tournament':
                tournaments[0] = MARKER
            elif location == 'fixture':
                tournaments[0]['fixtureList'][0] = MARKER
            elif location == 'fixture_list':
                tournaments[0]['fixtureList'] = False
            else:
                tournaments[0]['fixtureList'][0]['data']['competitors'] = {'a': 1, 'b': 2}
            with self.subTest(location=location):
                self.rejected(json.dumps(payload).encode(), 'INVALID_RESPONSE', catalogue=True)

    def test_nullable_data_and_outrights_are_not_promoted_to_match_fixtures(self):
        payload = self.catalogue()
        fixtures = payload['data']['slugSport']['tournamentList'][0]['fixtureList']
        fixtures.extend([{'data': None}, {'data': {'__typename': 'SportFixtureDataOutright'}}])
        opener = self.opener(json.dumps(payload).encode())
        packet = self.call(opener, catalogue=True)
        self.assertEqual([r['id'] for r in packet['events']], ['synthetic-fixture'])
        self.assertEqual(opener.calls, 1)
        self.assertTrue(opener.response.closed)

    def test_cli_health_reports_failure_without_traceback_retry_or_private_text(self):
        malformed = self.catalogue()
        malformed['data']['slugSport']['tournamentList'][0]['fixtureList'][0]['data'] = [MARKER]
        duplicate = b'{"data":{"slugSport":{"tournamentList":[]}},"data":{"slugSport":{"tournamentList":[]}}}'
        for raw, code in ((json.dumps(malformed).encode(), 'INVALID_RESPONSE'),
                          (duplicate, 'INVALID_JSON')):
            opener = self.opener(raw)
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(code=code), ExitStack() as stack:
                stack.enter_context(patch('sefirot.api_health.credential_status',
                    return_value={'STAKE_API_TOKEN': 'CONFIGURED'}))
                stack.enter_context(patch('sefirot.api_health.transport_status',
                    return_value={'credential_configured': False}))
                credential = stack.enter_context(patch.object(stake_provider, 'credential',
                    return_value='OWNED_TEST_TOKEN'))
                stack.enter_context(patch.object(stake_provider, 'build_opener', return_value=opener))
                repo = stack.enter_context(patch('sefirot.cli.Repository'))
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = main(['api-health', '--odds-provider', 'stake'])
                self.assertEqual(result, 2)
                repo.assert_not_called()
                credential.assert_called_once_with('STAKE_API_TOKEN')
                report = json.loads(stdout.getvalue())
                row = report['providers']['stake']
                self.assertEqual((row['status'], row['reason']), ('REQUEST_FAILED', code))
                self.assertTrue(row['request_attempted'])
                self.assertEqual(row['market_access'], 'NOT_CHECKED')
                self.assertFalse(report['monetary_permission'])
                self.assertFalse(report['admission_ready'])
                self.assertEqual(stderr.getvalue(), '')
                self.assertNotIn(MARKER, stdout.getvalue())
                self.assertNotIn('OWNED_TEST_TOKEN', stdout.getvalue())
                self.assertEqual(opener.calls, 1)
                self.assertTrue(opener.response.closed)


if __name__ == '__main__':
    unittest.main()
