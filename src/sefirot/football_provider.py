"""Sports-only API-Football source; missing sporting facts remain missing."""
from datetime import date
import re
from .contracts import PROFILES, digest, integer, number, text, time, result_chronology
from .credentials import credential
from .football_query import validate_fixture_query, validate_fixture_query_parameters
from .provider_transport import ProviderConnection, request_json

HOST = 'v3.football.api-sports.io'
MAX_PROVIDER_ID = 2**63-1
PARAMETERS = {
    'status': set(),
    'leagues': {'id','name','country','code','season','team','type','current','search','last'},
    'teams': {'id','name','league','season','country','code','venue','search'},
    'fixtures': {'id','ids','date','league','season','team','last','next','from','to','round','status','venue','timezone'},
    'fixtures/lineups': {'fixture','team','player','type'},
    'fixtures/statistics': {'fixture','team','type','half'},
    'injuries': {'league','season','fixture','team','player','date','ids','timezone'},
    # Quota-aware, read-only research sources; no odds, provider predictions or live.
    'standings': {'league','season','team'},
    'teams/statistics': {'league','season','team','date'},
    'fixtures/headtohead': {'h2h','last','league','season','from','to','status','venue'},
    'fixtures/events': {'fixture','team','player','type'},
    'fixtures/players': {'fixture','team'},
    'coachs': {'id','team','search'},
    'players/squads': {'team','player'},
    'players/topscorers': {'league','season'},
    'players/topassists': {'league','season'},
    'players/topyellowcards': {'league','season'},
    'players/topredcards': {'league','season'},
}
OBJECT_RESPONSE_ENDPOINTS = frozenset({'teams/statistics'})
ENRICHMENT_REQUIRED = {
    'standings': {'league','season'},
    'teams/statistics': {'league','season','team'},
    'fixtures/headtohead': {'h2h'},
    'fixtures/events': {'fixture'},
    'fixtures/players': {'fixture'},
    'coachs': set(),
    'players/squads': set(),
    'players/topscorers': {'league','season'},
    'players/topassists': {'league','season'},
    'players/topyellowcards': {'league','season'},
    'players/topredcards': {'league','season'},
}


def validate_enrichment_request(endpoint, params):
    """Extra fail-closed validation for new endpoints, keeping old API contracts."""
    required = ENRICHMENT_REQUIRED.get(endpoint)
    if required is None:
        return
    if not required.issubset(params):
        raise ValueError('missing required sports query parameter')
    if endpoint in {'coachs', 'players/squads'} and not params:
        raise ValueError('sports identity selector required')
    import re as _re
    for name in ('fixture','league','season','team','id','player','last'):
        if name in params:
            value = params[name]
            if isinstance(value, bool) or not _re.fullmatch(r'[0-9]{1,10}', str(value)) or int(value) <= 0:
                raise ValueError('invalid sports numeric selector')
    if 'last' in params and int(params['last']) > 50:
        raise ValueError('bounded sports history selector required')
    if endpoint == 'fixtures/headtohead':
        pair = params['h2h']
        if not isinstance(pair, str) or not _re.fullmatch(r'[1-9][0-9]{0,9}-[1-9][0-9]{0,9}', pair):
            raise ValueError('invalid head-to-head team pair')
        if len(set(pair.split('-'))) != 2:
            raise ValueError('head-to-head requires distinct teams')
    if endpoint == 'coachs' and 'search' in params and (
            not isinstance(params['search'], str) or len(params['search']) < 3):
        raise ValueError('coach search too short')
    if endpoint == 'teams/statistics' and 'date' in params and (
            not isinstance(params['date'], str) or
            not _re.fullmatch(r'20[0-9]{2}-[01][0-9]-[0-3][0-9]', params['date'])):
        raise ValueError('invalid statistics cutoff date')
    if endpoint == 'teams/statistics' and 'date' in params:
        try:
            date.fromisoformat(params['date'])
        except ValueError:
            raise ValueError('invalid statistics cutoff date') from None


