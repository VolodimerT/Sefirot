"""Offline counterexamples for bounded API orchestration and private gateway."""
import copy
from contextlib import closing, redirect_stdout, redirect_stderr
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.cli import main
from sefirot.contracts import digest, time
from sefirot.data_session import collect_session, render_session
from sefirot.football_gateway import get_sports
from sefirot.football_provider import FootballRequestError
from sefirot.repository import Repository
from sefirot.sports_archive import archive_packets, validate_packet
from test_operations_upgrade import NOW, packet, row, stamp


def response(endpoint, params, data):
    return {'data': data, 'receipt': {'provider_host': 'v3.football.api-sports.io',
        'endpoint': '/' + endpoint, 'parameters': params, 'request_started_at': stamp(),
        'received_at': stamp(), 'payload_hash': digest(data), 'http_status': 200,
        'provider': 'API_FOOTBALL_V3', 'sports_only': True}}


class DataSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'run'
        self.calls = []
        self.targets = [row(100, status='NS', hours=3, score=(None, None)),
                        row(101, status='NS', hours=4, score=(None, None))]
        self.history = [row(10+n, hours=-48-n) for n in range(8)]
        self.clock = NOW
        self.used, self.limit, self.active = 1, 100, True
        self.history_failure = None

    def get(self, endpoint, params):
        self.calls.append((endpoint, copy.deepcopy(params)))
        if endpoint == 'status':
            data = {'errors': [], 'response': {'subscription': {'active': self.active, 'plan': 'Fictional'},
                'requests': {'current': self.used, 'limit_day': self.limit}}}
        else:
            if 'date' in params:
                rows = self.targets
            else:
                # History must be requested only after every cohort assignment.
                with closing(Repository(self.directory/'research.sqlite', read_only=True)) as repo:
                    self.assertEqual(len(repo.all('split_assignments')), len(self.targets))
                    self.assertEqual(repo.all('predictions'), [])
                if self.history_failure:
                    raise self.history_failure
                rows = self.history
            data = packet(rows)['data']
        return response(endpoint, params, copy.deepcopy(data))

    def run_session(self, **kwargs):
        return collect_session(self.directory, '2030-01-01', {9: 'LOWER'}, source_reliability=.95,
                               getter=self.get, clock=lambda: self.clock, **kwargs)

    def test_one_history_query_per_league_and_complete_research_grids(self):
        report = self.run_session()
        self.assertEqual(report['request_attempts'], 3)
        self.assertEqual(report['planned_fixtures'], 2)
        self.assertEqual(report['forecasts_created'], 2)
        self.assertEqual(report['status'], 'RESEARCH_FORECASTS_COLLECTED')
        self.assertEqual(len(report['history_queries']), 1)
        for fixture in report['fixtures']:
            self.assertEqual(fixture['main_research_contracts'], 50)
            self.assertEqual(fixture['goal_builders'], 14)
        with closing(Repository(self.directory/'research.sqlite', read_only=True)) as repo:
            self.assertEqual(len(repo.all('predictions')), 2)
            self.assertEqual(repo.all('decisions'), [])
            self.assertEqual(repo.all('bets'), [])
            self.assertEqual(repo.all('policy_approvals'), [])
            self.assertTrue(repo.verify())
        self.assertFalse(report['prices_requested']); self.assertFalse(report['holdout_passed'])
        self.assertFalse(report['monetary_permission']); self.assertFalse(report['execution_enabled'])
        saved = json.loads((self.directory/'REPORT.json').read_text())
        digest_value = saved.pop('hash'); self.assertEqual(digest(saved), digest_value)
        self.assertIn('Назначено матчей: 2', render_session(report))

    def test_missing_history_keeps_entire_predeclared_denominator(self):
        self.history = []
        report = self.run_session()
        self.assertEqual(report['planned_fixtures'], 2)
        self.assertEqual(report['forecasts_created'], 0)
        self.assertEqual(report['fixture_counts'], {'INSUFFICIENT_HISTORY': 2})
        self.assertEqual(report['fixtures'][0]['coverage']['teams']['home']['games_needed'], 8)

    def test_provider_season_denial_is_not_retried_per_fixture_or_turned_into_forecast(self):
        self.history_failure = FootballRequestError({'plan': 'Free plan season unavailable PRIVATE_SECRET'})
        report = self.run_session()
        self.assertEqual(report['request_attempts'], 3)
        self.assertIn('SEASON_ACCESS_DENIED', report['blockers'])
        self.assertEqual(report['fixture_counts'], {'INSUFFICIENT_HISTORY': 2})
        self.assertNotIn('PRIVATE_SECRET', json.dumps(report))

    def test_request_budget_stops_before_history_but_preserves_plan(self):
        report = self.run_session(max_requests=2)
        self.assertEqual(report['request_attempts'], 2)
        self.assertEqual(report['planned_fixtures'], 2)
        self.assertIn('SESSION_REQUEST_BUDGET_EXHAUSTED', report['blockers'])
        self.assertEqual(report['fixture_counts'], {'INSUFFICIENT_HISTORY': 2})

    def test_missing_credential_is_not_reported_as_network_request(self):
        def get(endpoint, params):
            raise ValueError('API_FOOTBALL_KEY is missing or invalid')
        self.get = get
        report = self.run_session()
        self.assertEqual(report['request_attempts'], 1)
        self.assertEqual(report['network_requests_upper_bound'], 0)
        self.assertEqual(report['received_packets'], 0)

    def test_history_from_wrong_league_season_or_live_status_is_not_archived(self):
        for key, value in [('id', 10), ('season', 2029), ('status', '1H')]:
            with self.subTest(key=key):
                self.directory = Path(self.temp.name) / ('history-' + key)
                self.history = [row(10+n, hours=-48-n) for n in range(8)]
                if key == 'status':
                    self.history[0]['fixture']['status']['short'] = value
                else:
                    self.history[0]['league'][key] = value
                report = self.run_session()
                self.assertEqual(report['forecasts_created'], 0)
                self.assertEqual(len(list((self.directory/'sports-archive').glob('*.json'))), 1)

    def test_quota_reserve_stops_before_target_and_creates_no_ledger(self):
        self.used = 94
        report = self.run_session()
        self.assertEqual(report['request_attempts'], 1)
        self.assertIn('DAILY_QUOTA_RESERVE_REACHED', report['blockers'])
        self.assertFalse((self.directory/'research.sqlite').exists())

    def test_quota_header_can_lower_status_allowance(self):
        original = self.get
        def get(endpoint, params):
            out = original(endpoint, params)
            out['receipt']['quota'] = {'x-ratelimit-requests-remaining': '5'}
            return out
        self.get = get
        self.assertEqual(self.run_session()['request_attempts'], 1)

    def test_inactive_subscription_stops_without_fixture_calls(self):
        self.active = False
        report = self.run_session()
        self.assertEqual(report['request_attempts'], 1)
        self.assertIn('SUBSCRIPTION_INACTIVE', report['blockers'])

    def test_invalid_quota_fails_closed(self):
        self.used = True
        report = self.run_session()
        self.assertEqual(report['request_attempts'], 1)
        self.assertEqual(report['status'], 'COLLECTION_INCOMPLETE')

    def test_auth_network_and_429_errors_stop_without_secret_text(self):
        for message in ('provider HTTP 401', 'provider HTTP 429', 'provider network unavailable'):
            with self.subTest(message=message):
                self.directory = Path(self.temp.name)/str(len(self.calls))
                def get(endpoint, params):
                    self.calls.append((endpoint, params)); raise ValueError(message + ' PRIVATE_SECRET')
                self.get = get
                report = self.run_session()
                self.assertEqual(report['request_attempts'], 1)
                self.assertNotIn('PRIVATE_SECRET', json.dumps(report))

    def test_existing_run_refused_before_network_and_no_overwrite(self):
        self.directory.mkdir(); (self.directory/'REPORT.json').write_text('owner content')
        with self.assertRaisesRegex(ValueError, 'already exists'):self.run_session()
        self.assertEqual(self.calls, [])
        self.assertEqual((self.directory/'REPORT.json').read_text(), 'owner content')

    def test_past_day_invalid_profile_and_future_archive_refused_before_network(self):
        bad_archive = Path(self.temp.name)/'future-archive'
        archive_packets([packet([row(5)], hours=1)], bad_archive, stamp(2))
        cases = [dict(day='2029-12-31'), dict(profiles={9:'UNKNOWN'}), dict(source_archive=bad_archive)]
        for options in cases:
            with self.subTest(options=options), self.assertRaises(ValueError):
                collect_session(self.directory, options.pop('day', '2030-01-01'), options.pop('profiles',{9:'LOWER'}),
                    source_reliability=.95, getter=self.get, clock=lambda: NOW, **options)
        self.assertEqual(self.calls, []); self.assertFalse(self.directory.exists())

    def test_previous_archive_can_supply_history_after_provider_refusal(self):
        old = Path(self.temp.name)/'archive'
        archive_packets([packet(self.history, hours=-1)], old, stamp())
        self.history_failure = FootballRequestError({'plan':'season unavailable'})
        report = self.run_session(source_archive=old)
        self.assertEqual(report['forecasts_created'], 2)
        with closing(Repository(self.directory/'research.sqlite',read_only=True)) as repo:
            pred = repo.all('predictions')[0]
            self.assertTrue(all(h['received_at'] == stamp(-1) for h in pred['sports']['history']))

    def test_invalid_api_query_identity_and_replayed_receipt_are_rejected(self):
        for kind in ('parameters', 'time', 'hash'):
            with self.subTest(kind=kind):
                self.directory = Path(self.temp.name)/kind
                def get(endpoint, params):
                    out = response('status', params, {'errors':[], 'response':{}})
                    if kind == 'parameters':out['receipt']['parameters']={'apiKey':'PRIVATE_SECRET'}
                    if kind == 'time':out['receipt']['request_started_at']=stamp(-1)
                    if kind == 'hash':out['receipt']['payload_hash']='wrong'
                    return out
                self.get = get
                report = self.run_session()
                self.assertEqual(report['status'],'COLLECTION_INCOMPLETE')
                self.assertEqual(report['request_attempts'],1)
                self.assertNotIn('PRIVATE_SECRET',json.dumps(report))

    def test_wrong_local_day_and_ns_result_abort_without_predictions(self):
        for kind in ('date','result'):
            with self.subTest(kind=kind):
                self.directory = Path(self.temp.name)/kind
                self.targets=[row(100,status='NS',hours=27 if kind=='date' else 3,score=(0,0) if kind=='result' else (None,None))]
                report=self.run_session()
                self.assertEqual(report['status'],'COLLECTION_INCOMPLETE')
                self.assertEqual(report['forecasts_created'],0)

    def test_crossing_kickoff_keeps_missed_match_in_denominator(self):
        original=self.get
        def get(endpoint,params):
            out=original(endpoint,params)
            if 'season' in params:self.clock=NOW+timedelta(hours=5)
            return out
        self.get=get
        report=self.run_session()
        self.assertEqual(report['planned_fixtures'],2)
        self.assertEqual(report['fixture_counts'],{'MISSED_PREMATCH_WINDOW':2})

    def test_grid_failure_does_not_erase_sealed_forecasts_or_other_fixture(self):
        with patch('sefirot.data_session.create_grid',side_effect=ValueError('cannot freeze')):
            report=self.run_session()
        self.assertEqual(report['forecasts_created'],2)
        self.assertEqual(len(report['fixtures']),2)
        self.assertEqual(report['status'],'RESEARCH_COLLECTION_WITH_ARTIFACT_GAPS')
        self.assertTrue(report['journal_integrity'])

    def test_collector_seals_remain_scoreable_with_original_api_result_jobs(self):
        from sefirot.forward import settle_plan
        from sefirot.forward_scorecard import create_scorecard
        from sefirot.service import Service
        report=self.run_session()
        with closing(Repository(self.directory/'research.sqlite')) as repo:
            service=Service(repo,clock=lambda:NOW+timedelta(hours=6))
            results=packet([row(100,hours=3,score=(1,0)),row(101,hours=4,score=(2,2))],hours=6)
            settle_plan(service,report['plan_id'],results)
            score=create_scorecard(service,report['plan_id'],stamp(6))
            self.assertEqual(score['scored_fixtures'],2)
            self.assertFalse(score['holdout_passed']);self.assertFalse(score['monetary_permission'])

    def test_cli_one_command_does_not_create_global_db_and_closes_run_ledger(self):
        argv=['--db',str(Path(self.temp.name)/'unused.sqlite'),'data-session','--date','2030-01-01',
            '--directory',str(self.directory),'--league-profile','9=LOWER','--source-reliability','.95','--text']
        with patch('sefirot.data_session.get_sports',side_effect=self.get), \
             patch('sefirot.data_session.datetime') as dt, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            dt.now.return_value=NOW
            self.assertEqual(main(argv),0)
            self.assertEqual(main(argv),2)
        self.assertFalse((Path(self.temp.name)/'unused.sqlite').exists())
        with closing(Repository(self.directory/'research.sqlite',read_only=True)) as repo:self.assertTrue(repo.verify())


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'SEFIROT_SPORTS_GATEWAY_URL':
            'https://kxqpwgwihtjmqlcxgfxp.supabase.co/functions/v1/sefirot-sports-gateway',
            'SEFIROT_SPORTS_GATEWAY_TOKEN':'FICTIONAL_TOKEN'},clear=False)
        self.env.start(); self.addCleanup(self.env.stop)

    def call(self, mutate=None, http=200):
        data=packet([row(100,status='NS',hours=3,score=(None,None))])['data']
        wrapper={'ok':True,'provider':'API_FOOTBALL_V3','provider_host':'v3.football.api-sports.io',
            'endpoint':'/fixtures','params':{'date':'2030-01-01'},'received_at':stamp(),
            'sports_only':True,'monetary_permission':False,'execution_enabled':False,'data':data}
        if mutate:mutate(wrapper)
        class Response:
            status=http
            def read(self,limit):return json.dumps(wrapper).encode()
            def close(self):pass
        def open_request(request,timeout):
            self.assertEqual(request.get_method(),'POST')
            self.assertNotIn('apiKey',request.full_url)
            return Response()
        return get_sports('fixtures',{'date':'2030-01-01'},opener=open_request,clock=lambda:NOW)

    def test_gateway_receipt_preserves_transport_and_never_contains_token(self):
        out=self.call(); validate_packet(out,stamp())
        self.assertEqual(out['receipt']['transport'],'SUPABASE_GATEWAY')
        self.assertNotIn('FICTIONAL_TOKEN',json.dumps(out))

    def test_gateway_token_can_be_read_from_existing_private_env_file(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'credentials.env';path.write_text('SEFIROT_SPORTS_GATEWAY_TOKEN=FICTIONAL_FILE_TOKEN\n')
            with patch.dict(os.environ, {'SEFIROT_ENV_FILE':str(path)}):
                del os.environ['SEFIROT_SPORTS_GATEWAY_TOKEN']
                out=self.call()
                self.assertNotIn('FICTIONAL_FILE_TOKEN',json.dumps(out))

    def test_gateway_identity_parameters_permissions_and_future_time_are_rejected(self):
        for key,value in [('provider_host','evil.test'),('params',{}),('endpoint','/odds'),
                          ('execution_enabled',True),('received_at',stamp(1)),('sports_only',False)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.call(lambda wrapper:wrapper.update({key:value}))

    def test_gateway_provider_rejection_has_safe_typed_reason(self):
        with self.assertRaises(FootballRequestError) as error:
            self.call(lambda w:w.update(ok=False,error='PROVIDER_REJECTED_REQUEST',provider_errors={'plan':'season PRIVATE_SECRET'}),422)
        self.assertEqual(error.exception.code,'SEASON_ACCESS_DENIED')
        self.assertNotIn('PRIVATE_SECRET',str(error.exception))

    def test_redirect_credentials_in_url_and_live_odds_endpoints_are_refused(self):
        urls=['http://kxqpwgwihtjmqlcxgfxp.supabase.co/functions/v1/sefirot-sports-gateway',
              'https://evil.test/functions/v1/sefirot-sports-gateway',
              'https://user:pass@kxqpwgwihtjmqlcxgfxp.supabase.co/functions/v1/sefirot-sports-gateway',
              os.environ['SEFIROT_SPORTS_GATEWAY_URL']+'?token=private']
        for url in urls:
            with patch.dict(os.environ,{'SEFIROT_SPORTS_GATEWAY_URL':url}), self.assertRaises(ValueError):
                get_sports('status',{},opener=lambda *a,**k:self.fail('network called'))
        with self.assertRaises(ValueError):get_sports('odds/live',{})

    def test_gateway_pagination_malformed_json_and_incomplete_receipt_fail_closed(self):
        with self.assertRaises(ValueError):self.call(lambda w:w['data']['paging'].update(total=2))
        out=self.call(); del out['receipt']['upstream_received_at']
        with self.assertRaises(ValueError):validate_packet(out,stamp())


if __name__=='__main__':unittest.main()
