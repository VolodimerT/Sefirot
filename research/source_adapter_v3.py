"""P0: primary archive/forward ledger -> typed V3 candidates, never model fit.

Local bytes and ledger bindings are checkable. Neither proves external origin;
training_rows remains empty until a separately reviewed attestation gate exists.
Canonical CORE and V3 model modules are not modified or imported for fitting.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3

from sefirot.contracts import Policy, digest, integer, time
from sefirot.football_provider import MAX_PROVIDER_ID, fixture_identity
from sefirot.football_query import FootballQueryError, validate_fixture_echo, fixture_query_row_reason
from sefirot.forward_scorecard import _forecast_valid
from sefirot.identity import model_code_hash
from sefirot.repository import Repository
from sefirot.sports_archive import validate_packet, export_sports
from research.prediction_edge_v3.models import Config, checked_rows

SCHEMA = 'edge-v31-source-adapter-v1'
ORIGIN = 'UNVERIFIED_EXTERNAL_ORIGIN'
FORWARD_SCHEMAS = {'api-forward-plan-v1', 'api-forward-capture-v1',
                   'api-forward-result-source-v1', 'api-forward-settlement-v1'}


class SourceError(ValueError):
    """Fixed public codes; never emit upstream payloads or exception text."""


def _has_prices(value):
    if isinstance(value, dict):
        return any(str(k).lower() in {'odds', 'bookmaker', 'bookmakers', 'price', 'prices', 'market', 'markets'}
                   or _has_prices(v) for k, v in value.items())
    return isinstance(value, list) and any(_has_prices(v) for v in value)


def _scan(directory):
    if directory is None:
        return [], [], ['ARCHIVE_NOT_SUPPLIED'], {}
    root = Path(directory)
    if not root.is_dir():
        return [], [], ['ARCHIVE_MISSING'], {}
    packets, reviews, blockers, inventory = [], [], [], {}
    for index, path in enumerate(sorted(root.glob('*.json'))):
        review = {'input_index': index, 'packet_hash': None, 'status': 'INVALID_PACKET'}
        try:
            raw = path.read_bytes()
            inventory[path.name] = sha256(raw).hexdigest()
            review['file_sha256'] = inventory[path.name]
            if not re.fullmatch(r'[a-f0-9]{64}\.json', path.name):
                raise SourceError('NONCANONICAL_ARCHIVE_FILENAME')
            review['packet_hash'] = path.stem
            packet = validate_packet(json.loads(raw))
            review['fixture_ids'] = [fixture_identity(r)['id'] for r in packet['data']['response']]
            review['response_rows'] = len(packet['data']['response'])
            if digest(packet) != path.stem:
                raise SourceError('ARCHIVE_HASH_MISMATCH')
            if _has_prices(packet['data']):
                raise SourceError('PRICE_CONTAMINATION')
            try:
                validate_fixture_echo(packet['data'], packet['receipt']['parameters'])
            except FootballQueryError as exc:
                raise SourceError(exc.code) from None
            for row in packet['data']['response']:
                try:
                    integer(row['league'].get('season'), 'source season', 1900, 2200)
                    integer(row['fixture'].get('timestamp'), 'kickoff timestamp', 0, MAX_PROVIDER_ID)
                except ValueError:
                    raise SourceError('SOURCE_SEASON_OR_KICKOFF_UNVERIFIABLE') from None
            review.update(status='LOCAL_PACKET_VALID', received_at=packet['receipt']['received_at'],
                          response_rows=len(packet['data']['response']))
            if path.read_bytes() != raw:
                raise SourceError('ARCHIVE_CHANGED_DURING_READ')
            packets.append(packet)
        except SourceError as exc:
            review['status'] = str(exc); blockers.append(str(exc))
        except (ValueError, KeyError, TypeError, OSError, OverflowError, RecursionError):
            review['status'] = 'ARCHIVE_SCHEMA_OR_INTEGRITY_FAILED'
            blockers.append(review['status'])
        reviews.append(review)
    if not reviews: blockers.append('ARCHIVE_EMPTY')
    return packets, reviews, sorted(set(blockers)), inventory


def _query_row(packet, row):
    p = packet['receipt']['parameters']
    # Bounded support: reject selectors whose completeness/order cannot be replayed.
    if set(p) - {'id','ids','date','league','season','team','from','to','status','timezone'}:
        return 'QUERY_PARAMETER_SEMANTICS_UNSUPPORTED'
    reason = fixture_query_row_reason(p, row)
    if reason:
        return reason
    # FT history must be exactly scoped by league+season or an explicit fixture id.
    if row['fixture']['status']['short']=='FT' and not ({'league','season'} <= p.keys() or 'id' in p or 'ids' in p):
        return 'HISTORY_QUERY_SCOPE_MISSING'
    return None


class _ReadOnlyLedger(Repository):
    def __init__(self, path):
        # immutable=1 avoids sidecar creation. Reject live WAL/journal inputs;
        # use an offline checkpointed snapshot, never silently ignore its WAL.
        self.path = Path(path)
        if not self.path.is_file(): raise SourceError('LEDGER_MISSING')
        if any(Path(str(self.path)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
            raise SourceError('LEDGER_REQUIRES_OFFLINE_SNAPSHOT')
        self.before = sha256(self.path.read_bytes()).hexdigest()
        self.db = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro&immutable=1', uri=True)
        self.db.row_factory = sqlite3.Row
        self._record_digests = {}; self._transaction_sequence = 0
        try:
            self.db.execute('PRAGMA query_only=ON')
            self.db.execute('BEGIN')
            if self.db.execute('PRAGMA user_version').fetchone()[0] != 2:
                raise SourceError('LEDGER_SCHEMA_UNSUPPORTED')
            if (self.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok'
                    or self.db.execute('PRAGMA foreign_key_check').fetchone() is not None or not self.verify()):
                raise SourceError('LEDGER_INTEGRITY_FAILED')
        except Exception:
            self.close(); raise

    def unchanged(self):
        return (sha256(self.path.read_bytes()).hexdigest() == self.before
                and not any(Path(str(self.path)+s).exists() for s in ('-wal','-shm','-journal')))


def _ledger(path, cutoff, packets, directory):
    info = {'status':'NOT_SUPPLIED','plans':0,'results':0,'captures':0,'issues':[],
            'result_bindings':{},'member_bindings':{},'capture_bindings':{},'assignments':{},
            'future_record_exclusions':[],'declared_fixture_ids':[],'profiles':{}}
    if path is None: return info
    repo = None
    try:
        repo = _ReadOnlyLedger(path)
        info['snapshot_sha256'] = repo.before
        logs = list(repo.db.execute("SELECT at,payload FROM audit_logs WHERE event='RECORD'"))
        bound = defaultdict(list)
        for log in logs:
            data = json.loads(log['payload'])
            if 'record_table' in data:
                bound[(data['record_table'],data['record_id'],data['record_hash'])].append(log['at'])
        for log in repo.db.execute("SELECT at,payload FROM audit_logs WHERE event='SPLIT_RESERVED'"):
            data = json.loads(log['payload'])
            bound[('split_assignments',data['match_id'],digest(data))].append(log['at'])
        def stored(table, mid, payload, at):
            if not any(time(t) <= time(at) for t in bound[(table,mid,digest(payload))]):
                raise SourceError('UNBOUND_LEDGER_RECORD')
        def records(table, identifier, timestamp):
            visible = []
            for saved in repo.db.execute(f'SELECT * FROM {table} ORDER BY id'):
                payload = json.loads(saved['payload'])
                if table=='jobs' and payload.get('schema') not in FORWARD_SCHEMAS: continue
                if saved['id']!=payload[identifier] or time(saved['at'])!=time(payload[timestamp]):
                    raise SourceError('LEDGER_COLUMN_MISMATCH')
                if time(saved['at'])>time(cutoff):
                    info['future_record_exclusions'].append({'table':table,'record_id':saved['id'],
                                                            'reason':'RECORD_AFTER_CUTOFF'})
                else: visible.append(payload)
            return visible
        jobs = records('jobs','id','at')
        for j in jobs:
            if j.get('schema') not in FORWARD_SCHEMAS: continue
            if j.get('id') != digest({k:v for k,v in j.items() if k!='id'}):
                raise SourceError('FORWARD_JOB_HASH_MISMATCH')
            stored('jobs',j['id'],j,j['at'])
        packet_map = {digest(p):p for p in packets}
        plans = {j['id']:j for j in jobs if j.get('schema')=='api-forward-plan-v1'}
        info['declared_fixture_ids'] = sorted({m['match']['id'] for p in plans.values() for m in p['members']})
        assignments = {a['match_id']:a for a in records('split_assignments','match_id','at')}
        predictions = {p['id']:p for p in records('predictions','id','sealed_at')}
        for mid,assignment in assignments.items():
            stored('split_assignments',mid,assignment,assignment['at'])
        info['assignments'] = assignments
        for plan in plans.values():
            if plan['model_hash'] != model_code_hash(): raise SourceError('PLAN_MODEL_MISMATCH')
            if plan['role'] not in ('CALIBRATION','HOLDOUT'): raise SourceError('PLAN_ROLE_INVALID')
            selected = packet_map.get(plan['selection_packet_hash'])
            if selected is None or selected['receipt'] != plan['selection_receipt']:
                raise SourceError('SELECTION_PACKET_MISSING_OR_MISMATCHED')
            if time(selected['receipt']['received_at']) > time(plan['at']): raise SourceError('FUTURE_PLAN_RECEIPT')
            selected_rows = {r['fixture']['id']:r for r in selected['data']['response']}
            for member in plan['members']:
                fid = member['fixture_id']; raw = selected_rows.get(fid)
                if raw is None: raise SourceError('PLAN_FIXTURE_MISMATCH')
                if _query_row(selected,raw): raise SourceError('SELECTION_QUERY_RESPONSE_MISMATCH')
                match = fixture_identity(raw); league = str(raw['league']['id'])
                profile = plan['profiles'].get(league)
                match['competition_profile'] = profile
                if (member['match'] != match or member['home_id'] != raw['teams']['home']['id']
                    or member['away_id'] != raw['teams']['away']['id'] or member['season'] != raw['league']['season']
                    or profile not in ('MEN','WOMEN','RESERVE','LOWER')
                    or raw['fixture']['status']['short']!='NS' or time(plan['at'])>=time(match['kickoff'])):
                    raise SourceError('PLAN_FIXTURE_MISMATCH')
                if league in info['profiles'] and info['profiles'][league]!=profile:
                    raise SourceError('PROFILE_LEDGER_CONFLICT')
                info['profiles'][league] = profile
                assignment = assignments.get(match['id'])
                if assignment != {'match_id':match['id'],'role':plan['role'],'at':plan['at']}:
                    raise SourceError('SPLIT_ASSIGNMENT_MISMATCH')
                stored('split_assignments',match['id'],assignment,plan['at'])
                if match['id'] in info['member_bindings']: raise SourceError('DUPLICATE_PLAN_FIXTURE')
                info['member_bindings'][match['id']] = {'plan_id':plan['id'],'member':member,'role':plan['role']}
        results = {r['match_id']:r for r in records('results','match_id','received_at')}
        if not plans:
            raise SourceError('LEDGER_EMPTY' if not jobs and not results and not predictions and not assignments else 'FORWARD_PLAN_MISSING')
        for job in jobs:
            if job['schema'] not in ('api-forward-result-source-v1','api-forward-settlement-v1'): continue
            if job['plan_id'] not in plans: raise SourceError('RESULT_PLAN_MISSING')
            packet = packet_map.get(job['packet_hash'])
            if (packet is None or packet['receipt']!=job['receipt']
                    or time(packet['receipt']['received_at'])>time(job['at'])):
                raise SourceError('RESULT_SOURCE_PACKET_MISMATCH')
            if job['schema']!='api-forward-result-source-v1': continue
            declared_ids = set()
            raw_rows = {fixture_identity(r)['id']:r for r in packet['data']['response']}
            for result in job['api_results']:
                mid = result['match_id']; binding = info['member_bindings'].get(mid)
                raw = raw_rows.get(mid)
                if mid in declared_ids: raise SourceError('DUPLICATE_SOURCE_RESULT')
                declared_ids.add(mid)
                if (binding is None or binding['plan_id']!=job['plan_id'] or raw is None
                        or _query_row(packet,raw) or raw['fixture']['status']['short']!='FT'):
                    raise SourceError('RESULT_FIXTURE_MISMATCH')
                member = binding['member']; match = fixture_identity(raw)
                if (match['league']!=member['match']['league'] or match['kickoff']!=member['match']['kickoff']
                        or raw['teams']['home']['id']!=member['home_id'] or raw['teams']['away']['id']!=member['away_id']
                        or raw['league']['season']!=member['season']):
                    raise SourceError('RESULT_FIXTURE_MISMATCH')
                if (result['status']!='FINISHED' or result['source']!='API_FOOTBALL_V3:'+job['packet_hash']
                        or (result['home_goals'],result['away_goals'])!=tuple(raw['score']['fulltime'][s] for s in ('home','away'))
                        or time(result['received_at'])!=time(packet['receipt']['received_at'])
                        or time(result['finished_at'])!=time(result['received_at'])):
                    raise SourceError('RESULT_SOURCE_PACKET_MISMATCH')
                if mid not in results:
                    info['issues'].append({'fixture_id':mid,'reason':'FORWARD_SOURCE_WITHOUT_STORED_RESULT'})
        for mid,result in results.items():
            stored('results',mid,result,result['received_at'])
            sources = [j for j in jobs if j.get('schema')=='api-forward-result-source-v1'
                       and result in j.get('api_results',[])]
            for job in sources:
                packet = packet_map.get(job['packet_hash'])
                if (packet is None or packet['receipt'] != job['receipt']
                    or result['source'] != 'API_FOOTBALL_V3:'+job['packet_hash']
                    or time(result['received_at']) != time(packet['receipt']['received_at'])
                    or time(result['received_at']) > time(job['at'])):
                    raise SourceError('RESULT_SOURCE_PACKET_MISMATCH')
                info['result_bindings'][mid] = {'result':result,'packet_hash':job['packet_hash']}
            if not sources:
                info['issues'].append({'fixture_id':mid,'reason':'RESULT_WITHOUT_FORWARD_SOURCE'})
        for job in jobs:
            if job.get('schema')!='api-forward-capture-v1': continue
            plan = plans.get(job['plan_id'])
            if plan is None: raise SourceError('CAPTURE_PLAN_MISSING')
            for attempt in job['attempts']:
                if attempt['status']!='SEALED_RESEARCH': continue
                prediction = predictions.get(attempt['prediction_id'])
                if prediction is None: raise SourceError('CAPTURE_PREDICTION_MISSING_AT_CUTOFF')
                mid = prediction['sports']['match']['id']; binding = info['member_bindings'].get(mid)
                if (binding is None or binding['plan_id']!=plan['id'] or attempt['match_id']!=mid):
                    raise SourceError('CAPTURE_FIXTURE_MISMATCH')
                columns = repo.db.execute('SELECT match_id,model_id FROM predictions WHERE id=?',(prediction['id'],)).fetchone()
                if columns['match_id']!=mid or columns['model_id']!=prediction['model_id']:
                    raise SourceError('LEDGER_COLUMN_MISMATCH')
                if sum(p['sports']['match']['id']==mid for p in predictions.values())!=1:
                    raise SourceError('MULTIPLE_OR_REVISED_FORECASTS')
                stored('predictions',prediction['id'],prediction,job['at'])
                if not _forecast_valid(prediction,plan,binding['member'],assignments[mid]):
                    raise SourceError('ORIGINAL_FORECAST_INVALID')
                if not time(plan['at']) <= time(attempt['at']) <= time(prediction['sealed_at']) <= time(job['at']):
                    raise SourceError('CAPTURE_CHRONOLOGY_MISMATCH')
                receipts = attempt['source_receipts']
                if (attempt['sports_hash']!=digest(prediction['sports']) or not receipts
                    or any(not any(p['receipt']==r for p in packets) or time(r['received_at'])>time(prediction['sealed_at']) for r in receipts)):
                    raise SourceError('CAPTURE_SOURCE_PACKET_MISMATCH')
                if plan['policy_hash'] != Policy().fingerprint: raise SourceError('POLICY_REPLAY_UNSUPPORTED')
                replay = export_sports(directory,binding['member']['fixture_id'],attempt['at'],
                                       profile=binding['member']['match']['competition_profile'],source_reliability=plan['source_reliability'])
                if (digest(replay['sports']) != digest(prediction['sports'])
                        or receipts!=replay['receipt']['source_receipts']):
                    raise SourceError('SPORTS_REPLAY_MISMATCH')
                info['capture_bindings'][mid] = prediction['id']
        if not repo.unchanged(): raise SourceError('LEDGER_CHANGED_DURING_READ')
        info.update(status='LOCAL_LEDGER_INTEGRITY_CHECKED',plans=len(plans),results=len(results),captures=len(info['capture_bindings']))
    except SourceError as exc:
        info['status'] = str(exc)
    except (ValueError, sqlite3.Error, KeyError, TypeError, OSError, AttributeError, IndexError, OverflowError):
        info['status'] = 'LEDGER_SCHEMA_OR_INTEGRITY_FAILED'
    finally:
        if repo is not None: repo.close()
    return info


def adapt_sources(*, archive=None, database=None, cutoff, league_id, season, profile):
    integer(league_id,'league id',1,MAX_PROVIDER_ID); integer(season,'season',1900,2200)
    time(cutoff)
    if profile not in ('MEN','WOMEN','RESERVE','LOWER'): raise ValueError('known explicit league profile required')
    packets, packet_reviews, blockers, inventory = _scan(archive)
    ledger = _ledger(database,cutoff,packets,archive)
    if ledger['status'] not in ('NOT_SUPPLIED','LOCAL_LEDGER_INTEGRITY_CHECKED'): blockers.append(ledger['status'])
    observations = defaultdict(list); future_packets = []
    for p in packets:
        ph = digest(p)
        if time(p['receipt']['received_at']) > time(cutoff):
            future_packets.append({'packet_hash':ph,'reason':'RECEIPT_AFTER_CUTOFF','fixture_ids':[fixture_identity(r)['id'] for r in p['data']['response']]})
            continue
        for raw in p['data']['response']: observations[fixture_identity(raw)['id']].append((p,raw))
    candidates, reviews, bridges = [], [], []
    ledger_issues = {r['fixture_id']:r['reason'] for r in ledger['issues']}
    for mid, entries in sorted(observations.items()):
        entries.sort(key=lambda v:(time(v[0]['receipt']['received_at']),digest(v[0])))
        first_packet, first = entries[0]; latest = entries[-1][1]
        reason = None
        identities = {(r['league']['id'],r['league'].get('season'),r['teams']['home']['id'],r['teams']['away']['id'],time(r['fixture']['date'])) for _,r in entries}
        simultaneous = defaultdict(set)
        for p,r in entries:
            simultaneous[time(p['receipt']['received_at'])].add(digest([r['fixture']['status']['short'],r.get('score')]))
        finals = [(p,r) for p,r in entries if r['fixture']['status']['short']=='FT']
        if len(identities)!=1: reason='FIXTURE_IDENTITY_OR_SEASON_CHANGED'
        elif any(len(values)>1 for values in simultaneous.values()): reason='SIMULTANEOUS_OBSERVATION_CONFLICT'
        elif any(_query_row(p,r) is not None for p,r in entries): reason=next(_query_row(p,r) for p,r in entries if _query_row(p,r))
        elif first['league']['id']!=league_id: reason='OTHER_LEAGUE'
        elif not 0<=season-first['league'].get('season',0)<=2: reason='OTHER_SEASON'
        elif not finals or latest['fixture']['status']['short']!='FT': reason='NOT_CURRENT_REGULATION_FT'
        elif len({digest(r['score']['fulltime']) for _,r in finals})!=1: reason='RESULT_REVISION_CONFLICT'
        else:
            first_packet,first = finals[0]
            if time(first_packet['receipt']['received_at']) < time(first['fixture']['date'])+timedelta(minutes=90): reason='PREMATURE_FT_RECEIPT'
            elif (time(cutoff)-time(first['fixture']['date'])).total_seconds()/86400>Config().history_days: reason='STALE_HISTORY'
        review = {'fixture_id':mid,'observations':len(entries),'status':reason or 'STRUCTURALLY_VALID_EXTERNAL_UNVERIFIED'}
        binding = ledger['member_bindings'].get(mid)
        frozen_profile = ledger['profiles'].get(str(first['league']['id']))
        if not reason and frozen_profile is not None and frozen_profile!=profile: reason='PROFILE_LEDGER_MISMATCH'
        assignment = ledger['assignments'].get(mid)
        if not reason and assignment and assignment['role']=='HOLDOUT': reason='HOLDOUT_NOT_TRAINABLE'
        if not reason and mid in ledger_issues: reason=ledger_issues[mid]
        if not reason and binding:
            member = binding['member']
            if member['match']['competition_profile']!=profile: reason='PROFILE_LEDGER_MISMATCH'
            elif binding['role']=='HOLDOUT': reason='HOLDOUT_NOT_TRAINABLE'
        result_binding = ledger['result_bindings'].get(mid)
        if not reason and result_binding:
            result = result_binding['result']; r = first['score']['fulltime']
            if (result['status']!='FINISHED' or (result['home_goals'],result['away_goals'])!=(r['home'],r['away'])
                or time(result['received_at'])!=time(first_packet['receipt']['received_at'])
                or time(result['finished_at'])!=time(result['received_at'])): reason='RESULT_LEDGER_MISMATCH_OR_NOT_FIRST_RECEIPT'
        if reason: review['status']=reason
        if not reason:
            receipt = first_packet['receipt']; ident = fixture_identity(first)
            row = {'id':ident['id'],'home':f"api-football:team:{first['teams']['home']['id']}",
                   'away':f"api-football:team:{first['teams']['away']['id']}",'league':ident['league'],
                   'competition_profile':profile,'season':first['league']['season'],'kickoff':ident['kickoff'],
                   'finished_at':receipt['received_at'],'received_at':receipt['received_at'],
                   'home_goals':first['score']['fulltime']['home'],'away_goals':first['score']['fulltime']['away'],
                   'source_id':'api-football','receipt_sha':digest(receipt),'synthetic':False}
            checked_rows([row],cutoff,ident['league'],profile,season,Config())
            candidates.append(row)
            bridges.append({'fixture_id':mid,'packet_hash':digest(first_packet),'receipt':receipt,
                            'raw_team_ids':{s:first['teams'][s]['id'] for s in ('home','away')},
                            'names_observed':{s:sorted({r['teams'][s]['name'] for _,r in entries}) for s in ('home','away')},
                            'ledger_result_bound':result_binding is not None,'original_capture_id':ledger['capture_bindings'].get(mid),
                            'profile_verification':'ORIGINAL_PLAN_OPERATOR_ASSERTION' if frozen_profile else 'CALLER_OPERATOR_ASSERTION',
                            'finished_at_semantics':'FIRST_FT_RECEIPT_UPPER_BOUND; EXACT_WHISTLE_UNKNOWN','source_verification':ORIGIN})
        reviews.append(review)
    for mid,binding in sorted(ledger['member_bindings'].items()):
        if mid not in observations:
            reviews.append({'fixture_id':mid,'observations':0,'status':'PLANNED_FIXTURE_WITHOUT_ELIGIBLE_ARCHIVE_DATA'})
    missing = set(ledger['declared_fixture_ids']) - observations.keys() - {r['fixture_id'] for r in reviews}
    for mid in sorted(missing):
        reviews.append({'fixture_id':mid,'observations':0,'status':'PLANNED_FIXTURE_WITHOUT_ELIGIBLE_ARCHIVE_DATA'})
    for issue in ledger['issues']:
        if issue['fixture_id'] not in observations: reviews.append({'fixture_id':issue['fixture_id'],'observations':0,'status':issue['reason']})
    reported = {r['fixture_id'] for r in reviews}
    for excluded in future_packets:
        for mid in excluded['fixture_ids']:
            if mid not in reported:
                reviews.append({'fixture_id':mid,'observations':0,'status':'RECEIPT_AFTER_CUTOFF'})
                reported.add(mid)
    if archive is not None and Path(archive).is_dir():
        try:
            current = {p.name:sha256(p.read_bytes()).hexdigest() for p in Path(archive).glob('*.json')}
            if current!=inventory: blockers.append('ARCHIVE_CHANGED_DURING_READ')
        except OSError: blockers.append('ARCHIVE_CHANGED_DURING_READ')
    if blockers:
        for review in reviews:
            if review['status']=='STRUCTURALLY_VALID_EXTERNAL_UNVERIFIED': review['status']='GLOBAL_INPUT_BLOCKER'
        candidates=[]; bridges=[]
    report = {'schema':SCHEMA,'status':'INSUFFICIENT_REAL_DATA','model_decision':'KEEP_SHADOW','cutoff':cutoff,
              'context':{'league_id':league_id,'profile':profile,'season':season},
              'source_verification':ORIGIN,'core_model_hash':model_code_hash(),
              'adapter_hash':sha256(Path(__file__).read_bytes()).hexdigest(),
              'packet_reviews':packet_reviews,'future_packet_exclusions':future_packets,
              'fixture_reviews':reviews,'reason_counts':dict(Counter(r['status'] for r in reviews)),
              'archive_manifest_hash':digest(inventory),
              'ledger':{k:v for k,v in ledger.items() if k not in ('result_bindings','member_bindings','capture_bindings','assignments')},
              'structurally_valid_matches':len(candidates),'externally_verified_matches':0,
              'candidate_rows':candidates,'source_bindings':bridges,'training_rows':[],
              'blockers':sorted(set(blockers+['EXTERNAL_ORIGIN_NOT_ATTESTED'])),
              'training_allowed':False,'models_fitted':False,'monetary_permission':False,
              'execution_enabled':False,'stake':0.,'network_requests':0,
              'limitations':['Local hashes/ledger are not provider signatures',
                            'Deleted archive observations cannot be detected',
                            'No training or HOLDOUT registration is performed']}
    report['hash']=digest(report)
    return report