def validate_provider_data(endpoint, data):
    """All transports reject incomplete pages and bool/count ambiguities."""
    if not isinstance(data, dict) or data.get('errors') not in ([], {}):
        raise ValueError('API-Football provider response malformed')
    if endpoint == 'status':
        if not isinstance(data.get('response'), dict):
            raise ValueError('API-Football status malformed')
        return
    if type(data.get('results')) is not int or data['results'] < 0:
        raise ValueError('API-Football response count malformed')
    if endpoint in OBJECT_RESPONSE_ENDPOINTS:
        if not isinstance(data.get('response'), dict):
            raise ValueError('API-Football object response malformed')
    elif not isinstance(data.get('response'), list) or data['results'] != len(data['response']):
        raise ValueError('API-Football response count malformed')
    paging = data.get('paging')
    if (not isinstance(paging, dict) or type(paging.get('current')) is not int
            or paging['current'] != 1 or type(paging.get('total')) is not int
            or paging['total'] not in (0, 1)):
        raise ValueError('API-Football incomplete pagination; do not import partial data')


class FootballRequestError(ValueError):
    """Fixed public reasons; upstream error text may contain private values."""
    def __init__(self, errors, receipt=None):
        keys = {str(k).lower() for k in errors} if isinstance(errors, dict) else set()
        words = str(errors).lower()
        access = next((value for key, value in errors.items() if str(key).lower() == 'access'), None) if isinstance(errors, dict) else None
        suspended = isinstance(access, str) and re.search(
            r'\baccount\s+(?:(?:is|has been)\s+)?(?:(?:temporarily|permanently)\s+)?suspended\b',
            access, re.IGNORECASE)
        self.code = ('SEASON_ACCESS_DENIED' if 'plan' in keys and 'season' in words else
                     'PROVIDER_QUOTA_EXHAUSTED' if keys & {'requests', 'ratelimit', 'rate_limit', 'rate limit'} else
                     'PROVIDER_AUTH_FAILED' if keys & {'token', 'key', 'api_key'} else
                     'PROVIDER_ACCOUNT_SUSPENDED' if suspended else
                     'PROVIDER_ACCESS_DENIED' if 'access' in keys else
                     'PROVIDER_REJECTED_REQUEST')
        self.receipt = receipt
        super().__init__('API-Football provider rejected request; HTTP 200 is not success: ' + self.code)


def get(endpoint, params=None, *, api_key=None, connection_factory=ProviderConnection):
    params = dict(params or {})
    if endpoint not in PARAMETERS or set(params) - PARAMETERS[endpoint]:
        raise ValueError('unsupported sports endpoint/parameters; odds and live queries disabled')
    if any(not isinstance(v, (str,int)) or isinstance(v,bool) for v in params.values()):
        raise ValueError('invalid sports query parameter')
    validate_enrichment_request(endpoint, params)
    if endpoint == 'fixtures':
        validate_fixture_query_parameters(params)
    packet = request_json(HOST, '/' + endpoint, params,
                          {'x-apisports-key': api_key or credential('API_FOOTBALL_KEY')},
                          connection_factory=connection_factory)
    data = packet['data']
    if not isinstance(data, dict) or 'errors' not in data or 'response' not in data:
        raise ValueError('API-Football response malformed')
    if data['errors']:
        raise FootballRequestError(data['errors'], packet['receipt'])
    validate_provider_data(endpoint, data)
    if endpoint == 'fixtures':
        validate_fixture_query(data, params)
    packet['receipt'].update(provider='API_FOOTBALL_V3', sports_only=True)
    return packet


def status_summary(packet):
    data = packet['data']['response']
    if not isinstance(data, dict):
        raise ValueError('API-Football status malformed')
    sub, requests = data.get('subscription', {}), data.get('requests', {})
    return {'subscription_active':sub.get('active'),'plan':sub.get('plan'),
            'requests_current':requests.get('current'),'requests_limit_day':requests.get('limit_day'),
            'receipt':packet['receipt']}


def _rows(packet):
    receipt = packet['receipt']
    if receipt['provider_host'] != HOST or receipt['endpoint'] != '/fixtures':
        raise ValueError('fixture response required')
    if digest(packet['data']) != receipt['payload_hash']:
        raise ValueError('fixture response integrity mismatch')
    time(receipt['received_at'])
    if packet['data']['errors'] or packet['data'].get('paging', {}).get('total', 1) > 1:
        raise ValueError('invalid or incomplete fixture response')
    return packet['data']['response']


def fixture_identity(row):
    fixture, league, teams = row['fixture'], row['league'], row['teams']
    integer(fixture['id'], 'fixture id', 1, MAX_PROVIDER_ID);integer(league['id'], 'league id', 1, MAX_PROVIDER_ID)
    for side in ('home','away'):
        integer(teams[side]['id'], 'team id', 1, MAX_PROVIDER_ID);text(teams[side]['name'], 'team name')
    if teams['home']['id'] == teams['away']['id']:
        raise ValueError('fixture teams must differ')
    start = time(fixture['date'])
    if fixture.get('timestamp') is not None and abs(start.timestamp() - fixture['timestamp']) > 1:
        raise ValueError('fixture kickoff timestamps disagree')
    return {'id':f"api-football:fixture:{fixture['id']}", 'home':teams['home']['name'],
            'away':teams['away']['name'], 'league':f"api-football:league:{league['id']}",
            'kickoff':start.isoformat(),'sport':'football','format':'REGULATION_90'}


