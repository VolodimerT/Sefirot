"""Offline API diagnosis must distinguish presence, access and admission."""
from contextlib import ExitStack, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot import api_health
from sefirot.cli import main
from sefirot.football_provider import FootballRequestError
from sefirot.stake_provider import StakeRequestError, _post_graphql


class Reply:
    def __init__(self, raw, status=200):
        self.raw, self.status, self.closed = raw, status, False
    def read(self, limit):
        return self.raw[:limit]
    def close(self):
        self.closed = True


class Opener:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.requests = reply, error, []
    def open(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.reply


class ApiHealthTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.credentials = {name: 'CONFIGURED' for name in
                            ('API_FOOTBALL_KEY', 'SEFIROT_ODDS_API_KEY', 'STAKE_API_TOKEN')}
        self.transport = {'transport': 'DIRECT', 'credential_configured': True,
                          'credential_name': 'API_FOOTBALL_KEY'}
        self.stack.enter_context(patch.object(api_health, 'credential_status', return_value=self.credentials))
        self.stack.enter_context(patch.object(api_health, 'transport_status', return_value=self.transport))
        self.football = self.stack.enter_context(patch.object(api_health, 'get', return_value={
            'data': {'response': {'subscription': {'active': True, 'plan': 'Fixture'},
                                 'requests': {'current': 1, 'limit_day': 100}}},
            'receipt': {'provider': 'API_FOOTBALL_V3'}}))
        self.odds = self.stack.enter_context(patch.object(api_health, 'sports_catalogue', return_value={
            'data': [{'key': 'soccer_test'}, {'key': 'tennis_test'}], 'receipt': {}}))
        self.stake = self.stack.enter_context(patch('sefirot.stake_provider.sports_events', return_value={
            'events': [], 'receipt': {'provider': 'STAKE_GRAPHQL_EXPERIMENTAL'}}))

    def test_default_odds_catalogue_compatibility_without_stake_request(self):
        report = api_health.check()
        self.assertEqual(report['status'], 'API_READY')
        self.assertEqual(report['providers']['the_odds_api']['football_sports'], 1)
        self.football.assert_called_once_with('status')
        self.odds.assert_called_once_with(); self.stake.assert_not_called()
        self.assertFalse(report['admission_ready']); self.assertFalse(report['monetary_permission'])

    def test_selected_stake_checks_catalogue_only_and_never_grants_admission(self):
        self.credentials['SEFIROT_ODDS_API_KEY'] = 'MISSING_OR_INVALID'
        report = api_health.check(odds_provider='stake')
        self.assertEqual(report['status'], 'RESEARCH_API_READY')
        self.assertEqual(set(report['providers']), {'api_football', 'stake'})
        self.stake.assert_called_once_with(first=5, sport_slug='soccer', match_type='upcoming')
        self.odds.assert_not_called()
        stake = report['providers']['stake']
        self.assertEqual(stake['events'], 0)  # Empty catalogue is access, not a forecast.
        self.assertEqual(stake['scope'], 'EVENT_CATALOGUE_ONLY')
        self.assertEqual(stake['market_access'], 'NOT_CHECKED')
        self.assertEqual(stake['settlement'], 'UNVERIFIED')
        self.assertEqual(stake['freshness'], 'RECEIPT_TIME_ONLY')
        for value in (report, stake):
            self.assertFalse(value['monetary_permission']); self.assertFalse(value['execution_enabled'])
        self.assertFalse(report['admission_ready'])

    def test_configured_token_with_403_is_failed_access_not_missing_credential(self):
        self.stake.side_effect = StakeRequestError('HTTP_ERROR', http_status=403)
        report = api_health.check(odds_provider='stake')
        self.assertEqual(report['status'], 'API_CHECK_FAILED')
        self.assertEqual(report['credentials']['STAKE_API_TOKEN'], 'CONFIGURED')
        row = report['providers']['stake']
        self.assertEqual(row['status'], 'REQUEST_FAILED')
        self.assertEqual(row['reason'], 'HTTP_ACCESS_DENIED'); self.assertEqual(row['http_status'], 403)
        self.assertTrue(row['request_attempted'])

    def test_auth_quota_and_network_reasons_are_distinct(self):
        for error, reason, status in (
            (StakeRequestError('HTTP_ERROR', http_status=401), 'HTTP_AUTH_REJECTED', 401),
            (StakeRequestError('HTTP_ERROR', http_status=429), 'HTTP_RATE_LIMITED', 429),
            (StakeRequestError('NETWORK_ERROR'), 'NETWORK_ERROR', None),
            (StakeRequestError('GRAPHQL_ERROR'), 'GRAPHQL_ERROR', None),
        ):
            with self.subTest(reason=reason):
                self.stake.side_effect = error
                row = api_health.check(odds_provider='stake')['providers']['stake']
                self.assertEqual((row['reason'], row['http_status']), (reason, status))

    def test_missing_credentials_do_not_issue_requests(self):
        self.transport['credential_configured'] = False
        self.credentials.update({name: 'MISSING_OR_INVALID' for name in self.credentials})
        for provider, key in (('stake', 'stake'), ('the-odds-api', 'the_odds_api')):
            with self.subTest(provider=provider):
                report = api_health.check(odds_provider=provider)
                for name in ('api_football', key):
                    self.assertEqual(report['providers'][name]['status'], 'CREDENTIAL_UNAVAILABLE')
                    self.assertFalse(report['providers'][name]['request_attempted'])
        self.football.assert_not_called(); self.odds.assert_not_called(); self.stake.assert_not_called()

    def test_gateway_credential_can_work_without_local_football_key(self):
        self.credentials['API_FOOTBALL_KEY'] = 'MISSING_OR_INVALID'
        self.transport.update(transport='SUPABASE_GATEWAY', credential_name='SEFIROT_SPORTS_GATEWAY_TOKEN')
        self.assertEqual(api_health.check()['status'], 'API_READY')
        self.football.assert_called_once_with('status')

    def test_subscription_inactive_is_not_ready_even_when_catalogue_works(self):
        self.football.return_value['data']['response']['subscription']['active'] = False
        report = api_health.check(odds_provider='stake')
        self.assertEqual(report['status'], 'API_CHECK_FAILED')
        self.assertEqual(report['providers']['api_football']['status'], 'SUBSCRIPTION_INACTIVE')

    def test_football_provider_rejection_is_sanitized_and_classified(self):
        self.football.side_effect = FootballRequestError({'requests': 'PRIVATE_ACCOUNT_VALUE'})
        report = api_health.check()
        self.assertEqual(report['providers']['api_football']['reason'], 'PROVIDER_QUOTA_EXHAUSTED')
        self.assertNotIn('PRIVATE_ACCOUNT_VALUE', json.dumps(report))

    def test_fixed_http_codes_survive_without_echoing_arbitrary_errors(self):
        self.football.side_effect = ValueError('provider HTTP 401')
        self.odds.side_effect = ValueError('odds provider HTTP 429; PASS')
        report = api_health.check()
        self.assertEqual(report['providers']['api_football']['http_status'], 401)
        self.assertEqual(report['providers']['the_odds_api']['http_status'], 429)
        self.stake.side_effect = ValueError('PRIVATE_TOKEN accountId balance')
        report = api_health.check(odds_provider='stake')
        self.assertNotIn('PRIVATE_TOKEN', json.dumps(report))
        self.assertEqual(report['providers']['stake']['reason'], 'NETWORK_OR_PROVIDER_RESPONSE')

    def test_invalid_provider_does_not_start_network_checks(self):
        with self.assertRaises(ValueError): api_health.check(odds_provider='unsupported')
        self.football.assert_not_called(); self.odds.assert_not_called(); self.stake.assert_not_called()

    def test_cli_research_ready_exit_zero_saves_report_without_database(self):
        with tempfile.TemporaryDirectory() as folder, patch('sefirot.cli.Repository') as repo:
            output = Path(folder) / 'health.json'
            with redirect_stdout(io.StringIO()):
                code = main(['--db', str(Path(folder) / 'unused.sqlite'), 'api-health',
                             '--odds-provider', 'stake', '--output', str(output)])
            self.assertEqual(code, 0); repo.assert_not_called()
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'RESEARCH_API_READY')
            self.assertFalse(report['admission_ready'])
            self.assertFalse((Path(folder) / 'unused.sqlite').exists())

    def test_cli_access_failure_exits_two(self):
        self.stake.side_effect = StakeRequestError('HTTP_ERROR', http_status=403)
        with redirect_stdout(io.StringIO()):
            code = main(['api-health', '--odds-provider', 'stake'])
        self.assertEqual(code, 2)


