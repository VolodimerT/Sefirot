"""Regression tests for explicit bounded sports-only fetch executor (offline mocks)."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from scripts.football_enrichment_collect import collect_one, main
from sefirot.contracts import digest
from sefirot.football_gateway import get_sports


DEFAULT_QUOTA = {'x-ratelimit-requests-remaining': '90', 'x-ratelimit-requests-limit': '100',
                 'x-ratelimit-remaining': '20', 'x-ratelimit-limit': '300'}


def packet(endpoint, params, response, stamp, count=None, quota=None):
    data = {'errors': [], 'response': response,
            'results': count if count is not None else (len(response) if isinstance(response, list) else 1),
            'paging': {'current': 1, 'total': 1}}
    return {'data': data, 'receipt': {'provider': 'API_FOOTBALL_V3',
            'provider_host': 'v3.football.api-sports.io',
            'endpoint': '/' + endpoint, 'parameters': params,
            'http_status': 200, 'sports_only': True,
            'received_at': stamp.isoformat(), 'payload_hash': digest(data),
            'quota': {**DEFAULT_QUOTA, **(quota or {})}}}


class OneFixtureCollectorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.t = self.now - timedelta(seconds=30)
        self.fixture = {'fixture': {
            'id': 50001, 'date': (self.now + timedelta(hours=2)).isoformat(),
            'status': {'short': 'NS'}},
            'league': {'id': 39, 'season': 2026},
            'teams': {'home': {'id': 101, 'name': 'Alpha'},
                      'away': {'id': 202, 'name': 'Beta'}}}
        self.coverage = {'standings': True, 'injuries': True,
                         'fixtures': {'statistics_fixtures': True, 'lineups': True}}
        self.calls = []
        self.used = 10
        self.fail_on = None
        self.stop_after_one = False
        self.tamper = False
        self.quota_by_call = {}

    def getter(self, endpoint, params=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if endpoint == self.fail_on:
            raise ValueError('PRIVATE_URL_OR_SECRET')
        if endpoint == 'status':
            response = {'account': {'email': 'PRIVATE_ACCOUNT_VALUE'},
                        'subscription': {'active': True},
                        'requests': {'current': self.used, 'limit_day': 100}}
        elif endpoint == 'fixtures':
            response = [self.fixture]
        elif endpoint == 'leagues':
            response = [{'league': {'id': 39},
                         'seasons': [{'year': 2026, 'coverage': self.coverage}]}]
        elif endpoint == 'teams/statistics':
            response = {'team': {'id': params['team']}, 'form': 'WWD'}
        else:
            response = []
        kwargs = {}
        if self.stop_after_one and len(self.calls) == 4:
            kwargs['quota'] = {'x-ratelimit-remaining': '0'}
        out = packet(endpoint, params, response, self.t, **kwargs)
        if len(self.calls) in self.quota_by_call:
            out['receipt']['quota'] = self.quota_by_call[len(self.calls)]
        if self.tamper and len(self.calls) == 4:
            out['receipt']['payload_hash'] = 'f' * 64
        return out

    def run_one(self, **kwargs):
        return collect_one(50001, 39, 2026, getter=self.getter,
                           clock=lambda: self.now, **kwargs)

    def test_exact_five_requests_including_status_and_two_base_calls(self):
        out = self.run_one()
        self.assertEqual(len(self.calls), 5)
        self.assertEqual(out['requests_consumed_at_most'], 5)
        self.assertEqual(len(out['observations']), 2)
        self.assertEqual([x[0] for x in self.calls[:4]],
                         ['status', 'fixtures', 'leagues', 'standings'])
        self.assertEqual(out['status'], 'COMPLETE_BOUNDED_RESEARCH_OBSERVATIONS')
        for key in ('monetary_permission', 'execution_enabled', 'model_updated',
                    'raw_account_status_saved'):
            self.assertFalse(out[key])
        self.assertNotIn('PRIVATE_ACCOUNT_VALUE', json.dumps(out))

    def test_daily_reserve_stops_after_single_status_request(self):
        self.used = 96
        with self.assertRaisesRegex(ValueError, 'insufficient quota'):
            self.run_one()
        self.assertEqual(self.calls, [('status', {})])

    def test_minute_zero_from_new_receipt_aborts_remaining_requests(self):
        self.stop_after_one = True
        out = self.run_one()
        self.assertEqual(out['status'], 'PARTIAL_QUOTA_STOP')
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(len(out['observations']), 1)

    def test_unexpected_league_season_stops_before_third_request(self):
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            collect_one(50001, 39, 2025, getter=self.getter,
                        clock=lambda: self.now)
        self.assertEqual([x[0] for x in self.calls], ['status', 'fixtures'])

    def test_provider_error_never_retries_and_no_secrets_emitted(self):
        self.fail_on = 'standings'
        with self.assertRaisesRegex(ValueError, 'PRIVATE_URL_OR_SECRET'):
            self.run_one()
        self.assertEqual([x[0] for x in self.calls],
                         ['status', 'fixtures', 'leagues', 'standings'])
        # The CLI wrapper replaces provider errors with a fixed public code.

    def test_tampered_packet_cannot_be_saved_as_completed(self):
        self.tamper = True
        with self.assertRaisesRegex(ValueError, 'provenance'):
            self.run_one()
        self.assertEqual(len(self.calls), 4)

    def test_reject_more_than_eleventotal_and_low_reserve_before_network(self):
        for config in ({'max_requests': 6}, {'max_requests': 8}, {'max_requests': 12}, {'reserve': 0}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                self.run_one(**config)
        self.assertEqual(self.calls, [])

    def test_cli_without_explicit_execution_is_network_free(self):
        with redirect_stdout(io.StringIO()) as captured:
            code = main(['--fixture-id', '50001', '--league-id', '39',
                         '--season', '2026', '--output', 'NOT_WRITTEN.json'])
        self.assertEqual(code, 2)
        self.assertIn('NOT_EXECUTED', captured.getvalue())
        self.assertEqual(self.calls, [])

    def test_default_collector_requires_guarded_gateway_on_every_request(self):
        with patch('scripts.football_enrichment_collect._get', side_effect=self.getter) as fetch:
            # Add the new transport keyword without adding network operations.
            fetch.side_effect = lambda endpoint, params, **kwargs: (
                self.getter(endpoint, params) if kwargs == {'require_shared_budget': True}
                else self.fail('collector did not require the shared budget'))
            out = collect_one(50001, 39, 2026, clock=lambda: self.now)
        self.assertEqual(out['requests_consumed_at_most'], 5)
        self.assertEqual(fetch.call_count, 5)

    def test_shared_guard_prevents_default_direct_provider_before_network(self):
        with patch.dict('os.environ', {'SEFIROT_SPORTS_GATEWAY_URL': ''}), patch('sefirot.football_gateway.get') as direct:
            with self.assertRaisesRegex(ValueError, 'shared-budget'):
                collect_one(50001, 39, 2026, clock=lambda: self.now)
            direct.assert_not_called()

    def test_unknown_quota_never_authorizes_next_request(self):
        for call in (1, 2, 3, 4):
            for quota in ({}, {'x-ratelimit-remaining': '10'}):
                with self.subTest(call=call, quota=quota):
                    self.calls = []
                    self.quota_by_call = {call: quota}
                    with self.assertRaisesRegex(ValueError, 'quota unknown'):
                        self.run_one()
                    self.assertEqual(len(self.calls), call)

    def test_exhaustion_after_fixture_stops_before_coverage_request(self):
        for override in ({'x-ratelimit-remaining': '0'}, {'x-ratelimit-requests-remaining': '5'}):
            with self.subTest(override=override):
                self.calls = []
                self.quota_by_call = {2: {**DEFAULT_QUOTA, **override}}
                with self.assertRaisesRegex(ValueError, 'insufficient quota'):
                    self.run_one()
                self.assertEqual([c[0] for c in self.calls], ['status', 'fixtures'])

    def test_exhaustion_after_coverage_stops_before_enrichment(self):
        self.quota_by_call = {3: {**DEFAULT_QUOTA, 'x-ratelimit-remaining': '0'}}
        out = self.run_one()
        self.assertEqual(out['status'], 'PARTIAL_QUOTA_STOP')
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(out['observations'], [])

    def test_invalid_and_conflicting_quota_stop_without_leaking_values(self):
        for override in ({'x-ratelimit-remaining': 'PRIVATE_QUOTA_VALUE'},
                         {'x-ratelimit-remaining': True},
                         {'x-ratelimit-remaining': '301'},
                         {'x-ratelimit-requests-remaining': '101'},
                         {'x-ratelimit-limit': '0'}):
            with self.subTest(override=override):
                self.calls = []
                self.quota_by_call = {2: {**DEFAULT_QUOTA, **override}}
                with self.assertRaises(ValueError) as caught:
                    self.run_one()
                self.assertNotIn('PRIVATE_QUOTA_VALUE', str(caught.exception))
                self.assertEqual(len(self.calls), 2)


if __name__ == '__main__':
    unittest.main()
