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
        report = self.run_session(research_grids=True)
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

    def test_default_collection_never_calls_research_grids(self):
        with patch('sefirot.market_grid.create_grid', side_effect=AssertionError('LABS entered')), \
             patch('sefirot.builder_research.create_builder_grid', side_effect=AssertionError('LABS entered')):
            report = self.run_session()
        self.assertEqual(report['forecasts_created'], 2)
        self.assertFalse(report['research_grids_enabled'])
        for fixture in report['fixtures']:
            self.assertEqual(fixture['artifact_status'], 'SEALED_FORECAST_ONLY')
            self.assertEqual(fixture['main_research_contracts'], 0)
            self.assertEqual(fixture['goal_builders'], 0)
        self.assertFalse(list(self.directory.rglob('*grid.json')))
        self.assertNotIn('RESEARCH_GRID_UNAVAILABLE', report['blockers'])

    def test_enabling_grids_preserves_original_forecasts_and_cohort(self):
        lean = self.run_session()
        with closing(Repository(self.directory/'research.sqlite', read_only=True)) as repo:
            original = repo.all('predictions')
            cohort = repo.all('split_assignments')
        self.directory = Path(self.temp.name) / 'labs'
        labs = self.run_session(research_grids=True)
        with closing(Repository(self.directory/'research.sqlite', read_only=True)) as repo:
            self.assertEqual(repo.all('predictions'), original)
            self.assertEqual(repo.all('split_assignments'), cohort)
            self.assertEqual(repo.all('bets'), [])
        self.assertEqual(lean['plan_id'], labs['plan_id'])
        self.assertEqual(lean['forecasts_created'], labs['forecasts_created'])

    def test_non_boolean_research_mode_rejected_before_io(self):
        for mode in ('false', 1, None):
            with self.assertRaisesRegex(ValueError, 'explicit boolean'):
                self.run_session(research_grids=mode)
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.calls, [])

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

    def test_empty_minute_window_stops_before_date_despite_available_daily_quota(self):
        original = self.get
        def get(endpoint, params):
            out = original(endpoint, params)
            out['receipt']['quota'] = {'x-ratelimit-remaining': '0', 'x-ratelimit-limit': '10'}
            return out
        self.get = get
        report = self.run_session()
        self.assertEqual(report['request_attempts'], 1)
        self.assertEqual(report['received_packets'], 1)
        self.assertGreater(report['quota_remaining_conservative'], 5)
        self.assertEqual(report['minute_remaining_conservative'], 0)
        self.assertIn('PROVIDER_RATE_LIMIT_WINDOW_EXHAUSTED', report['blockers'])
        self.assertFalse((self.directory/'research.sqlite').exists())

    def test_minute_budget_stops_another_league_and_preserves_cohort(self):
        self.targets[1]['league']['id'] = 10
        original = self.get
        def get(endpoint, params):
            out = original(endpoint, params)
            out['receipt']['quota'] = {'x-ratelimit-remaining': '2' if endpoint == 'status' else '1'}
            return out
        report = collect_session(self.directory,'2030-01-01',{9:'LOWER',10:'MEN'},
            source_reliability=.95,getter=get,clock=lambda:self.clock)
        self.assertEqual(report['request_attempts'], 3)
        self.assertEqual(report['planned_fixtures'], 2)
        self.assertEqual(report['forecasts_created'], 1)
        self.assertEqual(report['minute_remaining_conservative'], 0)
        self.assertEqual(report['history_queries'][1]['status'], 'PROVIDER_RATE_LIMIT_WINDOW_EXHAUSTED')

    def test_larger_minute_header_does_not_refill_a_conservative_session_allowance(self):
        self.targets[1]['league']['id'] = 10
        original = self.get
        def get(endpoint, params):
            out = original(endpoint, params)
            out['receipt']['quota'] = {'x-ratelimit-remaining': '2' if endpoint == 'status' else '99'}
            return out
        report = collect_session(self.directory,'2030-01-01',{9:'LOWER',10:'MEN'},
            source_reliability=.95,getter=get,clock=lambda:self.clock)
        self.assertEqual(report['request_attempts'], 3)
        self.assertEqual(report['minute_remaining_conservative'], 0)
        self.assertEqual(report['history_queries'][1]['status'], 'PROVIDER_RATE_LIMIT_WINDOW_EXHAUSTED')

    def test_invalid_minute_header_is_rejected_without_private_text(self):
        original = self.get
        for value in ('PRIVATE_SECRET', True, '-1 PRIVATE_SECRET', '١'):
            with self.subTest(value=value):
                self.directory = Path(self.temp.name)/('invalid-minute-'+str(len(self.calls)))
                def get(endpoint, params):
                    out = original(endpoint, params)
                    out['receipt']['quota'] = {'x-ratelimit-remaining': value}
                    return out
                report = collect_session(self.directory,'2030-01-01',{9:'LOWER'},
                    source_reliability=.95,getter=get,clock=lambda:self.clock)
                self.assertEqual(report['request_attempts'], 1)
                self.assertEqual(report['received_packets'], 0)
                self.assertNotIn('PRIVATE_SECRET', json.dumps(report))

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
        with patch('sefirot.market_grid.create_grid',side_effect=ValueError('cannot freeze')):
            report=self.run_session(research_grids=True)
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


    def test_provider_access_denial_stops_remaining_league_requests(self):
        self.targets[1]['league']['id']=10
        self.history_failure=FootballRequestError({'access':'PRIVATE_SECRET'})
        report=collect_session(self.directory,'2030-01-01',{9:'LOWER',10:'MEN'},
            source_reliability=.95,getter=self.get,clock=lambda:self.clock)
        self.assertEqual(report['request_attempts'],3)
        self.assertEqual(len(report['history_queries']),2)
        self.assertTrue(all(q['status']=='PROVIDER_ACCESS_DENIED' for q in report['history_queries']))
        self.assertEqual(report['forecasts_created'],0)
        self.assertEqual(report['planned_fixtures'],2)
        self.assertNotIn('PRIVATE_SECRET',json.dumps(report))

    def test_camel_case_rate_limit_and_account_suspension_stop_other_leagues(self):
        self.targets[1]['league']['id'] = 10
        for index, (errors, reason) in enumerate([
                ({'rateLimit':'PRIVATE_SECRET'},'PROVIDER_QUOTA_EXHAUSTED'),
                ({'RATELIMIT':'PRIVATE_SECRET'},'PROVIDER_QUOTA_EXHAUSTED'),
                ({'access':'Your account has been suspended PRIVATE_SECRET'},'PROVIDER_ACCOUNT_SUSPENDED')]):
            with self.subTest(reason=reason):
                self.directory = Path(self.temp.name)/('provider-stop-'+str(index))
                self.history_failure = FootballRequestError(errors)
                report = collect_session(self.directory,'2030-01-01',{9:'LOWER',10:'MEN'},
                    source_reliability=.95,getter=self.get,clock=lambda:self.clock)
                self.assertEqual(report['request_attempts'], 3)
                self.assertEqual(report['planned_fixtures'], 2)
                self.assertTrue(all(q['status']==reason for q in report['history_queries']))
                self.assertNotIn('PRIVATE_SECRET', json.dumps(report))


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

    def test_http_200_provider_access_denial_is_not_reported_as_invalid_token(self):
        with self.assertRaises(FootballRequestError) as error:
            self.call(lambda w:w.update(ok=False,error='PROVIDER_REJECTED_REQUEST',
                provider_errors={'access':'PRIVATE_SECRET'}),422)
        self.assertEqual(error.exception.code,'PROVIDER_ACCESS_DENIED')
        self.assertNotIn('PRIVATE_SECRET',str(error.exception))

    def test_gateway_preserves_observed_quota_in_fixture_receipt(self):
        out=self.call(lambda w:w.update(quota={'x-ratelimit-requests-remaining':'5'}))
        self.assertEqual(out['receipt']['quota']['x-ratelimit-requests-remaining'],'5')
        validate_packet(out,stamp())

    def test_gateway_preserves_minute_allowance_and_limit(self):
        out=self.call(lambda w:w.update(quota={'x-ratelimit-remaining':'0','x-ratelimit-limit':'10'}))
        self.assertEqual(out['receipt']['quota'], {'x-ratelimit-remaining':'0','x-ratelimit-limit':'10'})
        validate_packet(out,stamp())

    def test_gateway_rate_limit_and_suspension_have_typed_private_safe_reasons(self):
        for errors, reason in (({'rateLimit':'PRIVATE_SECRET'},'PROVIDER_QUOTA_EXHAUSTED'),
                ({'access':'provider account suspended PRIVATE_SECRET'},'PROVIDER_ACCOUNT_SUSPENDED'),
                ({'access':'account is not suspended PRIVATE_SECRET'},'PROVIDER_ACCESS_DENIED')):
            with self.subTest(reason=reason), self.assertRaises(FootballRequestError) as caught:
                self.call(lambda w:w.update(ok=False,error='PROVIDER_REJECTED_REQUEST',provider_errors=errors),422)
            self.assertEqual(caught.exception.code,reason)
            self.assertNotIn('PRIVATE_SECRET',str(caught.exception))

    def test_gateway_rejects_malformed_or_unexpected_quota_without_echo(self):
        for quota in (None,[],{'token':'PRIVATE_SECRET'},
                      {'x-ratelimit-requests-remaining':'-1 PRIVATE_SECRET'},
                      {'x-ratelimit-requests-remaining':True}):
            with self.subTest(quota=quota),self.assertRaises(ValueError) as caught:
                self.call(lambda w:w.update(quota=quota))
            self.assertNotIn('PRIVATE_SECRET',str(caught.exception))

    def test_gateway_upstream_http_codes_survive_outer_502(self):
        from sefirot.data_session import _reason
        from sefirot.api_health import _failure
        for status,reason in ((401,'PROVIDER_AUTH_FAILED'),(403,'PROVIDER_AUTH_FAILED'),
                             (429,'PROVIDER_QUOTA_EXHAUSTED')):
            with self.subTest(status=status),self.assertRaises(ValueError) as caught:
                self.call(lambda w:w.update(ok=False,error='UPSTREAM_HTTP_ERROR',
                    upstream_http_status=status,detail='PRIVATE_SECRET'),502)
            self.assertEqual(_reason(caught.exception),reason)
            self.assertEqual(_failure(caught.exception)['http_status'],status)
            self.assertNotIn('PRIVATE_SECRET',str(caught.exception))

    def test_gateway_timeout_and_network_failure_stop_collection(self):
        from sefirot.data_session import _reason
        for error in ('UPSTREAM_TIMEOUT','UPSTREAM_UNAVAILABLE'):
            with self.subTest(error=error),self.assertRaises(ValueError) as caught:
                self.call(lambda w:w.update(ok=False,error=error,detail='PRIVATE_SECRET'),502)
            self.assertEqual(_reason(caught.exception),'PROVIDER_NETWORK_UNAVAILABLE')
            self.assertNotIn('PRIVATE_SECRET',str(caught.exception))

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