class StakeTransportDiagnosisTests(unittest.TestCase):
    def call(self, opener):
        return _post_graphql('query Catalogue { data }', {}, token='PRIVATE_TOKEN',
                             opener=opener, operation_name='Catalogue')

    def test_http_error_body_is_never_read_or_exposed_even_under_old_debug_flag(self):
        body = io.BytesIO(b'{"errors":[{"message":"PRIVATE_TOKEN PRIVATE_ACCOUNT_VALUE"}]}')
        error = HTTPError('https://stake.com/?PRIVATE_TOKEN', 403, 'PRIVATE_ACCOUNT_VALUE', {}, body)
        with patch.dict(os.environ, {'SEFIROT_STAKE_DEBUG_ERRORS': '1'}):
            with self.assertRaises(StakeRequestError) as caught:
                self.call(Opener(error=error))
        self.assertEqual(caught.exception.http_status, 403)
        self.assertEqual(str(caught.exception), 'stake provider HTTP 403; PASS')
        self.assertTrue(body.closed)

    def test_non_200_response_is_closed_and_classified(self):
        reply = Reply(b'PRIVATE_ACCOUNT_VALUE', status=429)
        with self.assertRaises(StakeRequestError) as caught: self.call(Opener(reply))
        self.assertEqual(caught.exception.http_status, 429); self.assertTrue(reply.closed)

    def test_graphql_error_messages_are_never_exposed(self):
        reply = Reply(json.dumps({'errors': [{'message': 'PRIVATE_TOKEN PRIVATE_ACCOUNT_VALUE'}]}).encode())
        with patch.dict(os.environ, {'SEFIROT_STAKE_DEBUG_ERRORS': '1'}):
            with self.assertRaises(StakeRequestError) as caught: self.call(Opener(reply))
        self.assertEqual(caught.exception.code, 'GRAPHQL_ERROR')
        self.assertNotIn('PRIVATE_', str(caught.exception)); self.assertTrue(reply.closed)

    def test_network_invalid_json_and_invalid_response_are_sanitized(self):
        for opener, code in (
            (Opener(error=URLError('PRIVATE_TOKEN')), 'NETWORK_ERROR'),
            (Opener(Reply(b'PRIVATE_TOKEN')), 'INVALID_JSON'),
            (Opener(Reply(b'[]')), 'INVALID_RESPONSE'),
        ):
            with self.subTest(code=code):
                with self.assertRaises(StakeRequestError) as caught: self.call(opener)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('PRIVATE_TOKEN', str(caught.exception))

    def test_oversized_response_fails_closed(self):
        with patch('sefirot.stake_provider.MAX_RESPONSE', 10):
            with self.assertRaises(StakeRequestError) as caught: self.call(Opener(Reply(b'x' * 11)))
        self.assertEqual(caught.exception.code, 'RESPONSE_TOO_LARGE')

    def test_catalogue_health_uses_one_bounded_query_no_identity_or_prices(self):
        reply = Reply(b'{"data":{"slugSport":{"tournamentList":[]}}}')
        opener = Opener(reply)
        credentials = {name: 'CONFIGURED' for name in api_health.credential_status()}
        with patch.object(api_health, 'credential_status', return_value=credentials), \
             patch.object(api_health, 'transport_status', return_value={'credential_configured': False}), \
             patch('sefirot.stake_provider.credential', return_value='PRIVATE_TOKEN'), \
             patch('sefirot.stake_provider.build_opener', return_value=opener):
            report = api_health.check(odds_provider='stake')
        self.assertEqual(len(opener.requests), 1)
        body = json.loads(opener.requests[0].data)
        self.assertEqual(body['operationName'], 'SportTournamentFixtureList')
        self.assertEqual(body['variables']['type'], 'upcoming')
        self.assertLessEqual(body['variables']['tournamentLimit'] * body['variables']['fixtureCountLimit'], 100)
        for forbidden in ('UserIdentity', 'slugFixture', 'outcomes', 'odds'):
            self.assertNotIn(forbidden, body['query'])
        self.assertNotIn('PRIVATE_TOKEN', json.dumps(report))
        self.assertEqual(report['providers']['stake']['status'], 'OK')

    def test_cold_import_ignores_old_boot_probe_flag_and_performs_no_io(self):
        script = '''from unittest.mock import patch
with patch('urllib.request.build_opener') as opener:
    import sefirot.stake_provider
    opener.assert_not_called()
print('IMPORT_OK')
'''
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'),
                   SEFIROT_STAKE_BOOT_PROBE='1', STAKE_API_TOKEN='PRIVATE_TOKEN')
        result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True,
                                text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'IMPORT_OK')


if __name__ == '__main__':
    unittest.main()
