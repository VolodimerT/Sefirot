"""Predeclared API cohorts; collection is research, never money permission.

Plans and attempts are content-bound ledger records. All selected fixtures,
including missing data and missed windows, remain in the denominator.
"""
from copy import deepcopy
from collections import Counter

from .contracts import PROFILES, digest, integer, number, time
from .football_provider import MAX_PROVIDER_ID, fixture_identity
from .identity import code_hash, model_code_hash
from .markets import DEFAULT_POOL
from .sports_archive import export_sports, read_archive, validate_packet

SCHEMA = 'api-forward-plan-v1'


def _save(service, payload):
    record = {**payload, 'id': digest(payload)}
    with service.repo.transaction():
        if service.repo.insert('jobs', record['id'], record, at=record['at']):
            service.repo.record_log('jobs', record['id'], record['at'], record)
    return record


def _plan(service, plan_id, *, current=True):
    if not service.repo.verify():
        raise ValueError('journal integrity failed')
    plan = service.repo.get('jobs', plan_id)
    payload = dict(plan); signature = payload.pop('id', None)
    if plan.get('schema') != SCHEMA or signature != digest(payload):
        raise ValueError('forward plan identity mismatch')
    service._time(plan['at'])
    if current and (plan['code_hash'] != code_hash() or plan['model_hash'] != model_code_hash()
                    or plan['policy_hash'] != service.policy.fingerprint):
        raise ValueError('forward plan requires its frozen build and policy; do not relabel it')
    return plan


def create_plan(service, packet, profiles, *, role='CALIBRATION',
                source_reliability, calibrator_id=None):
    at = service.now()
    validate_packet(packet, at)
    if not service.repo.verify():
        raise ValueError('journal integrity failed')
    if service.policy.goal_model != 'BASELINE_V1':
        raise ValueError('forward collector currently supports BASELINE_V1 only')
    if role not in ('CALIBRATION', 'HOLDOUT'):
        raise ValueError('forward role must be CALIBRATION or HOLDOUT')
    number(source_reliability, 'operator source reliability', 0, 1)
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError('explicit API league/profile mapping required')
    for league, profile in profiles.items():
        integer(league, 'API league id', 1, MAX_PROVIDER_ID)
        if profile not in PROFILES or profile == 'UNKNOWN':
            raise ValueError('explicit competition profile required')
    fit = service.repo.get('calibrators', calibrator_id) if calibrator_id else None
    if role == 'CALIBRATION' and fit is not None:
        raise ValueError('calibration cohort must use raw predictions')
    if role == 'HOLDOUT':
        if fit is None:
            raise ValueError('freeze a calibrator before reserving HOLDOUT')
        artifact = dict(fit); signature = artifact.pop('hash', None)
        if (signature != digest(artifact) or fit['model_hash'] != model_code_hash()
                or fit['policy_hash'] != service.policy.fingerprint
                or fit.get('goal_model_hash') is not None or fit['synthetic']
                or time(fit['fit_at']) > time(at)):
            raise ValueError('compatible nonsynthetic frozen calibrator required')
    # Automatic production routes must not silently replace this study's fit.
    if service.repo.all('model_routes'):
        raise ValueError('use a dedicated research ledger without active model routes')
    members, excluded = [], Counter()
    for row in packet['data']['response']:
        league = row['league']['id']
        if league not in profiles:
            excluded['OUTSIDE_DECLARED_LEAGUES'] += 1; continue
        match = fixture_identity(row)
        if row['fixture']['status']['short'] != 'NS' or time(match['kickoff']) <= time(at):
            excluded['NOT_FUTURE_PREMATCH'] += 1; continue
        if any(v is not None for v in row.get('score', {}).get('fulltime', {}).values()):
            raise ValueError('future NS fixture already contains a result')
        if fit and match['id'] in fit['fit_ids']:
            raise ValueError('holdout fixture overlaps calibrator training')
        match['competition_profile'] = profiles[league]
        members.append({'fixture_id': row['fixture']['id'], 'match': match,
                        'home_id': row['teams']['home']['id'], 'away_id': row['teams']['away']['id'],
                        'season': row['league'].get('season')})
    members.sort(key=lambda m: (time(m['match']['kickoff']), m['fixture_id']))
    if not members:
        raise ValueError('no future fixtures in declared API leagues')
    plan = {'schema': SCHEMA, 'at': at, 'role': role, 'code_hash': code_hash(),
            'model_hash': model_code_hash(), 'policy_hash': service.policy.fingerprint,
            'calibrator_id': calibrator_id, 'markets': deepcopy(DEFAULT_POOL),
            'source_reliability': source_reliability,
            'profiles': {str(k): profiles[k] for k in sorted(profiles)},
            'members': members, 'selection_packet_hash': digest(packet),
            'selection_receipt': deepcopy(packet['receipt']), 'excluded_counts': dict(excluded),
            'selection': 'Every future NS fixture in the declared leagues of this API packet',
            'monetary_permission': False, 'execution_enabled': False}
    plan['id'] = digest(plan)
    # Reserve every member and the plan atomically, before the first forecast.
    with service.repo.transaction():
        assigned = {a['match_id'] for a in service.repo.all('split_assignments')}
        for member in members:
            mid = member['match']['id']
            if mid in assigned or service.repo.all('predictions', match_id=mid):
                raise ValueError('forward fixture already assigned or predicted')
            assignment = {'match_id': mid, 'role': role, 'at': at}
            service.repo.insert('split_assignments', mid, assignment, at=at)
            service.repo.record_log('split_assignments', mid, at, assignment)
        service.repo.insert('jobs', plan['id'], plan, at=at)
        service.repo.record_log('jobs', plan['id'], at, plan)
    return plan


