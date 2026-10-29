"""Offline evidence qualification, never a model fitter or dataset allocator.

Labels may become known after their own kickoff. Features/history may not.
Local integrity and structural candidacy never attest external origin or fit.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import sqlite3

from sefirot.contracts import digest, time
from sefirot.probability import CALIBRATION_SCHEMA
from sefirot.football_provider import fixture_identity
from research.day_calendar import calendar_day, day_window
from research.source_adapter_v3 import _scan, _ledger, _ReadOnlyLedger, SourceError, _query_row
from research.football_pipeline import packets as source_packets

MARKETS = ('1X2', 'DOUBLE_CHANCE', 'DNB', 'HANDICAP', 'TOTAL', 'BTTS', 'TEAM_TOTAL',
           'CORNERS', 'SHOTS', 'FOULS', 'YELLOW_CARDS')
REQUIRED = {'history': 'FIRST_AVAILABLE_REGULATION_FT_HISTORY_RECEIPTS',
            'statistics': 'EXACT_FIXTURE_TEAM_STATISTICS_RECEIPTS',
            'xg': 'DOCUMENTED_XG_PROVIDER_WITH_TIMESTAMP_AND_DEFINITION',
            'injuries': 'PREMATCH_FACT_INJURY_REPORT_WITH_ORIGIN',
            'lineups': 'PREMATCH_CONFIRMED_LINEUP_WITH_ORIGIN',
            'quotes': 'SEPARATE_EXACT_BOOKMAKER_EVENT_LINE_RULES_AND_QUOTE_RECEIPTS'}


def _snapshot(path, cutoff, packets, archive):
    state = {'status': 'NOT_SUPPLIED', 'source_records': [], 'predictions': [], 'assignments': {},
             'bindings': {}, 'snapshot_sha256': None, 'unchanged': None}
    if path is None:
        return state
    repo = None
    try:
        repo = _ReadOnlyLedger(path)
        state['snapshot_sha256'] = repo.before
        # Reuse the original forward-plan/receipt/assignment audit, not caller role flags.
        checked = _ledger(path, cutoff, packets, archive)
        if checked['status'] not in ('LOCAL_LEDGER_INTEGRITY_CHECKED', 'LEDGER_EMPTY'):
            raise SourceError('SNAPSHOT_BINDINGS_INVALID')
        state['forward_status'] = checked['status']
        state['assignments'] = checked['assignments']
        state['bindings'] = checked['capture_bindings']
        state['source_records'] = source_packets(repo, cutoff)
        state['predictions'] = repo.all('predictions', cutoff)
        state['status'] = 'VERIFIED_OFFLINE_SNAPSHOT'
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        state['status'] = 'SNAPSHOT_REJECTED'
        state['source_records'], state['predictions'], state['assignments'] = [], [], {}
    finally:
        if repo is not None:
            try:
                state['unchanged'] = repo.unchanged()
            except OSError:
                state['unchanged'] = False
            repo.close()
            if not state['unchanged']:
                state['status'] = 'SNAPSHOT_CHANGED_DURING_READ'
                state['source_records'], state['predictions'], state['assignments'] = [], [], {}
    return state


def _frozen_at_seal(calibrator, prediction):
    try:
        return (isinstance(calibrator, dict) and calibrator.get('synthetic') is False
                and calibrator.get('version')==CALIBRATION_SCHEMA
                and calibrator.get('hash')==digest({k:v for k,v in calibrator.items() if k!='hash'})
                and calibrator.get('model_hash')==prediction['model_hash']
                and calibrator.get('policy_hash')==prediction['policy_hash']
                and isinstance(calibrator.get('fit_ids'), list)
                and all(isinstance(v,str) for v in calibrator['fit_ids'])
                and time(calibrator['last_result_at']) <= time(calibrator['fit_at'])
                < time(prediction['sealed_at']))
    except (ValueError, KeyError, TypeError):
        return False


def _role_reviews(item, snapshot, cutoff):
    base = list(item['blockers'])
    if not item['prematch_observations']:
        base.append('NO_LOCALLY_AVAILABLE_PREMATCH_SNAPSHOT')
    if item['label_available_at'] is None:
        base.append('NO_FIRST_AVAILABLE_REGULATION_FT_LABEL')
    if item['synthetic_detected']:
        base.append('SYNTHETIC_RECORD_NOT_REAL_DATA')
    assignment = snapshot['assignments'].get(item['fixture_id'])
    predictions = [p for p in snapshot['predictions'] if p['sports']['match']['id']==item['fixture_id']]
    reviews = {}
    for role in ('TRAIN', 'CALIBRATION', 'HOLDOUT'):
        reasons = list(base)
        if role == 'TRAIN' and assignment is not None:
            reasons.append('RESERVED_ROLE_NOT_TRAINABLE')
        if role != 'TRAIN':
            if not assignment or assignment['role'] != role:
                reasons.append('PROSPECTIVE_ROLE_NOT_RESERVED')
            elif time(assignment['at']) >= time(item['kickoff']):
                reasons.append('ROLE_RESERVED_AFTER_KICKOFF')
            if not predictions or any(not p['captured_prematch'] or p['reconstructed']
                                      or time(p['sealed_at']) >= time(item['kickoff']) for p in predictions):
                reasons.append('ORIGINAL_PREMATCH_SEAL_REQUIRED')
            if assignment and any(time(assignment['at'])>=time(p['sealed_at']) for p in predictions):
                reasons.append('ROLE_RESERVED_AFTER_SEAL')
            if not snapshot['bindings'].get(item['fixture_id']):
                reasons.append('FORWARD_CAPTURE_BINDING_REQUIRED')
        if role == 'HOLDOUT':
            calibrators = [p.get('calibrator') for p in predictions]
            if not predictions or any(not _frozen_at_seal(p.get('calibrator'),p) for p in predictions):
                reasons.append('FROZEN_NONSYNTHETIC_CALIBRATION_REQUIRED')
            holdouts = {mid for mid,a in snapshot['assignments'].items() if a['role']=='HOLDOUT'}
            if any(isinstance(c,dict) and isinstance(c.get('fit_ids'),list)
                   and all(isinstance(v,str) for v in c['fit_ids']) and set(c['fit_ids']) & holdouts for c in calibrators):
                reasons.append('CALIBRATION_HOLDOUT_OVERLAP')
        reviews[role] = {'chronology_usable': not reasons, 'structurally_usable': not reasons, 'reasons': sorted(set(reasons)),
                         'qualified': False, 'admission_blockers': ['EXTERNAL_ORIGIN_NOT_ATTESTED',
                             'MODEL_FIT_NOT_AUTHORIZED'], 'model_fit_allowed': False}
    return reviews


def qualify_day(*, day, as_of, timezone='Europe/Kyiv', calendar=None, archive=None,
                snapshot=None, audit=None):
    cutoff = time(as_of)
    window = day_window(day, timezone)
    report = {'schema': 'day-bundle-qualification-v1', 'day_window': window, 'as_of': as_of,
        'decision': 'PASS', 'model_probability': None, 'ev': None, 'model_fit_allowed': False,
        'monetary_permission': False, 'execution_enabled': False, 'network_requests': 0,
        'artifacts_modified': 0, 'fixtures': [], 'day_fixture_ids': [], 'blockers': [],
        'audit': {'status': 'NOT_SUPPLIED'}, 'calendar_status': 'NOT_SUPPLIED',
        'data_label': 'SAVED_INPUTS_NOT_EXTERNALLY_ATTESTED', 'future_exclusions': [],
        'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest()}
    if audit is not None:
        try:
            report['audit'] = {'status': 'FILE_HASHED_NOT_REVIEW_AUTHORITY',
                               'sha256': sha256(Path(audit).read_bytes()).hexdigest()}
        except OSError:
            report['audit']['status'] = 'UNREADABLE'
    if report['audit']['status'] == 'NOT_SUPPLIED':
        report['blockers'].append('W1_AUDIT_NOT_SUPPLIED')
    calendar_rows = []
    if calendar is not None:
        try:
            calendar_rows = calendar_day(calendar, day, as_of, timezone)
            report['calendar_status'] = 'STRUCTURALLY_VALID_LOCAL_DAY'
            report['calendar_hash'] = digest(calendar)
        except (ValueError, KeyError, TypeError):
            report['calendar_status'] = 'REJECTED'
    if report['calendar_status'] != 'STRUCTURALLY_VALID_LOCAL_DAY':
        report['blockers'].append('VALID_DAY_CALENDAR_REQUIRED')
    packets, reviews, errors, inventory = _scan(archive)
    report['archive'] = {'packet_reviews': reviews, 'manifest_hash': digest(inventory), 'issues': errors}
    report['blockers'].extend(errors)
    snap = _snapshot(snapshot, as_of, packets, archive)
    report['snapshot'] = {k:snap[k] for k in ('status','snapshot_sha256','unchanged')}
    report['snapshot']['source_packet_count'] = len(snap['source_records'])
    report['snapshot']['forward_status'] = snap.get('forward_status', 'NOT_VERIFIED')
    if snap['status'] != 'VERIFIED_OFFLINE_SNAPSHOT':
        report['blockers'].append('CHECKPOINTED_SQLITE_SNAPSHOT_REQUIRED')
    # A source ledger provides first *local* knowledge. Receipt time alone does not.
    originals = {digest(p):(r,p) for r,p in snap['source_records']}
    observations = defaultdict(list)
    enrichment = defaultdict(list)
    for packet in packets:
        ph = digest(packet)
        binding = originals.get(ph)
        received = packet['receipt']['received_at']
        if time(received) > cutoff:
            report['future_exclusions'].append({'packet_hash':ph, 'reason':'RECEIPT_AFTER_AS_OF'})
            continue
        for raw in packet['data']['response']:
            mid = fixture_identity(raw)['id']
            observations[mid].append((packet,raw,binding[0]['available_at'] if binding else None))
    for record, packet in snap['source_records']:
        endpoint = packet['receipt']['endpoint'].lstrip('/')
        if endpoint == 'fixtures':
            for raw in packet['data']['response']:
                mid = fixture_identity(raw)['id']
                ph = digest(packet)
                if not any(digest(p)==ph for p,_,_ in observations[mid]):
                    observations[mid].append((packet,raw,record['available_at']))
        else:
            fid = packet['receipt']['parameters'].get('fixture')
            if fid is not None:
                enrichment[f'api-football:fixture:{fid}'].append((record,packet))
    for raw in calendar_rows:
        mid = fixture_identity(raw)['id']
        report['day_fixture_ids'].append(mid)
        if not any(digest(p)==digest(calendar) for p,_,_ in observations[mid]):
            binding = originals.get(digest(calendar))
            observations[mid].append((calendar,raw,binding[0]['available_at'] if binding else None))
    for mid, entries in sorted(observations.items()):
        entries.sort(key=lambda v:(time(v[0]['receipt']['received_at']),digest(v[0])))
        raw = entries[0][1]; identity = fixture_identity(raw); kickoff = time(identity['kickoff'])
        item = {'fixture_id':mid, 'provider_fixture_id':raw['fixture']['id'],
            'league_id':raw['league']['id'], 'season':raw['league'].get('season'),
            'team_ids':{s:raw['teams'][s]['id'] for s in ('home','away')},
            'names_observed':{s:sorted({r['teams'][s]['name'] for _,r,_ in entries}) for s in ('home','away')},
            'kickoff':identity['kickoff'], 'in_saved_day':mid in report['day_fixture_ids'],
            'blockers':[], 'observations':[], 'prematch_observations':[], 'label_available_at':None,
            'synthetic_detected':any(p['sports'].get('synthetic') is True for p in snap['predictions']
                                     if p['sports']['match']['id']==mid),
            'model_probability':None, 'ev':None, 'decision':'PASS'}
        identities = {(r['league']['id'],r['league'].get('season'),r['teams']['home']['id'],
                       r['teams']['away']['id'],time(r['fixture']['date'])) for _,r,_ in entries}
        if len(identities)!=1:
            item['blockers'].append('FIXTURE_IDENTITY_CONFLICT')
        item['blockers'].extend(sorted({reason for p,r,_ in entries if (reason:=_query_row(p,r))}))
        finals = []
        for packet,r,available in entries:
            receipt = packet['receipt']; state = r['fixture']['status']['short']
            obs = {'packet_hash':digest(packet),'receipt_hash':digest(receipt),
                   'source':receipt['provider'],'received_at':receipt['received_at'],
                   'locally_available_at':available,'state':state,
                   'feature_available_before_kickoff':bool(available and time(available)<kickoff
                       and time(receipt['received_at'])<kickoff and state=='NS')}
            item['observations'].append(obs)
            if obs['feature_available_before_kickoff']:
                item['prematch_observations'].append(obs['packet_hash'])
            if state=='FT' and available and time(receipt['received_at'])>=kickoff+timedelta(minutes=90):
                finals.append((available,digest(r['score']['fulltime'])))
        if len({h for _,h in finals})>1:
            item['blockers'].append('RESULT_REVISION_CONFLICT')
        elif finals:
            item['label_available_at'] = min((t for t,_ in finals),key=time)
        facts = [e for p in snap['predictions'] if p['sports']['match']['id']==mid
                 and snap['bindings'].get(mid)==p['id']
                 and p['captured_prematch'] and not p['reconstructed'] and time(p['sealed_at'])<kickoff
                 for e in p['sports']['evidence'] if e['kind']=='FACT'
                 and time(e['received_at'])<kickoff and time(e['received_at'])<=cutoff]
        pre_stats = [p for r,p in enrichment[mid] if time(r['available_at'])<kickoff]
        item['feature_coverage'] = {'history':False, 'statistics':bool(pre_stats),
            'xg':False, 'injuries':any(e['key']=='injuries' for e in facts),
            'lineups':any(e['key']=='lineup' for e in facts), 'quotes':False}
        # Unknown metric definitions and caller-declared odds are not source proof.
        item['missing_sources'] = [v for k,v in REQUIRED.items() if not item['feature_coverage'][k]]
        item['roles'] = _role_reviews(item,snap,cutoff)
        report['fixtures'].append(item)
    for item in report['fixtures']:
        history = [f['fixture_id'] for f in report['fixtures'] if f['fixture_id']!=item['fixture_id']
                   and f['league_id']==item['league_id'] and f['label_available_at'] and not f['blockers'] and not f['synthetic_detected']
                   and time(f['label_available_at'])<time(item['kickoff'])
                   and set(f['team_ids'].values()) & set(item['team_ids'].values())]
        item['pre_kickoff_history_fixture_ids'] = sorted(history)
        item['feature_coverage']['history'] = bool(history)
        metric_sources = []
        for prior in history:
            for rec,p in enrichment[prior]:
                if (p['receipt']['endpoint'].lstrip('/')=='fixtures/statistics'
                        and time(rec['available_at'])<time(item['kickoff'])):
                    metric_sources.append({'fixture_id':prior,'packet_hash':digest(p),
                        'available_at':rec['available_at'],
                        'metrics':sorted({v['type'] for team in p['data']['response']
                            for v in team.get('statistics',[]) if v.get('value') is not None})})
        item['historical_statistic_sources'] = metric_sources
        item['feature_coverage']['statistics'] = bool(metric_sources)
        item['feature_coverage']['xg'] = any(set(p['metrics']) & {'Expected Goals','expected_goals'}
                                           for p in metric_sources)
        item['missing_sources'] = [v for k,v in REQUIRED.items() if not item['feature_coverage'][k]]
        for review in item['roles'].values():
            review['reasons'] = sorted(set(review['reasons'] + [v for k,v in REQUIRED.items() if k!='quotes' and not item['feature_coverage'][k]]))
            review['structurally_usable'] = not review['reasons'] and not report['blockers']
    report['day_fixture_count'] = (len(report['day_fixture_ids'])
        if report['calendar_status']=='STRUCTURALLY_VALID_LOCAL_DAY' else None)
    report['coverage_by_league'] = {str(league):{'fixtures':sum(f['league_id']==league for f in report['fixtures']),
        'saved_day_fixtures':sum(f['league_id']==league and f['in_saved_day'] for f in report['fixtures'])}
        for league in sorted({f['league_id'] for f in report['fixtures']})}
    count_metrics = {'CORNERS': 'Corner Kicks', 'SHOTS': 'Total Shots',
                     'FOULS': 'Fouls', 'YELLOW_CARDS': 'Yellow Cards'}
    day_rows = [f for f in report['fixtures'] if f['in_saved_day']]
    report['coverage_by_market'] = {}
    for market in MARKETS:
        local = sum(any(count_metrics[market] in p['metrics'] for p in f['historical_statistic_sources'])
                    if market in count_metrics else f['feature_coverage']['history'] for f in day_rows)
        report['coverage_by_market'][market] = {'saved_day_fixtures':report['day_fixture_count'],
            'fixtures_with_local_sports_inputs':local if report['day_fixture_count'] is not None else None, 'fixtures_with_verified_quotes':0,
            'qualified':0,'decision':'PASS','model_probability':None,'ev':None,
            'referee_gate_required':market=='YELLOW_CARDS',
            'required_sources':(['DIRECT_COMMITTED_AND_SUFFERED_FOUL_COUNTS'] if market=='FOULS' else
                ['INDEPENDENT_REFEREE_YC_HISTORY_AND_CALIBRATION'] if market=='YELLOW_CARDS' else
                ['EXACT_MARKET_DATA_AND_INDEPENDENT_CALIBRATION'])}
    report['missing_sources'] = sorted({s for f in report['fixtures'] for s in f['missing_sources']}) or list(REQUIRED.values())
    report['blockers'] = sorted(set(report['blockers']+['EXTERNAL_ORIGIN_NOT_ATTESTED','MODEL_FIT_NOT_AUTHORIZED']))
    if archive is not None:
        try:
            current = {p.name:sha256(p.read_bytes()).hexdigest() for p in Path(archive).glob('*.json')}
        except OSError:
            current = None
        if current!=inventory:
            report['blockers'].append('ARCHIVE_CHANGED_DURING_READ')
            for item in report['fixtures']:
                for role in item['roles'].values():
                    role['structurally_usable'] = False
                    role['reasons'].append('ARCHIVE_CHANGED_DURING_READ')
    report['next_blocker'] = ('SUPPLY_REAL_DAY_ARCHIVE_AND_CHECKPOINTED_SQLITE'
        if report['calendar_status']!='STRUCTURALLY_VALID_LOCAL_DAY' or errors
        or snap['status']!='VERIFIED_OFFLINE_SNAPSHOT' else 'INDEPENDENT_SOURCE_ORIGIN_ATTESTATION')
    report['role_summary'] = {role:{'chronology_usable':sum(f['roles'][role]['chronology_usable'] for f in report['fixtures']),
        'structurally_usable':sum(f['roles'][role]['structurally_usable'] for f in report['fixtures']),
        'qualified':0} for role in ('TRAIN','CALIBRATION','HOLDOUT')}
    report['qualification_status'] = ('INPUTS_MISSING_OR_REJECTED'
        if report['next_blocker']=='SUPPLY_REAL_DAY_ARCHIVE_AND_CHECKPOINTED_SQLITE' else 'EVIDENCE_BLOCKED')
    report['hash'] = digest(report)
    return report