def select_prematch(packet, fixture_id):
    integer(fixture_id, 'fixture id', 1, MAX_PROVIDER_ID)
    matches = [r for r in _rows(packet) if r.get('fixture', {}).get('id') == fixture_id]
    if len(matches) != 1:
        raise ValueError('exact unique API-Football fixture required')
    row = matches[0];match = fixture_identity(row)
    if row['fixture']['status']['short'] != 'NS' or time(match['kickoff']) <= time(packet['receipt']['received_at']):
        raise ValueError('fixture is not prematch; live/postponed/cancelled imports disabled')
    return row, match


def normalize_sports(target_packet, fixture_id, history_packets, *, profile, source_reliability):
    if profile not in PROFILES or profile == 'UNKNOWN':
        raise ValueError('explicit competition profile required')
    number(source_reliability, 'operator source reliability', 0, 1)
    _, match = select_prematch(target_packet, fixture_id)
    match['competition_profile'] = profile
    packets = [target_packet, *history_packets]
    as_of = max((p['receipt']['received_at'] for p in packets), key=time)
    if time(as_of) >= time(match['kickoff']):
        raise ValueError('sports collection crossed kickoff; prematch import rejected')
    received = target_packet['receipt']['received_at'];evidence = []
    for key,value in [('home_team',match['home']),('away_team',match['away']),('format',match['format'])]:
        evidence.append({'id':f'{match["id"]}:{key}','key':key,'value':value,'kind':'FACT',
                         'source_id':'api-football','observed_at':received,'published_at':received,
                         'received_at':received,'critical':True,'supports':[]})
    history, excluded, seen = [], [], set()
    for packet in history_packets:
        stamp = packet['receipt']['received_at']
        for row in _rows(packet):
            ident = fixture_identity(row);reason = None
            if ident['id'] == match['id']:reason = 'TARGET_RESULT_EXCLUDED'
            elif ident['league'] != match['league']:reason = 'OTHER_COMPETITION'
            elif row['fixture']['status']['short'] != 'FT':reason = 'NOT_REGULATION_FT; AET/PEN_NOT_IMPORTED'
            if reason is None:
                try:
                    result_chronology(ident['kickoff'],stamp,stamp)
                except ValueError:
                    reason = 'IMPOSSIBLE_RESULT_CHRONOLOGY'
            if reason:
                excluded.append({'id':ident['id'],'reason':reason});continue
            goals = row.get('score', {}).get('fulltime', {})
            for side in ('home','away'):integer(goals.get(side), 'regulation goals', 0, 50)
            normalized = {'id':ident['id'],'home':ident['home'],'away':ident['away'],
                          'league':ident['league'],'kickoff':ident['kickoff'],
                          'finished_at':stamp,'received_at':stamp,'home_goals':goals['home'],
                          'away_goals':goals['away'],'source_id':'api-football','competition_profile':profile}
            if ident['id'] in seen:raise ValueError('duplicate fixture across history responses')
            seen.add(ident['id']);history.append(normalized)
    sports = {'match':match,'as_of':as_of,
              'sources':[{'id':'api-football','independence_group':'api-sports',
                          'reliability':source_reliability,'enabled':True}],
              'evidence':evidence,'history':sorted(history,key=lambda r:(time(r['kickoff']),r['id']))}
    receipt = {'status':'IMPORTED_SPORTS_OBSERVATIONS; NOT_CERTIFIED_FORECAST',
               'fixture_id':fixture_id,'sports_hash':digest(sports),
               'source_receipts':[p['receipt'] for p in packets],'excluded_history':excluded,
               'missing_facts':['lineup','injuries','coach','rotation','tactics'],
               'source_reliability':'operator assertion; not independently calibrated',
               'timestamp_semantics':{
                   'published_at':'first observed published API response; original upstream publication time unknown',
                   'finished_at':'completion upper bound = FT receipt; exact final-whistle time unknown',
                   'history_received_at':'actual collection time, never backdated'},
               'execution_enabled':False,'monetary_permission':False}
    return {'sports':sports,'receipt':receipt}