def capture_plan(service, plan_id, archive):
    plan = _plan(service, plan_id)
    if service.repo.all('model_routes'):
        raise ValueError('research ledger gained an active model route')
    if not any(digest(p) == plan['selection_packet_hash'] for p in read_archive(archive)):
        raise ValueError('archive must contain the original selection API packet')
    prior_status = {r['match_id']: r['status'] for r in inspect_plan(service, plan_id)['fixtures']}
    if any(s == 'INVALID_OR_REVISED_SEAL' for s in prior_status.values()):
        raise ValueError('cohort contains an incompatible or revised forecast; review required')
    attempts = []
    for member in plan['members']:
        at = service.now(); mid = member['match']['id']
        prior = service.repo.all('predictions', match_id=mid)
        row = {'match_id': mid, 'at': at}
        if prior:
            row.update(status='ALREADY_SEALED', prediction_ids=[p['id'] for p in prior])
        elif time(at) >= time(member['match']['kickoff']):
            row.update(status='MISSED_PREMATCH_WINDOW')
        else:
            try:
                imported = export_sports(archive, member['fixture_id'], at,
                    profile=member['match']['competition_profile'],
                    source_reliability=plan['source_reliability'], policy=service.policy)
            except ValueError as exc:
                row.update(status='DATA_UNAVAILABLE', reason=str(exc))
            else:
                row.update(coverage=imported['coverage'], sports_hash=digest(imported['sports']),
                           source_receipts=imported['receipt']['source_receipts'])
                if imported['sports']['match'] != member['match']:
                    row.update(status='FIXTURE_CHANGED; NEW_PLAN_REQUIRED')
                elif not imported['coverage']['history_coverage_ready']:
                    row.update(status='INSUFFICIENT_HISTORY')
                elif 'TARGET_OBSERVATION_STALE' in imported['coverage']['blockers']:
                    row.update(status='STALE_TARGET_OBSERVATION')
                elif (plan['calibrator_id'] and time(service.repo.get('calibrators', plan['calibrator_id'])['fit_at'])
                      > time(imported['sports']['as_of'])):
                    row.update(status='CALIBRATOR_NEWER_THAN_SPORTS_DATA')
                else:
                    prediction = service.capture(imported['sports'], plan['markets'], plan['calibrator_id'])
                    row.update(status='SEALED_RESEARCH', prediction_id=prediction['id'],
                               sports_gates_passed=not imported['coverage']['blockers'])
        attempts.append(row)
    return _save(service, {'schema': 'api-forward-capture-v1', 'plan_id': plan_id,
        'at': service.now(), 'attempts': attempts, 'counts': dict(Counter(a['status'] for a in attempts)),
        'monetary_permission': False, 'execution_enabled': False})


