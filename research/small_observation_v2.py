"""Offline small-market identities, point-in-time revisions and league coverage.

Hashes are integrity references, NOT proof of provider origin. No source
attestation adapter is installed here; verified coverage and score metrics stay
null, fit/money remain disabled even for a structurally complete input archive.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import re

METRICS = ('CORNERS', 'SHOTS', 'SOT', 'FOULS_COMMITTED', 'YELLOW_CARDS',
           'RED_CARDS', 'SECOND_YELLOW', 'BOOKING_POINTS')
PERIODS = ('FT', '1H', '2H')
STATUSES = ('FT', 'VOID', 'PST', 'ABD', 'AET', 'PEN', 'NS', 'LIVE')
IDENTITY = ('provider', 'competition_id', 'season', 'competition_type')
FIXTURE_IDENTITY = ('fixture_id', 'home_id', 'away_id', 'kickoff', 'venue')
OBS_FIELDS = {'schema', *IDENTITY, *FIXTURE_IDENTITY, 'status', 'revision',
              'supersedes_sha256', 'published_at', 'received_at', 'available_at',
              'raw_sha256', 'source_kind', 'license_ref', 'metric_definitions',
              'counts', 'referee'}


def exact(value, fields, reason):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(reason)


def text(value, reason):
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise ValueError(reason)
    return value


def stamp(value):
    if not isinstance(value, str):
        raise ValueError('INVALID_TIMESTAMP')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('INVALID_TIMESTAMP') from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return result.astimezone(timezone.utc)


def sha(value, reason='INVALID_SHA256'):
    if not isinstance(value, str) or re.fullmatch('[a-f0-9]{64}', value) is None:
        raise ValueError(reason)


def record_hash(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def validate_fixture(row):
    exact(row, {*FIXTURE_IDENTITY, 'status'}, 'EXACT_MANIFEST_FIXTURE_FIELDS')
    for field in ('fixture_id', 'home_id', 'away_id'):
        text(row[field], 'INVALID_ID')
    if row['home_id'] == row['away_id']:
        raise ValueError('IDENTICAL_TEAMS')
    stamp(row['kickoff'])
    if row['venue'] not in ('HOME', 'NEUTRAL') or row['status'] not in STATUSES:
        raise ValueError('INVALID_VENUE_OR_STATUS')


def validate_manifest(m, at):
    exact(m, {'schema', *IDENTITY, 'registered_at', 'source_sha256',
              'pagination_complete', 'license_ref', 'team_ids', 'fixtures'},
          'EXACT_MANIFEST_FIELDS')
    if m['schema'] != 'small-league-manifest-v1' or m['competition_type'] != 'LEAGUE':
        raise ValueError('LEAGUE_MANIFEST_REQUIRED')
    for field in IDENTITY:
        text(m[field], 'INVALID_MANIFEST_IDENTITY')
    sha(m['source_sha256'])
    if type(m['pagination_complete']) is not bool:
        raise ValueError('BOOLEAN_PAGINATION_REQUIRED')
    if m['license_ref'] is not None:
        text(m['license_ref'], 'INVALID_LICENSE_REFERENCE')
    if stamp(m['registered_at']) > at:
        raise ValueError('FUTURE_MANIFEST_REGISTRATION')
    teams = m['team_ids']
    if (not isinstance(teams, list) or len(teams) > 1000
            or any(not isinstance(t, str) or not t.strip() or len(t)>300 for t in teams)
            or len(set(teams)) != len(teams)):
        raise ValueError('UNIQUE_TEAM_IDS_REQUIRED')
    if not isinstance(m['fixtures'], list) or len(m['fixtures']) > 10000:
        raise ValueError('BOUNDED_MANIFEST_FIXTURES_REQUIRED')
    assigned = {}
    for row in m['fixtures']:
        validate_fixture(row)
        if row['fixture_id'] in assigned:
            raise ValueError('DUPLICATE_MANIFEST_FIXTURE')
        if not {row['home_id'], row['away_id']} <= set(teams):
            raise ValueError('UNREGISTERED_TEAM')
        assigned[row['fixture_id']] = row
    return assigned


def validate_observation(o):
    exact(o, OBS_FIELDS, 'EXACT_OBSERVATION_FIELDS')
    if o['schema'] != 'small-match-observation-v2':
        raise ValueError('OBSERVATION_VERSION_MISMATCH')
    validate_fixture({k:o[k] for k in (*FIXTURE_IDENTITY,'status')})
    for field in IDENTITY:
        text(o[field], 'INVALID_OBSERVATION_IDENTITY')
    if type(o['revision']) is not int or not 0 <= o['revision'] <= 10000:
        raise ValueError('INVALID_REVISION')
    if o['revision'] == 0:
        if o['supersedes_sha256'] is not None:
            raise ValueError('INITIAL_REVISION_HAS_PARENT')
    else:
        sha(o['supersedes_sha256'], 'REVISION_PARENT_REQUIRED')
    sha(o['raw_sha256'])
    if o['source_kind'] not in ('SYNTHETIC', 'RETROSPECTIVE_IMPORT', 'ARCHIVE_UNATTESTED'):
        raise ValueError('SOURCE_KIND_UNATTESTED_ONLY')
    if o['license_ref'] is not None:
        text(o['license_ref'], 'INVALID_LICENSE_REFERENCE')
    published, received, available = (stamp(o[k]) for k in ('published_at','received_at','available_at'))
    if not stamp(o['kickoff']) < published <= received <= available:
        raise ValueError('SOURCE_CHRONOLOGY')
    exact(o['metric_definitions'], METRICS, 'EXACT_METRIC_DEFINITIONS_REQUIRED')
    for definition in o['metric_definitions'].values():
        if definition is not None:
            text(definition, 'INVALID_METRIC_DEFINITION')
    exact(o['counts'], PERIODS, 'EXPLICIT_PERIODS_REQUIRED')
    for p in PERIODS:
        exact(o['counts'][p], METRICS, 'EXPLICIT_NULLABLE_METRICS_REQUIRED')
        for m in METRICS:
            exact(o['counts'][p][m], ('home','away'), 'EXACT_COUNT_SIDES_REQUIRED')
            for n in o['counts'][p][m].values():
                if n is not None and (type(n) is not int or not 0 <= n <= 10000):
                    raise ValueError('INVALID_COUNT')
        for side in ('home','away'):
            shots, sot = (o['counts'][p][m][side] for m in ('SHOTS','SOT'))
            if shots is not None and sot is not None and sot > shots:
                raise ValueError('SOT_EXCEEDS_SHOTS')
    for m in METRICS:
        for side in ('home','away'):
            ft, h1, h2 = (o['counts'][p][m][side] for p in PERIODS)
            if ft is not None and any(n is not None and n > ft for n in (h1,h2)):
                raise ValueError('HALF_EXCEEDS_FT')
            if None not in (ft,h1,h2) and ft != h1+h2:
                raise ValueError('PERIOD_SUM_MISMATCH')
    ref=o['referee']
    if ref is not None:
        exact(ref, ('referee_id','competition_id','season','yc_per_game','yc_per_foul',
                    'sample_matches','available_at','raw_sha256'), 'EXACT_REFEREE_FIELDS')
        for field in ('referee_id','competition_id','season'):
            text(ref[field], 'INVALID_REFEREE_IDENTITY')
        if (ref['competition_id'],ref['season']) != (o['competition_id'],o['season']):
            raise ValueError('REFEREE_COMPETITION_MISMATCH')
        if type(ref['sample_matches']) is not int or ref['sample_matches'] <= 0:
            raise ValueError('REFEREE_SAMPLE_REQUIRED')
        for field in ('yc_per_game','yc_per_foul'):
            n=ref[field]
            if type(n) not in (int,float) or not math.isfinite(n) or n<0:
                raise ValueError('INVALID_REFEREE_STATISTIC')
        # A referee prior first available after kickoff cannot serve Referee Gate.
        if stamp(ref['available_at']) >= stamp(o['kickoff']):
            raise ValueError('REFEREE_PRIOR_POST_KICKOFF')
        sha(ref['raw_sha256'])
    return o


def validate_market(m):
    exact(m, ('schema','fixture_id','metric','period','kind','side','team_id','line',
              'settlement','bookmaker','market_id','rules_version','quote_at'),
          'EXACT_MARKET_FIELDS')
    if m['schema'] != 'small-market-contract-v1' or m['metric'] not in METRICS or m['period'] not in PERIODS:
        raise ValueError('UNSUPPORTED_METRIC_OR_PERIOD')
    for field in ('fixture_id','bookmaker','market_id','rules_version'):
        text(m[field], 'EXACT_MARKET_RULES_REQUIRED')
    stamp(m['quote_at'])
    kind=m['kind']
    if kind not in ('TOTAL','TEAM_TOTAL','HANDICAP','DOUBLE_CHANCE'):
        raise ValueError('UNSUPPORTED_MARKET_KIND')
    if kind=='TEAM_TOTAL':
        text(m['team_id'], 'TEAM_REQUIRED')
    elif m['team_id'] is not None:
        raise ValueError('UNEXPECTED_TEAM')
    if kind=='DOUBLE_CHANCE':
        if (m['metric']!='CORNERS' or m['side'] not in ('1X','12','X2')
                or m['line'] is not None or m['settlement']!='WIN_LOSS'):
            raise ValueError('CORNER_DOUBLE_CHANCE_CONTRACT_REQUIRED')
    else:
        n=m['line']
        if type(n) not in (int,float) or not math.isfinite(n) or abs(n)>10000:
            raise ValueError('FINITE_NUMERIC_LINE_REQUIRED')
        if kind in ('TOTAL','TEAM_TOTAL') and (n<0 or m['side'] not in ('OVER','UNDER')):
            raise ValueError('INVALID_TOTAL_CONTRACT')
        if kind=='HANDICAP' and m['side'] not in ('HOME','AWAY'):
            raise ValueError('INVALID_HANDICAP_SIDE')
        fraction=Decimal(str(n)) % 1
        fraction=abs(fraction)
        required={Decimal('0'):'ASIAN_INTEGER',Decimal('.5'):'ASIAN_HALF',
                  Decimal('.25'):'ASIAN_QUARTER',Decimal('.75'):'ASIAN_QUARTER'}.get(fraction)
        if required is None or m['settlement']!=required:
            raise ValueError('SETTLEMENT_LINE_MISMATCH')
    # Syntax validation only: this is neither a verified quote nor payoff model.
    return dict(m)


def audit_dataset(data, evaluated_at):
    """Return per-metric candidate coverage; never certify source or allow fit."""
    at=stamp(evaluated_at)
    exact(data, ('schema','manifest','observations'), 'EXACT_BATCH_FIELDS')
    if data['schema']!='small-observation-batch-v2':
        raise ValueError('BATCH_VERSION_MISMATCH')
    # Require canonical JSON-compatible input before producing a report hash.
    input_hash=record_hash(data)
    manifest=data['manifest'];assigned=validate_manifest(manifest,at)
    rows=data['observations']
    if not isinstance(rows,list) or len(rows)>20000:
        raise ValueError('BOUNDED_OBSERVATIONS_REQUIRED')
    quarantine=[];bad=set();excluded=Counter();duplicates=0;revisions=0
    groups=defaultdict(dict)
    for index,o in enumerate(rows):
        fid=o.get('fixture_id') if isinstance(o,dict) else None
        try:
            # Post-cutoff revisions must not change an earlier report, even if
            # they later contain inconsistent counts. They are audited later.
            if isinstance(o,dict) and 'available_at' in o and stamp(o['available_at'])>at:
                excluded['NOT_AVAILABLE_AT_CUTOFF']+=1
                continue
            validate_observation(o)
            if any(o[k]!=manifest[k] for k in IDENTITY):
                raise ValueError('MANIFEST_IDENTITY_MISMATCH')
            if fid not in assigned:
                raise ValueError('UNASSIGNED_FIXTURE')
            target=assigned[fid]
            if (any(o[k]!=target[k] for k in ('home_id','away_id','venue'))
                    or stamp(o['kickoff'])!=stamp(target['kickoff'])):
                raise ValueError('FIXTURE_IDENTITY_MISMATCH')
            if stamp(o['available_at'])>at:
                excluded['NOT_AVAILABLE_AT_CUTOFF']+=1
                continue
            key=record_hash(o);rev=o['revision']
            if rev in groups[fid]:
                if groups[fid][rev][0]==key:
                    duplicates+=1;continue
                raise ValueError('REVISION_CONFLICT')
            groups[fid][rev]=(key,o)
        except ValueError as error:
            quarantine.append({'row':index,'fixture_id':fid if isinstance(fid,str) else None,
                               'reason':str(error)})
            if isinstance(fid,str) and fid in assigned:
                bad.add(fid)
    selected={}
    for fid,versions in sorted(groups.items()):
        if fid in bad:continue
        ordered=sorted(versions)
        previous=None
        for rev in ordered:
            key,o=versions[rev]
            if ((previous is None and rev!=0) or
                    (previous is not None and (rev!=previous[1]['revision']+1
                     or o['supersedes_sha256']!=previous[0]))):
                quarantine.append({'fixture_id':fid,'reason':'REVISION_PARENT_MISSING'})
                bad.add(fid);break
            if previous is not None and (stamp(o['available_at'])<=stamp(previous[1]['available_at'])
                    or stamp(o['published_at'])<stamp(previous[1]['published_at'])
                    or stamp(o['received_at'])<stamp(previous[1]['received_at'])):
                quarantine.append({'fixture_id':fid,'reason':'REVISION_CHRONOLOGY'})
                bad.add(fid);break
            previous=(key,o)
        if fid not in bad:
            selected[fid]=previous[1];revisions+=len(ordered)-1
    eligible={fid:f for fid,f in assigned.items() if f['status']=='FT' and stamp(f['kickoff'])<at}
    for fid,f in assigned.items():
        if fid not in eligible:excluded['MANIFEST_'+f['status']]+=1
    for fid,o in list(selected.items()):
        if fid not in eligible or o['status']!='FT':
            excluded['NON_ELIGIBLE_OBSERVATION']+=1
            del selected[fid]
    markets=[]
    for metric in METRICS:
        definitions={o['metric_definitions'][metric] for o in selected.values()
                     if o['metric_definitions'][metric] is not None}
        for period in PERIODS:
            blockers={'SOURCE_ORIGIN_NOT_ATTESTED','RAW_RECEIPTS_NOT_BOUND',
                      'MANIFEST_COMPLETENESS_NOT_ATTESTED','SETTLEMENT_NOT_ATTESTED',
                      'NO_INDEPENDENT_HOLDOUT','SMALL_MARKET_MODEL_UNVALIDATED'}
            if not manifest['pagination_complete']:blockers.add('INCOMPLETE_PAGINATION')
            if manifest['license_ref'] is None: blockers.add('LICENSE_REFERENCE_MISSING')
            if not eligible:blockers.add('NO_ELIGIBLE_FIXTURES')
            if quarantine:blockers.add('SOURCE_QUARANTINE')
            if len(definitions)>1:blockers.add('METRIC_DEFINITION_CONFLICT')
            if not definitions or any(o['metric_definitions'][metric] is None for o in selected.values()):
                blockers.add('METRIC_DEFINITION_MISSING')
            known=[];teams={t:{'assigned':0,'observed':0,'home':0,'away':0} for t in manifest['team_ids']}
            referee_missing=[]
            for fid,f in eligible.items():
                for side in ('home','away'):teams[f[side+'_id']]['assigned']+=1
                o=selected.get(fid)
                if (o is None or len(definitions)!=1 or o['metric_definitions'][metric] is None
                        or any(n is None for n in o['counts'][period][metric].values())):continue
                known.append(fid)
                if o['license_ref'] is None:blockers.add('LICENSE_REFERENCE_MISSING')
                for side in ('home','away'):
                    t=teams[f[side+'_id']];t['observed']+=1;t[side]+=1
                if metric in ('YELLOW_CARDS','RED_CARDS','SECOND_YELLOW','BOOKING_POINTS'):
                    if o['referee'] is None:referee_missing.append(fid)
            if metric in ('YELLOW_CARDS','RED_CARDS','SECOND_YELLOW','BOOKING_POINTS'):
                blockers.add('REFEREE_ORIGIN_NOT_ATTESTED')
                if referee_missing or not known:blockers.add('REFEREE_EVIDENCE_MISSING')
            missing=sorted(set(eligible)-set(known))
            if missing:blockers.add('METRIC_COUNTS_MISSING')
            qc='RED' if quarantine or not eligible or not manifest['pagination_complete'] or len(definitions)>1 else 'AMBER'
            markets.append({'metric':metric,'period':period,'qc':qc,
                            'eligible_denominator':len(eligible),'known_fixtures':len(known),
                            'missing_fixtures':len(missing),'missing_fixture_ids':missing,
                            'observed_coverage':len(known)/len(eligible) if eligible else None,
                            'verified_coverage':None,'team_coverage':teams,
                            'referee_missing_fixture_ids':referee_missing,
                            'blockers':sorted(blockers),'fit_allowed':False,
                            'probability':None,'ev':None})
    result={'schema':'small-market-coverage-v2','status':'INSUFFICIENT_REAL_DATA',
            'evaluated_at':at.isoformat(),'identity':{k:manifest[k] for k in IDENTITY},
            'manifest_hash':record_hash(manifest),'input_hash':input_hash,
            'assigned_league_fixture_count':len(assigned),'eligible_unique_fixture_count':len(eligible),
            'observed_eligible_coverage':len(eligible)/len(assigned) if assigned else None,
            'source_kind_counts':dict(sorted(Counter(o['source_kind'] for o in selected.values()).items())),
            'duplicates':duplicates,'revisions':revisions,'excluded':dict(sorted(excluded.items())),
            'quarantine':quarantine,'markets':markets,'source_attested':False,
            'cohorts':{'TRAIN':0,'CALIBRATION':0,'HOLDOUT':0},
            'scores':{'brier':None,'log_loss':None,'ece':None,'clv':None},
            'fit_allowed':False,'monetary_permission':False,
            'next_action':'Bind licensed complete league raw receipts through an independently verified source adapter.'}
    result['report_hash']=record_hash(result)
    return result
