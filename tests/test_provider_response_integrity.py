"""Real HTTP parser over owned bytes: no provider calls or actual credentials."""
from datetime import datetime, timezone
import http.client
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from sefirot import api_health, football_gateway, football_provider, odds_provider, provider_transport
from sefirot.stake_provider import StakeRequestError, _post_graphql

SECRET = 'OWNED_SYNTHETIC_PRIVATE_MARKER'
CLIENTS = ('football', 'odds_catalogue', 'odds_events', 'gateway', 'stake')


class ProviderResponseIntegrityTests(unittest.TestCase):
    def payload(self, client):
        data = {'errors': [], 'response': {}}
        if client in ('odds_catalogue', 'odds_events'):
            return []
        if client == 'gateway':
            return {'ok': True, 'provider': 'API_FOOTBALL_V3',
                'provider_host': football_provider.HOST, 'endpoint': '/status', 'params': {},
                'sports_only': True, 'monetary_permission': False, 'execution_enabled': False,
                'received_at': '2030-01-01T09:00:00+00:00', 'data': data}
        if client == 'stake':
            return {'data': {'fixture': {}}}
        return data

    def wire(self, client, framing):
        body = json.dumps(self.payload(client)).encode()
        headers = b''
        if framing == 'fixed':
            headers = b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
        elif framing == 'short':
            headers = b'Content-Length: ' + str(len(body) + 100).encode() + b'\r\n'
        elif framing == 'invalid':
            headers = b'Content-Length: invalid\r\n'
        elif framing == 'duplicate':
            headers = b'Content-Length: ' + str(len(body)).encode() + b'\r\nContent-Length: 9999\r\n'
        elif framing in ('chunked', 'conflict', 'broken_chunked'):
            headers = b'Transfer-Encoding: chunked\r\n'
            if framing == 'conflict':
                headers += b'Content-Length: ' + str(len(body)).encode() + b'\r\n'
            body = hex(len(body))[2:].encode() + b'\r\n' + body + b'\r\n'
            body += b'5\r\nxx' if framing == 'broken_chunked' else b'0\r\n\r\n'
        return b'HTTP/1.1 200 OK\r\n' + headers + b'\r\n' + body

    def call(self, client, *, framing='fixed', protocol_error=False, close_error=False):
        raw = self.wire(client, framing)
        owner = self
        self.requests = self.closed = 0

        class Socket:
            def makefile(self, *args):
                return io.BytesIO(raw)

        class Reply:
            def __init__(self):
                if protocol_error:
                    raise http.client.BadStatusLine(SECRET)
                self.inner = http.client.HTTPResponse(Socket())
                self.inner.begin()
                self.status, self.headers = self.inner.status, self.inner.headers
            def getheader(self, key):
                return self.inner.getheader(key)
            def read(self, size):
                return self.inner.read(size)
            def close(self):
                owner.closed += 1
                self.inner.close()
                if close_error:
                    raise OSError(SECRET)

        class Connection:
            def __init__(self, *args, **kwargs):
                self.response = None
            def request(self, *args, **kwargs):
                owner.requests += 1
            def getresponse(self):
                self.response = Reply()
                return self.response
            def close(self):
                if self.response is not None:
                    self.response.close()
                else:
                    owner.closed += 1

        class Opener:
            def open(self, *args, **kwargs):
                owner.requests += 1
                return Reply()

        if client == 'football':
            return football_provider.get('status', api_key=SECRET, connection_factory=Connection)
        if client == 'odds_catalogue':
            return odds_provider.sports_catalogue(api_key=SECRET, connection_factory=Connection)
        if client == 'odds_events':
            return odds_provider.events('soccer_test', api_key=SECRET, connection_factory=Connection)
        if client == 'stake':
            return _post_graphql('query Owned { fixture { id } }', {}, token=SECRET,
                opener=Opener(), operation_name='Owned')
        with patch.dict('os.environ', {'SEFIROT_SPORTS_GATEWAY_URL':
                'https://abcdefghijklmnopqrst.supabase.co/functions/v1/sefirot-sports-gateway'}), \
             patch.object(football_gateway, 'credential', return_value=SECRET):
            return football_gateway.get_sports('status', opener=Opener().open,
                clock=lambda: datetime(2030, 1, 1, 9, tzinfo=timezone.utc))

    def assert_refused(self, client, **kwargs):
        with self.assertRaises(ValueError) as caught:
            self.call(client, **kwargs)
        self.assertNotIn(SECRET, str(caught.exception))
        if client == 'stake':
            self.assertIsInstance(caught.exception, StakeRequestError)
            self.assertEqual(caught.exception.code, 'NETWORK_ERROR')
        self.assertEqual(self.requests, 1)  # Never retry or spend another request.
        if not kwargs.get('protocol_error'):
            self.assertEqual(self.closed, 1)

    def test_chunked_disconnect_is_a_sanitized_provider_failure(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                self.assert_refused(client, framing='broken_chunked')

    def test_short_content_length_cannot_issue_a_success_receipt(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                self.assert_refused(client, framing='short')

    def test_invalid_content_length_is_refused(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                self.assert_refused(client, framing='invalid')

    def test_conflicting_content_lengths_are_refused(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                self.assert_refused(client, framing='duplicate')

    def test_chunked_and_content_length_conflict_is_refused(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                self.assert_refused(client, framing='conflict')

    def test_bad_status_line_never_exposes_upstream_text(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                self.assert_refused(client, protocol_error=True)

    def test_complete_fixed_chunked_and_close_delimited_responses_still_work(self):
        for client in CLIENTS:
            for framing in ('fixed', 'chunked', 'close_delimited'):
                with self.subTest(client=client, framing=framing):
                    result = self.call(client, framing=framing)
                    self.assertEqual(self.requests, 1)
                    self.assertEqual(self.closed, 1)
                    self.assertNotIn(SECRET, json.dumps(result))
                    if client != 'odds_events':
                        self.assertEqual(result['receipt']['http_status'], 200)

    def test_cleanup_failure_cannot_expose_private_text_or_mask_primary_refusal(self):
        for client in CLIENTS:
            with self.subTest(client=client):
                self.assert_refused(client, framing='short', close_error=True)

    def test_health_check_reports_failure_instead_of_crashing_on_disconnect(self):
        credentials = {'API_FOOTBALL_KEY': 'CONFIGURED', 'SEFIROT_ODDS_API_KEY': 'CONFIGURED',
                       'STAKE_API_TOKEN': 'CONFIGURED'}
        transport = {'transport': 'DIRECT', 'credential_configured': True,
                     'credential_name': 'API_FOOTBALL_KEY'}
        with patch.object(api_health, 'credential_status', return_value=credentials), \
             patch.object(api_health, 'transport_status', return_value=transport), \
             patch.object(api_health, 'get', side_effect=lambda *a: self.call('football', framing='broken_chunked')), \
             patch.object(api_health, 'sports_catalogue', side_effect=lambda: self.call('odds_catalogue', framing='broken_chunked')):
            report = api_health.check()
        self.assertEqual(report['status'], 'API_CHECK_FAILED')
        self.assertTrue(all(row['status'] == 'REQUEST_FAILED' for row in report['providers'].values()))
        self.assertFalse(report['admission_ready'])
        self.assertFalse(report['monetary_permission'])
        self.assertFalse(report['execution_enabled'])
        self.assertNotIn(SECRET, json.dumps(report))

    def test_default_connection_sanitizes_http_parser_failures(self):
        with patch.object(provider_transport, 'build_opener') as opener:
            opener.return_value.open.side_effect = http.client.BadStatusLine(SECRET)
            with self.assertRaises(ValueError) as caught:
                provider_transport.request_json(football_provider.HOST, '/status', {}, {})
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertEqual(opener.return_value.open.call_count, 1)


if __name__ == '__main__':
    unittest.main()
