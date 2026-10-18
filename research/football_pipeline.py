"""Append-only source ledger -> existing SEFIROT archive/model inputs.

Uses Repository jobs/audit transactions, never an alternative prediction engine.
Use a dedicated source database, not the owner's historical prediction ledger.
No networking on import/coverage/export. No cohort assignment, fit or bets.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
import tempfile
import re

from sefirot.contracts import Policy, canonical, digest, integer, time
from sefirot.football_provider import validate_provider_data
from sefirot.football_query import validate_fixture_query
from sefirot.provider_transport import strict_json_payload
from sefirot.sports_archive import archive_packets, export_sports, validate_packet
from sefirot.small_market import validate_statistics_packet, review_small_market

SOURCE = 'football-source-v1'
QC = 'football-source-qc-v1'
ATTEMPT = 'football-collection-attempt-v1'
ADAPTER = sha256(Path(__file__).read_bytes()).hexdigest()
MAX_BYTES = 2_000_000
LABELS = {'CORNERS': 'Corner Kicks', 'SHOTS': 'Total Shots',
          'SOT': 'Shots on Goal', 'YELLOW_CARDS': 'Yellow Cards'}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _append(repo, record):
    if repo.insert('jobs', record['id'], record, at=record['at']):
        repo.record_log('jobs', record['id'], record['at'], record)
        return True
    return False


def source_only(repo):
    if not repo.verify() or any(repo.all(t) for t in ('predictions','decisions','results','calibrators','split_assignments')):
        raise ValueError('DEDICATED_SOURCE_DB_REQUIRED')
    if any(r.get('schema') not in {SOURCE,QC,ATTEMPT} for r in repo.all('jobs')):
        raise ValueError('DEDICATED_SOURCE_DB_REQUIRED')


def _records(repo, schema):
    if not repo.verify():
        raise ValueError('SOURCE_LEDGER_INTEGRITY_FAILED')
    return [r for r in repo.all('jobs') if r.get('schema') == schema]


def _packet(source):
    return {'data': source['data'], 'receipt': source['receipt']}


def _qc(packet, at):
    r = packet['receipt']; endpoint = r['endpoint'].removeprefix('/')
    if (r['provider'] != 'API_FOOTBALL_V3' or r['provider_host'] != 'v3.football.api-sports.io'
            or r['sports_only'] is not True or type(r['http_status']) is not int or r['http_status'] != 200
            or r['transport'] != 'SUPABASE_GATEWAY' or digest(packet['data']) != r['payload_hash']
            or not time(r['request_started_at']) <= time(r['upstream_received_at'])
            <= time(r['received_at']) <= time(at)):
        raise ValueError('SOURCE_PROVENANCE_INVALID')
    validate_provider_data(endpoint, packet['data'])
    if endpoint == 'fixtures':
        validate_packet(packet, at)
        validate_fixture_query(packet['data'], r['parameters'])
        for row in packet['data']['response']:
            integer(row['league']['season'], 'season', 1990, 2200)
    elif endpoint == 'fixtures/statistics':
        validate_statistics_packet(packet)
    return endpoint


def ingest(repo, raw, *, imported_at=None, origin='SAVED_GATEWAY_PACKET'):
    """Commit safe source bytes FIRST; failed QC cannot roll back that commit.

