"""Offline adversarial checks for bounded API-Football enrichment and response contracts."""
import copy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import digest
from sefirot.football_enrichment import plan_fixture_enrichment
from sefirot.football_provider import validate_enrichment_request, get


def packet(endpoint, response, received, params=None):
    data = {'errors': [], 'response': response,
            'results': len(response) if isinstance(response, list) else 1,
            'paging': {'current': 1, 'total': 1}}
    return {'data': data, 'receipt': {
        'provider': 'API_FOOTBALL_V3', 'provider_host': 'v3.football.api-sports.io',
        'endpoint': '/' + endpoint, 'parameters': params or {}, 'received_at': received.isoformat(),
        'http_status': 200, 'sports_only': True, 'payload_hash': digest(data)}}


class EnrichmentContracts(unittest.TestCase):
    def setUp(self):
        self.at = datetime.now(timezone.utc) - timedelta(minutes=1)
        kickoff = self.at + timedelta(hours=2)
        self.fixture_row = {
            'fixture': {'id': 50001, 'date': kickoff.isoformat(), 'status': {'short': 'NS'}},
            'league': {'id': 39, 'season': 2026},
            'teams': {'home': {'id': 101, 'name': 'Alpha'}, 'away': {'id': 202, 'name': 'Beta'}}}
        self.coverage = {'standings': True, 'injuries': True,
           'fixtures': {'statistics_fixtures': True, 'statistics_players': True,
                        'events': True, 'lineups': True}}
        self.fixtures = packet('fixtures', [self.fixture_row], self.at - timedelta(seconds=40))
        self.leagues = packet('leagues', [{
            'league': {'id': 39}, 'seasons': [{'year': 2026, 'coverage': self.coverage}]}],
            self.at - timedelta(seconds=40))
        self.status = packet('status', {'subscription': {'active': True},
                                       'requests': {'current': 10, 'limit_day': 100}},
                             self.at - timedelta(seconds=15))

    def plan(self, **kwargs):
        return plan_fixture_enrichment(self.fixtures, self.leagues, self.status, 50001,
                                       at=self.at.isoformat(), **kwargs)

    def test_six_predeclared_context_requests_under_budget(self):
        result = self.plan()
        self.assertEqual(result['status'], 'READY_FOR_MANUAL_FETCH')
        self.assertEqual(len(result['requested']), 6)
        self.assertEqual([r['endpoint'] for r in result['requested']],
                         ['standings', 'teams/statistics', 'teams/statistics',
                          'fixtures/headtohead', 'injuries', 'coachs'])
        self.assertFalse(result['execution_enabled'])
        self.assertFalse(result['monetary_permission'])
        self.assertEqual(result['quota']['budget'], 6)

    def test_minute_quota_zero_prevents_all_requests(self):
        self.status['receipt']['quota'] = {'x-ratelimit-remaining': '0'}
        result = self.plan()
        self.assertEqual(result['status'], 'NO_ADMISSIBLE_REQUESTS')
        self.assertEqual(result['requested'], [])

    def test_daily_reserve_prevents_all_requests(self):
        self.status['data']['response']['requests']['current'] = 95
        self.status['receipt']['payload_hash'] = digest(self.status['data'])
        result = self.plan()
        self.assertEqual(result['quota']['budget'], 0)

    def test_deliberate_limit_is_at_most_eight(self):
        with self.assertRaises(ValueError): self.plan(max_calls=9)
        self.assertEqual(len(self.plan(max_calls=8)['requested']), 7)

    def test_season_team_totals_do_not_depend_on_detailed_fixture_stats_flag(self):
        self.coverage['fixtures']['statistics_fixtures'] = False
        self.leagues['receipt']['payload_hash'] = digest(self.leagues['data'])
        requested = self.plan()['requested']
        self.assertEqual(sum(r['endpoint'] == 'teams/statistics' for r in requested), 2)

    def test_lineup_allowed_only_close_to_kickoff(self):
        self.fixture_row['fixture']['date'] = (self.at + timedelta(minutes=45)).isoformat()
        self.fixtures['receipt']['payload_hash'] = digest(self.fixtures['data'])
        result = self.plan(max_calls=8)
        self.assertEqual(len(result['requested']), 8)
        self.assertEqual(result['requested'][-1]['endpoint'], 'fixtures/lineups')

    def test_postmatch_does_not_reuse_prematch_enrichment(self):
        self.fixture_row['fixture']['status']['short'] = 'FT'
        self.fixture_row['fixture']['date'] = (self.at - timedelta(days=2)).isoformat()
        self.fixtures['receipt']['payload_hash'] = digest(self.fixtures['data'])
        result = self.plan()
        self.assertEqual(result['phase'], 'POSTMATCH')
        self.assertEqual([r['endpoint'] for r in result['requested']],
                         ['fixtures/events', 'fixtures/statistics', 'fixtures/players'])

    def test_live_fixture_is_rejected(self):
        self.fixture_row['fixture']['status']['short'] = '1H'
        self.fixtures['receipt']['payload_hash'] = digest(self.fixtures['data'])
        with self.assertRaisesRegex(ValueError, 'live/extra-time'):
            self.plan()

    def test_coverage_missing_or_duplicate_league_rejected(self):
        self.leagues['data']['response'][0]['seasons'][0].pop('coverage')
        self.leagues['receipt']['payload_hash'] = digest(self.leagues['data'])
        with self.assertRaisesRegex(ValueError, 'coverage missing'):
            self.plan()
        self.leagues['data']['response'][0]['seasons'][0]['coverage'] = self.coverage
        self.leagues['data']['response'][0]['seasons'].append(
            copy.deepcopy(self.leagues['data']['response'][0]['seasons'][0]))
        self.leagues['receipt']['payload_hash'] = digest(self.leagues['data'])
        with self.assertRaisesRegex(ValueError, 'unique league-season'):
            self.plan()

    def test_bad_source_hash_and_future_receipt_rejected(self):
        self.fixtures['data']['response'][0]['league']['id'] = 40
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.plan()
        self.fixtures['receipt']['payload_hash'] = digest(self.fixtures['data'])
        self.fixtures['receipt']['received_at'] = (self.at + timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(ValueError, 'future'):
            self.plan()

    def test_stale_account_quota_receipt_stops_automated_plan(self):
        self.status['receipt']['received_at'] = (self.at - timedelta(minutes=6)).isoformat()
        with self.assertRaisesRegex(ValueError, 'snapshot stale'):
            self.plan()

    def test_object_response_may_have_multiple_aggregate_subkeys(self):
        import json
        raw = json.dumps({'errors': [], 'response': {'league': {'id': 39}, 'team': {'id': 101}},
                          'results': 11, 'paging': {'current': 1, 'total': 1}}).encode()
        class Resp:
            status = 200
            def read(self, n): return raw[:n]
            def getheader(self, n): return None
        class Conn:
            def __init__(self, host, timeout=15): self.r = Resp()
            def request(self, method, path, headers): pass
            def getresponse(self): return self.r
            def close(self): pass
        value = get('teams/statistics', {'league':39, 'season':2026, 'team':101},
                    api_key='SYNTHETIC', connection_factory=Conn)
        self.assertEqual(value['data']['results'], 11)

    def test_inactive_status_or_malformed_quota_rejected(self):
        self.status['data']['response']['subscription']['active'] = False
        self.status['receipt']['payload_hash'] = digest(self.status['data'])
        with self.assertRaisesRegex(ValueError, 'subscription inactive'):
            self.plan()
        self.status['data']['response']['subscription']['active'] = True
        self.status['receipt']['payload_hash'] = digest(self.status['data'])
        self.status['receipt']['quota'] = {'x-ratelimit-remaining': 'SECRET_KEY'}
        with self.assertRaisesRegex(ValueError, 'invalid minute'):
            self.plan()

    def test_incompatible_response_and_incomplete_pagination(self):
        self.leagues['data']['paging']['total'] = 2
        self.leagues['receipt']['payload_hash'] = digest(self.leagues['data'])
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.plan()

    def test_identical_or_missing_teams_rejected(self):
        self.fixture_row['teams']['away']['id'] = 101
        self.fixtures['receipt']['payload_hash'] = digest(self.fixtures['data'])
        with self.assertRaises(ValueError):
            self.plan()

    def test_new_endpoint_required_identity_and_no_unknown_bets(self):
        for endpoint, params in [('teams/statistics', {'team': 2}),
                                 ('standings', {'season': 2026}),
                                 ('fixtures/events', {}),
                                 ('fixtures/headtohead', {'h2h': '10-10'}),
                                 ('coachs', {}),
                                 ('players/squads', {})]:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_enrichment_request(endpoint, params)
        validate_enrichment_request('teams/statistics', {
            'league': 39, 'season': 2026, 'team': 2, 'date': '2026-10-12'})
        validate_enrichment_request('fixtures/headtohead', {'h2h': '101-202', 'last': 5})

    def test_team_stats_direct_object_shape(self):
        import json
        raw = json.dumps({'errors': [], 'response': {'league': {'id': 39}, 'team': {'id': 101}},
                          'results': 1, 'paging': {'current': 1, 'total': 1}}).encode()
        class Resp:
            status = 200
            def read(self, n): return raw[:n]
            def getheader(self, n): return None
        class Conn:
            def __init__(self, host, timeout=15): self.r = Resp()
            def request(self, method, path, headers): self.path = path
            def getresponse(self): return self.r
            def close(self): pass
        result = get('teams/statistics', {'league': 39,'season': 2026,'team': 101},
                     api_key='SYNTHETIC', connection_factory=Conn)
        self.assertEqual(result['data']['results'], 1)
        self.assertIsInstance(result['data']['response'], dict)


if __name__ == '__main__':
    unittest.main()
