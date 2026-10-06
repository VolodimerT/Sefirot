"""Sports-only API-Football source; missing sporting facts remain missing."""
from .contracts import PROFILES, digest, integer, number, text, time
from .credentials import credential
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
}


def get(endpoint, params=None, *, api_key=None, connection_factory=ProviderConnection):
    params = dict(params or {})
    if endpoint not in PARAMETERS or set(params) - PARAMETERS[endpoint]:
        raise ValueError('unsupported sports endpoint/parameters; odds and live queries disabled')
    if any(not isinstance(v, (str,int)) or isinstance(v,bool) for v in params.values()):
        raise ValueError('invalid sports query parameter')
    packet = request_json(HOST, '/' + endpoint, params,
                          {'x-apisports-key': api_key or credential('API_FOOTBALL_KEY')},
                          connection_factory=connection_factory)
    data = packet['data']
    if not isinstance(data, dict) or 'errors' not in data or 'response' not in data:
        raise ValueError('API-Football response malformed')
    if data['errors']:
        raise ValueError('API-Football provider rejected request; HTTP 200 is not success')
    if endpoint != 'status':
        if not isinstance(data['response'], list) or data.get('results') != len(data['response']):
            raise ValueError('API-Football response count malformed')
        if data.get('paging', {}).get('total', 1) > 1:
            raise ValueError('API-Football incomplete pagination; do not import partial data')
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
            elif time(ident['kickoff']) >= time(stamp):reason = 'IMPOSSIBLE_RESULT_CHRONOLOGY'
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