The input can be a two-field packet or the original guarded-probe source_packet.
Original UTF-8, wrapper hash and provider payload/receipt are retained separately.
Account/credential-bearing/unknown-value payloads fail closed before persistence.
"""
    at = imported_at or utcnow()
    time(at)
    source_only(repo)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValueError('BOUNDED_SOURCE_BYTES_REQUIRED')
    source = strict_json_payload(raw)
    if (not isinstance(source, dict) or set(source) not in (
            {'data', 'receipt'}, {'data', 'receipt', 'schema', 'projection_hash'})):
        raise ValueError('SOURCE_PACKET_SHAPE')
    from scripts.chat_sports_probe import _safe_source
    if not isinstance(source['receipt'],dict) or not isinstance(source['receipt'].get('endpoint'),str):
        raise ValueError('SOURCE_RECEIPT_SHAPE')
    endpoint = source['receipt']['endpoint'].removeprefix('/')
    if (origin not in {'SAVED_GATEWAY_PACKET','SAVED_PROBE_RESPONSE','DAILY_PROBE'}
            and not re.fullmatch(r'CHAT_JOB:[0-9a-f-]{36}',origin)):
        raise ValueError('SOURCE_ORIGIN_INVALID')
    if (not _safe_source(source['data'], endpoint)
            or not _safe_source({'response':source['receipt']}, 'fixtures')
            or source['data'].get('errors') not in ({}, [])):
        raise ValueError('UNSAFE_SOURCE_NOT_STORED')
    # Inspect the WHOLE receipt too: arbitrary added headers/tokens never enter DB.
    allowed = {'provider', 'provider_host', 'endpoint', 'parameters', 'request_started_at',
               'received_at', 'upstream_received_at', 'payload_hash', 'http_status',
               'sports_only', 'transport', 'quota'}
    if not isinstance(source['receipt'], dict) or set(source['receipt']) - allowed:
        raise ValueError('UNSAFE_RECEIPT_NOT_STORED')
    # Arbitrary values in the receipt cannot be used as a credential envelope.
    if endpoint not in {'fixtures', 'fixtures/statistics', 'fixtures/lineups', 'status',
                        'leagues', 'teams/statistics'}:
        raise ValueError('UNSUPPORTED_SOURCE_ENDPOINT')
    key = 'football-source:' + sha256(raw).hexdigest()
    record = {'schema': SOURCE, 'id': key, 'at': at, 'origin': origin,
              'raw_sha256': sha256(raw).hexdigest(), 'source_packet_hash': digest(source),
              'source_packet': source, 'raw_utf8': raw.decode('utf-8'),
              'original_http_bytes_available': False, 'provider_origin_attested': False,
              'monetary_permission': False, 'execution_enabled': False}
    with repo.transaction():
        if not repo.verify():raise ValueError('SOURCE_LEDGER_INTEGRITY_FAILED')
        try: record = repo.get('jobs', key); added = False
        except ValueError: added = _append(repo, record)
    # Above commit is deliberately independent from all normalization/QC below.
    qid = 'football-qc:' + digest([key, ADAPTER])
    try:
        prior = repo.get('jobs', qid)
        return {**prior, 'added_source': added}
    except ValueError: pass
    try:
        endpoint = _qc(_packet(record['source_packet']), record['at'])
        accepted, reason = True, None
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        accepted, reason = False, 'PACKET_QC_FAILED'
    qc = {'schema': QC, 'id': qid, 'at': at, 'source_id': key,
          'adapter_hash': ADAPTER, 'endpoint': endpoint, 'accepted': accepted,
          'reason': reason, 'forecast_created': False, 'fit_allowed': False}
    with repo.transaction():_append(repo, qc)
    return {**qc, 'added_source': added}


def ingest_probe(repo, response, *, imported_at=None, origin='SAVED_PROBE_RESPONSE'):
    from scripts.chat_sports_probe import verify_evidence
    at = imported_at or utcnow(); results = []
    for q in response.get('queries', []):
        if 'source_packet' not in q:continue
        if verify_evidence(q)['status'] != 'CANONICAL_PACKET_ARCHIVED':
            raise ValueError('ORIGINAL_PROBE_BINDING_INVALID')
        results.append(ingest(repo, canonical(q['source_packet']).encode(),
                              imported_at=at, origin=origin))
    return results


def packets(repo, as_of):
    cutoff = time(as_of)
    sources = _records(repo, SOURCE)
    accepted = {r['source_id']:r for r in _records(repo, QC)
                if r['adapter_hash'] == ADAPTER and r['accepted'] and time(r['at'])<=cutoff}
    out = []
    for r in sources:
        if r['id'] not in accepted or time(r['at']) > cutoff:continue
        raw = r['raw_utf8'].encode()
        if sha256(raw).hexdigest() != r['raw_sha256'] or digest(strict_json_payload(raw)) != r['source_packet_hash']:
            raise ValueError('SOURCE_BYTES_CHANGED')
        packet = _packet(r['source_packet'])
        _qc(packet, r['at'])
        if time(packet['receipt']['received_at']) <= cutoff:
            out.append(({**r,'available_at':max(r['at'],accepted[r['id']]['at'],key=time)}, packet))
    return out


def league_view(repo, league=39, season=2026, *, as_of=None):
    integer(league, 'league', 1);integer(season, 'season', 1990, 2200)
    at = as_of or utcnow(); observations = defaultdict(list); statistics = defaultdict(list)
    full = []; bound = []; contexts = []; temporal={"PREMATCH":[],"POST_FT":[],"HISTORICAL_NS":[],"OTHER":[]}
    for rec, p in packets(repo, at):
        r = p['receipt']; endpoint = r['endpoint']
        if endpoint == '/fixtures':
            params = r['parameters']
            rows = [v for v in p['data']['response'] if v['league']['id'] == league and v['league']['season'] == season]
            if set(params) == {'league', 'season'} and str(params['league']) == str(league) and str(params['season']) == str(season):
                full.append((time(r['received_at']), rec['id'], {v['fixture']['id'] for v in rows}))
            for row in rows:
                observations[row['fixture']['id']].append((rec,p,row))
                received=time(r['received_at']);kickoff=time(row['fixture']['date'])
                state=row['fixture']['status']['short']
                if state=='NS' and received<kickoff:
                    phase='PREMATCH' if time(rec['available_at'])<kickoff else 'HISTORICAL_NS'
                elif state=='FT' and received>=kickoff+timedelta(minutes=90):phase='POST_FT'
                else:phase='OTHER'
                temporal[phase].append({'fixture_id':row['fixture']['id'],'league_id':league,'season':season,
                    'source_id':rec['id'],'received_at':r['received_at'],'available_at':rec['available_at'],
                    'kickoff':row['fixture']['date'],'provider_status':state})
            if rows:bound.append(rec['id'])
        elif endpoint == '/fixtures/statistics':
            statistics[int(r['parameters']['fixture'])].append((rec, p))
        elif endpoint == '/teams/statistics':contexts.append(rec['id'])
    fixtures = {}; rejected = Counter()
    for fid, versions in observations.items():
        identities = {(v['league']['id'],v['league']['season'],v['teams']['home']['id'],v['teams']['away']['id'],time(v['fixture']['date'])) for _,_,v in versions}
        latest = max(time(p['receipt']['received_at']) for _,p,_ in versions)
        simultaneous = [v for _,p,v in versions if time(p['receipt']['received_at']) == latest]
        finals = [v['score']['fulltime'] for _,_,v in versions if v['fixture']['status']['short'] == 'FT']
        if len(identities) != 1:reason = 'FIXTURE_IDENTITY_CHANGED'
        elif len({digest(v) for v in simultaneous}) != 1:reason = 'SIMULTANEOUS_FIXTURE_CONFLICT'
        elif len({digest(v) for v in finals}) > 1:reason = 'RESULT_REVISION_CONFLICT'
        else:reason = None
        if reason:rejected[reason] += 1;continue
        fixtures[fid] = simultaneous[0]
    expected = max(full, default=None)
    if expected and len({frozenset(v[2]) for v in full if v[0]==expected[0]})>1:
        rejected['SIMULTANEOUS_CALENDAR_CONFLICT']+=1;expected=None
    counts = {m: 0 for m in LABELS}; nulls = {m: 0 for m in LABELS}; stat_ok = set()
    for fid, versions in statistics.items():
        if fid not in fixtures:rejected['STATISTICS_FIXTURE_UNBOUND'] += 1;continue
        f = fixtures[fid]
        if f['fixture']['status']['short'] != 'FT':rejected['STATISTICS_NOT_CONFIRMED_FT'] += 1;continue
        first_ft = min(time(p['receipt']['received_at']) for _,p,v in observations[fid] if v['fixture']['status']['short']=='FT')
        teams = {f['teams'][s]['id'] for s in ('home', 'away')}
        values = defaultdict(set); valid = True; post_ft_packets=0
        for rec, p in versions:
            if time(p['receipt']['request_started_at']) < first_ft:
                rejected['STATISTICS_BEFORE_FT_KNOWLEDGE'] += 1;continue
            post_ft_packets+=1
            if {v['team']['id'] for v in p['data']['response']} != teams:
                valid = False;rejected['STATISTICS_TEAM_MISMATCH'] += 1;continue
            for row in p['data']['response']:
                for v in row['statistics']:
                    if v['type'] in LABELS.values():values[(row['team']['id'],v['type'])].add(v['value'])
        if any(len(v)>1 for v in values.values()):
            valid=False;rejected['STATISTICS_REVISION_CONFLICT'] += 1
        if not valid or not post_ft_packets:continue
        stat_ok.add(fid)
        for metric,label in LABELS.items():
            if all(len(values[(t,label)])==1 and None not in values[(t,label)] for t in teams):counts[metric] += 1
            else:nulls[metric] += 1
    ft=sum(v['fixture']['status']['short']=='FT' for v in fixtures.values())
    nulls={m:ft-counts[m] for m in LABELS}
    sources = _records(repo, SOURCE); qc = [r for r in _records(repo, QC) if r['adapter_hash']==ADAPTER]
    return {'schema': 'football-pipeline-coverage-v1', 'league': league, 'season': season,
            'as_of': at, 'expected_matches': len(expected[2]) if expected else None,
            'calendar_complete': expected is not None, 'calendar_attested': False,
            'temporal_source_views':temporal,
            'observed_matches': len(observations), 'qc_matches': len(fixtures),
            'rejected_matches': len(observations)-len(fixtures), 'reasons': dict(rejected),
            'confirmed_ft': sum(v['fixture']['status']['short']=='FT' for v in fixtures.values()),
            'statistics_qc_matches': len(stat_ok), 'statistics_qc_fixture_ids': sorted(stat_ok), 'statistics_complete_counts': counts,
            'statistics_missing_counts': nulls, 'fouls_semantics': 'NOT_VERIFIED',
            'source_packets': len(sources), 'qc_rejected_packets': sum(not v['accepted'] for v in qc),
            'pending_qc_packets':len({r['id'] for r in sources}-{r['source_id'] for r in qc}),
            'fixtures': fixtures, 'source_ids': sorted(bound), 'team_context_source_ids': sorted(contexts),
            'cohorts': {'TRAIN':0,'CALIBRATION':0,'HOLDOUT':0},
            'calibration_target':60, 'minimum_per_bin':Policy().min_calibration,
            'holdout_target':Policy().min_holdout, 'fit_allowed':False,
            'probability':None,'ev':None,'scores':{'brier':None,'log_loss':None,'ece':None},
            'decision':'PASS','small_markets':'SHADOW','stake':0,'monetary_permission':False}


def model_inputs(repo, fixture_id, *, as_of=None, profile, source_reliability):
    at = as_of or utcnow()
    if time(at)>time(utcnow()):raise ValueError('FUTURE_MODEL_CUTOFF')
    selected=packets(repo, at)
    fixture_packets=[p for _,p in selected if p['receipt']['endpoint']=='/fixtures']
    stats=[p for _,p in selected if p['receipt']['endpoint']=='/fixtures/statistics']
    with tempfile.TemporaryDirectory(prefix='sefirot-source-view-') as d:
        archive_packets(fixture_packets, d, at)
        main=export_sports(d, fixture_id, at, profile=profile, source_reliability=source_reliability)
    # Local availability is a second cutoff; a late import is never knowledge
    # available for a historical seal, even if its provider receipt is older.
    local=max((r['available_at'] for r,p in selected if p['receipt']['endpoint']=='/fixtures'),key=time)
    main['sports']['as_of']=max(main['sports']['as_of'],local,key=time)
    main['receipt']['sports_hash']=digest(main['sports'])
    main['receipt']['local_available_at']=local
    main['receipt']['pipeline_adapter_hash']=ADAPTER
    main['coverage']['sports_as_of']=main['sports']['as_of']
    main['coverage'].pop('hash',None);main['coverage']['hash']=digest(main['coverage'])
    small={}
    for metric in ('CORNERS','SHOTS','SOT','CARDS'):
        for side in ('home','away'):
            tid=next(v['teams'][side]['id'] for p in fixture_packets for v in p['data']['response'] if v['fixture']['id']==fixture_id)
            data={'schema':'small-market-input-v1','as_of':at,'fixture_id':fixture_id,'team_id':tid,
                  'profile':profile,'metric':metric,'fixture_packets':fixture_packets,'statistic_packets':stats}
            small[metric+':'+side]=review_small_market(data,at)
    return {'schema':'football-model-inputs-v1','adapter_hash':ADAPTER,'main':main,'small':small,
            'source_ids':[r['id'] for r,_ in selected], 'forecast_created':False,
            'probability':None,'ev':None,'fit_allowed':False,'decision':'PASS','stake':0,
            'fouls':{'status':'SHADOW','reason':'FOULS_SEMANTICS_NOT_VERIFIED'}}


def plan_day(repo, league=39, season=2026, *, at=None):
    stamp=at or utcnow();day=time(stamp).date().isoformat()
    view=league_view(repo,league,season,as_of=stamp)
    attempts=_records(repo,ATTEMPT)
    used=sum(time(r['at']).date().isoformat()==day for r in attempts)
    q=[]
    latest=packets(repo,stamp)
    full_today=any(p['receipt']['endpoint']=='/fixtures'
        and p['receipt']['parameters']=={'league':league,'season':season}
        and time(p['receipt']['received_at']).date().isoformat()==day for _,p in latest)
    if not full_today:q.append({'endpoint':'fixtures','params':{'league':league,'season':season}})
    known=set(view['statistics_qc_fixture_ids'])
    for fid,row in sorted(view['fixtures'].items(),key=lambda item:(time(item[1]['fixture']['date']),int(item[0]))):
        if row['fixture']['status']['short']=='FT' and int(fid) not in known:
            q.append({'endpoint':'fixtures/statistics','params':{'fixture':int(fid)}})
    # An uncertain transport/provider attempt is never automatically reconstructed
    # the following day. The intent exists even if its source/ACK never arrived.
    unresolved={digest(r['query']) for r in attempts if not any(p['receipt']['endpoint']=='/'+r['query']['endpoint']
        and p['receipt']['parameters']==r['query']['params']
        and time(p['receipt']['received_at'])>=time(r['at']) for _,p in latest)}
    q=[v for v in q if digest(v) not in unresolved]
    if view['pending_qc_packets'] or view['qc_rejected_packets']:q=[]
    return {'schema':'football-daily-plan-v1','day':day,'league':league,'season':season,
            'queries':q[:max(0,5-used)],'attempts_today':used,'daily_limit':5,
            'minute_limit':1,'reserve':5,'unresolved_attempts':len(unresolved),
            'pending_qc_packets':view['pending_qc_packets'],'rejected_qc_packets':view['qc_rejected_packets'],
            'budget_action':'NONE','automatic_retry':False,'execution_enabled':False}


def collect_day(repo, league=39, season=2026, *, execute=False, clock=None, collector=None, wait=None):
    """Explicit scheduled entrypoint; never arms the protected gateway budget.

    One query per existing probe, intent committed before I/O. Next invocation
    reuses saved sources; a crash after dispatch cannot silently refetch.
    """
    clock=clock or utcnow
    source_only(repo)
    if not execute:return plan_day(repo,league,season,at=clock())
    for record in _records(repo,SOURCE):
        ingest(repo,record['raw_utf8'].encode(),imported_at=clock(),origin=record['origin'])
    from scripts.chat_sports_probe import collect
    from time import sleep
    collector=collector or collect;wait=wait or sleep;results=[]
    for index in range(5):
        if index:wait(61)
        now=clock()
        with repo.transaction():
            plan=plan_day(repo,league,season,at=now)
            if not plan['queries']:break
            query=plan['queries'][0]
            intent={'schema':ATTEMPT,'id':'football-attempt:'+digest([plan['day'],query]),
                    'at':now,'query':query,'league':league,'season':season}
            if not _append(repo,intent):break
        def persist(packet):
            ingest(repo,canonical(packet).encode(),imported_at=clock(),origin='DAILY_PROBE')
        response=collector({'queries':[query]},packet_sink=persist)
        results.append(response)
        if not response.get('queries') or any(q['status']!='DONE' for q in response['queries']):break
    return {'schema':'football-daily-run-v1','responses':results,
            'plan':plan_day(repo,league,season,at=clock()),'decision':'PASS','stake':0}


def calibration_report(source_repo, prediction_repo, *, at=None):
    """Use the original fit gate; imported sources never become scored seals."""
    from scripts.calibration_fit_gate import assess
    stamp=at or utcnow()
    gate=assess(prediction_repo,Policy(),stamp)
    return {'schema':'football-calibration-preflight-v1',
            'source_packets':len(_records(source_repo,SOURCE)),
            'original_fit_gate':gate,'protocol_status':'DRAFT_NOT_REGISTERED',
            'sequence':['TRAIN','CALIBRATION','FROZEN_FIT','NEW_HOLDOUT','EVALUATION'],
            'minimum_per_bin':20,'calibration_target':60,'holdout_target':60,
            'source_import_assigns_no_cohort':True,'fit_allowed':False,
            'brier':None,'log_loss':None,'ece':None,'market_benchmark':None,
            'decision':'PASS','small_markets':'SHADOW','stake':0}


def sync_archive(repo, *, request=None, limit=1000):
    """Read existing private cloud archives only; never calls sports/provider API.

    Every run scans from the beginning: hash ordering is not chronological, so
    remembering the last hash would silently miss subsequently inserted packets.
    Existing raw hashes make re-import safe and leave first availability intact.
    """
    integer(limit,'sync limit',1,1000);source_only(repo)
    if request is None:
        from scripts.chat_store import request
    after='';added=0
    for _ in range(limit):
        row=request({'action':'source_export','after':after})
        if row.get('next') is None:return {'complete':True,'added_sources':added,'provider_requests':0}
        key=row.get('next');raw=row.get('raw_source')
        if (not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key) or key<=after
                or row.get('raw_sha256')!=key or not isinstance(raw,str)
                or sha256(raw.encode()).hexdigest()!=key):
            raise ValueError('SOURCE_EXPORT_BINDING_FAILED')
        result=ingest(repo,raw.encode())
        added+=int(result['added_source']);after=key
    return {'complete':False,'added_sources':added,'provider_requests':0,'reason':'SYNC_PAGE_LIMIT_RESCAN_REQUIRED'}
