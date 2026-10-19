"""Owned HTTP and synthetic archived packets; no account or provider access."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from sefirot import api_health, football_provider
from sefirot.cli import main
from sefirot.contracts import digest
from test_operations_upgrade import packet, row
from test_odds_provider import fixture as odds_fixture
from sefirot.odds_provider import quotes_from_event

MARKER = 'OWNED_PRIVATE_FOOTBALL_MARKER'


class FootballResponseContractTests(unittest.TestCase):
    def setUp(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.calls += 1
                raw = self.server.payload
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

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

    def status(self, response):
        self.server.payload = json.dumps({'errors': [], 'response': response}).encode()
        self.server.calls = 0
        owner = self

        class Connection(http.client.HTTPConnection):
            def __init__(inner, *args, **kwargs):
                super().__init__('127.0.0.1', owner.server.server_port, timeout=5)
                inner.owned_response = None
                owner.addCleanup(inner.close)

            def getresponse(inner):
                owner.response = inner.owned_response = super().getresponse()
                return inner.owned_response

            def close(inner):
                if inner.owned_response is not None:
                    inner.owned_response.close()
                super().close()

        return football_provider.get('status', api_key=MARKER, connection_factory=Connection)

    def target(self):
        return packet([row(100, status='NS', hours=3, score=(None, None))])

    def sealed(self, value):
        value['receipt']['payload_hash'] = digest(value['data'])
        return value

    def normalize(self, target=None, history=None):
        return football_provider.normalize_sports(target if target is not None else self.target(),
            100, history or [], profile='LOWER', source_reliability=.95)

    def assert_fixed_refusal(self, function):
        with self.assertRaises(ValueError) as caught:
            function()
        self.assertNotIn(MARKER, str(caught.exception))

    def test_status_containers_refuse_with_safe_errors_and_closed_single_request(self):
        for field in ('subscription', 'requests'):
            for value in (None, [], MARKER, True, 1):
                response = {'subscription': {'active': True}, 'requests': {'current': 1, 'limit_day': 100}}
                response[field] = value
                with self.subTest(field=field, kind=type(value).__name__):
                    self.assert_fixed_refusal(lambda: football_provider.status_summary(self.status(response)))
                    self.assertEqual(self.server.calls, 1)
                    self.assertTrue(self.response.closed)

    def test_status_scalar_fields_cannot_echo_objects_or_coerce_quota_and_activity(self):
        cases = [('subscription', 'active', 1), ('subscription', 'active', 'true'),
                 ('subscription', 'plan', {'private': MARKER}), ('subscription', 'plan', [MARKER]),
                 ('requests', 'current', True), ('requests', 'current', -1),
                 ('requests', 'current', '1'), ('requests', 'limit_day', False),
                 ('requests', 'limit_day', -1), ('requests', 'limit_day', {'private': MARKER})]
        for group, field, value in cases:
            response = {'subscription': {'active': True, 'plan': 'Synthetic'},
                        'requests': {'current': 1, 'limit_day': 100}}
            response[group][field] = value
            with self.subTest(group=group, field=field, kind=type(value).__name__):
                self.assert_fixed_refusal(lambda: football_provider.status_summary(self.status(response)))
                self.assertEqual(self.server.calls, 1)
                self.assertTrue(self.response.closed)

    def test_status_missing_fields_stay_unknown_and_valid_zero_false_are_preserved(self):
        for response in ({}, {'subscription': {}, 'requests': {}},
                         {'subscription': {'active': False, 'plan': '球😀'},
                          'requests': {'current': 0, 'limit_day': 0}},
                         {'subscription': {'active': None, 'plan': None},
                          'requests': {'current': None, 'limit_day': None}}):
            with self.subTest(response=response):
                result = football_provider.status_summary(self.status(response))
                self.assertEqual(result['subscription_active'], response.get('subscription', {}).get('active'))
                self.assertEqual(result['plan'], response.get('subscription', {}).get('plan'))
                self.assertEqual(result['requests_current'], response.get('requests', {}).get('current'))
                self.assertEqual(result['requests_limit_day'], response.get('requests', {}).get('limit_day'))
                self.assertEqual(result['receipt']['payload_hash'], digest({'errors': [], 'response': response}))
                self.assertEqual(self.server.calls, 1)
                self.assertTrue(self.response.closed)

    def test_health_cli_rejects_bad_status_without_traceback_database_or_private_echo(self):
        for response in ({'subscription': None}, {'requests': [MARKER]},
                         {'subscription': {'active': True, 'plan': {'private': MARKER}}}):
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(response=response), \
                 patch.object(api_health, 'credential_status', return_value={
                     'API_FOOTBALL_KEY': 'CONFIGURED', 'SEFIROT_ODDS_API_KEY': 'MISSING_OR_INVALID',
                     'STAKE_API_TOKEN': 'MISSING_OR_INVALID'}), \
                 patch.object(api_health, 'transport_status', return_value={'credential_configured': True}), \
                 patch.object(api_health, 'get', side_effect=lambda *a: self.status(response)), \
                 patch('sefirot.cli.Repository') as repo, redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(['api-health']), 2)
                repo.assert_not_called()
                report = json.loads(stdout.getvalue())
                self.assertEqual(report['providers']['api_football']['status'], 'REQUEST_FAILED')
                self.assertFalse(report['admission_ready'])
                self.assertFalse(report['monetary_permission'])
                self.assertFalse(report['execution_enabled'])
                self.assertNotIn(MARKER, stdout.getvalue())
                self.assertEqual(stderr.getvalue(), '')
                self.assertEqual(self.server.calls, 1)
                self.assertTrue(self.response.closed)

    def test_archive_rows_and_paging_are_validated_before_fixture_selection(self):
        for value in (None, MARKER, [], 1):
            for location in ('row', 'fixture', 'paging', 'data'):
                source = self.target()
                if location == 'row':
                    source['data']['response'] = [value]
                elif location == 'fixture':
                    source['data']['response'][0]['fixture'] = value
                elif location == 'paging':
                    source['data']['paging'] = value
                else:
                    source['data'] = value
                before = deepcopy(source)
                with self.subTest(location=location, kind=type(value).__name__):
                    self.assert_fixed_refusal(lambda: self.normalize(self.sealed(source)))
                    before['receipt']['payload_hash'] = digest(before['data'])
                    self.assertEqual(source, before)

    def test_direct_prematch_container_validation_never_raises_attribute_error(self):
        for value in (None, MARKER, [], 1):
            for payload in (value, {'fixture': value}):
                with self.subTest(kind=type(payload).__name__):
                    self.assert_fixed_refusal(lambda: football_provider.validate_prematch_state(payload))

    def test_null_or_wrong_history_score_containers_do_not_crash_or_invent_goals(self):
        for value in (None, MARKER, [], 1):
            for location in ('score', 'fulltime', 'status'):
                history = packet([row(10)], -24)
                first = history['data']['response'][0]
                if location == 'score':
                    first['score'] = value
                elif location == 'fulltime':
                    first['score']['fulltime'] = value
                else:
                    first['fixture']['status'] = value
                before = deepcopy(self.sealed(history))
                with self.subTest(location=location, kind=type(value).__name__):
                    self.assert_fixed_refusal(lambda: self.normalize(history=[history]))
                    self.assertEqual(history, before)

    def test_normalize_cli_refuses_bad_rows_without_writing_output_or_opening_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'source.json', Path(folder) / 'sports.json'
            payload = self.target()
            payload['data']['response'] = [None]
            source.write_text(json.dumps(self.sealed(payload)))
            original = source.read_bytes()
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch('sefirot.cli.Repository') as repo, redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(main(['football-normalize', str(source), '--fixture-id', '100',
                    '--profile', 'LOWER', '--source-reliability', '.95', '--output', str(output)]), 2)
                repo.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(folder).iterdir()), [source])
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(json.loads(stderr.getvalue())['decision'], 'PASS')
            self.assertNotIn(MARKER, stderr.getvalue())

    def test_valid_sports_normalization_and_existing_odds_refusals_remain_intact(self):
        source, history = self.target(), packet([row(10)], -24)
        before = deepcopy((source, history))
        result = self.normalize(source, [history])
        self.assertEqual(len(result['sports']['history']), 1)
        self.assertFalse(result['receipt']['monetary_permission'])
        self.assertEqual((source, history), before)
        prediction, event, received = odds_fixture()
        for location in ('bookmakers', 'markets'):
            bad = deepcopy(event)
            if location == 'bookmakers':
                bad[location] = None
            else:
                bad['bookmakers'][0][location] = None
            with self.subTest(location=location), self.assertRaises((ValueError, TypeError)):
                quotes_from_event(bad, prediction, 'soccer_epl', 'event1234', 'testbook',
                                 received, rules_confirmed=True)


if __name__ == '__main__':
    unittest.main()