def settle_plan(service, plan_id, packet):
    plan = _plan(service, plan_id)
    at = service.now(); validate_packet(packet, at)
    statuses_before = {r['match_id']: r['status'] for r in inspect_plan(service, plan_id)['fixtures']}
    if any(s == 'INVALID_OR_REVISED_SEAL' for s in statuses_before.values()):
        raise ValueError('cohort contains an incompatible or revised forecast; review required')
    observed = {r['fixture']['id']: r for r in packet['data']['response']}
    ready, statuses = [], []
    for member in plan['members']:
        mid = member['match']['id']; row = observed.get(member['fixture_id'])
        status = {'match_id': mid}
        if not service.repo.all('predictions', match_id=mid):
            status['status'] = 'NO_PREMATCH_SEAL'
        elif row is None or row['fixture']['status']['short'] != 'FT':
            status['status'] = 'AWAITING_REGULATION_FT'
        else:
            match = fixture_identity(row); match['competition_profile'] = member['match']['competition_profile']
            if (match != member['match'] or row['teams']['home']['id'] != member['home_id']
                    or row['teams']['away']['id'] != member['away_id']):
                raise ValueError('API result fixture identity differs from frozen plan')
            score = row['score']['fulltime']; received = packet['receipt']['received_at']
            if time(received) <= time(member['match']['kickoff']):
                raise ValueError('result observed before kickoff')
            existing = [r for r in service.repo.all('results') if r['match_id'] == mid]
            if existing:
                old = existing[0]
                if old['status'] != 'FINISHED' or (old['home_goals'], old['away_goals']) != (score['home'], score['away']):
                    raise ValueError('API result correction conflicts with immutable result; review required')
                if statuses_before[mid] == 'SETTLED_WITHOUT_FORWARD_API_RECEIPT':
                    raise ValueError('existing result lacks original forward API provenance; do not relabel it')
                status['status'] = 'ALREADY_SETTLED'
            else:
                result = {'match_id': mid, 'status': 'FINISHED', 'home_goals': score['home'],
                    'away_goals': score['away'], 'finished_at': received, 'received_at': received,
                    'source': 'API_FOOTBALL_V3:' + digest(packet)}
                ready.append(result); status['status'] = 'SETTLED_API_RESULT'
        statuses.append(status)
    # Validate the complete packet/cohort before settling any of its results.
    # Bind API provenance first: an interrupted batch can resume without
    # inventing a new receipt for a result already committed by Service.result.
    if ready:
        _save(service, {'schema': 'api-forward-result-source-v1', 'at': at, 'plan_id': plan_id,
            'packet_hash': digest(packet), 'receipt': deepcopy(packet['receipt']),
            'api_results': ready, 'monetary_permission': False, 'execution_enabled': False})
    for result in ready:
        service.result(result)
    return _save(service, {'schema': 'api-forward-settlement-v1', 'at': service.now(),
        'plan_id': plan_id, 'packet_hash': digest(packet), 'receipt': packet['receipt'],
        'results': statuses, 'monetary_permission': False, 'execution_enabled': False,
        'finished_at_semantics': 'FT receipt upper bound; exact final whistle unknown'})


def inspect_plan(service, plan_id):
    plan = _plan(service, plan_id, current=False)
    assignments = {a['match_id']: a for a in service.repo.all('split_assignments')}
    results = {r['match_id']: r for r in service.repo.all('results')}
    jobs = service.repo.all('jobs')
    api_sources = {}
    for job in jobs:
        if job.get('plan_id') == plan_id and job.get('schema') == 'api-forward-result-source-v1':
            for result in job['api_results']:
                api_sources.setdefault(result['match_id'], set()).add('API_FOOTBALL_V3:' + job['packet_hash'])
    rows = []
    for member in plan['members']:
        mid = member['match']['id']; predictions = service.repo.all('predictions', match_id=mid)
        assignment = assignments.get(mid, {})
        valid = [p for p in predictions if p['captured_prematch'] and not p['reconstructed']
            and not p['synthetic'] and p['parent'] is None and p['revision'] == 0
            and p['code_hash'] == plan['code_hash'] and p['model_hash'] == plan['model_hash']
            and p['policy_hash'] == plan['policy_hash'] and p['sports']['match'] == member['match']
            and p['market_pool'] == plan['markets']
            and (p['calibrator']['hash'] if p['calibrator'] else None) == plan['calibrator_id']
            and assignment.get('role') == plan['role'] and assignment.get('at') == plan['at']
            and time(plan['at']) <= time(p['sealed_at']) < time(member['match']['kickoff'])]
        result = results.get(mid)
        status = ('NO_SEAL' if not predictions else 'INVALID_OR_REVISED_SEAL' if len(predictions) != 1 or len(valid) != 1
                  else 'SETTLED' if result else 'AWAITING_RESULT')
        if status == 'NO_SEAL' and time(service.now()) >= time(member['match']['kickoff']):
            status = 'MISSED_PREMATCH_WINDOW'
        if status == 'SETTLED' and result['source'] not in api_sources.get(mid, set()):
            status = 'SETTLED_WITHOUT_FORWARD_API_RECEIPT'
        rows.append({'match_id': mid, 'kickoff': member['match']['kickoff'], 'status': status,
                     'prediction_ids': [p['id'] for p in predictions],
                     'result_source': result['source'] if result else None})
    attempts = [j for j in jobs if j.get('plan_id') == plan_id
                and j.get('schema') == 'api-forward-capture-v1']
    latest = max(attempts, key=lambda j: (time(j['at']), j['id'])) if attempts else None
    return {'schema': 'api-forward-status-v1', 'plan_id': plan_id, 'role': plan['role'],
        'at': service.now(), 'planned_fixtures': len(rows), 'fixtures': rows,
        'counts': dict(Counter(r['status'] for r in rows)),
        'last_capture_counts': latest['counts'] if latest else {},
        'same_current_build': plan['code_hash'] == code_hash(),
        'same_current_policy': plan['policy_hash'] == service.policy.fingerprint,
        'holdout_passed': False, 'monetary_permission': False, 'execution_enabled': False,
        'next_step': 'Freeze calibrator after CALIBRATION; reserve new unseen HOLDOUT fixtures; validate exact model',
        'limitations': ['Plan membership is not independent holdout success',
            'Fixtures within a league/date may be correlated; seven markets are not seven independent matches',
            'Local hashes bind recorded content, not a provider digital signature or external timestamp']}
