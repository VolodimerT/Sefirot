"""Observed API packets, deduplicated history and explicit pre-price data gaps.

This archive makes no network calls and never rewrites an observation. Its
hashes detect changed bytes, not fabricated receipts or deleted observations.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re

from .contracts import Policy, digest, integer, number, strict, text, time
from .evidence import eligible_history, inspect
from .football_provider import HOST, MAX_PROVIDER_ID, PARAMETERS, fixture_identity, normalize_sports


def validate_packet(packet, at=None):
    strict(packet, ('data', 'receipt'))
    receipt = packet['receipt']
    strict(receipt, ('provider_host', 'endpoint', 'parameters', 'request_started_at',
                     'received_at', 'payload_hash', 'http_status', 'provider', 'sports_only'), ('quota',))
    if (receipt['provider_host'] != HOST or receipt['endpoint'] != '/fixtures'
            or receipt['provider'] != 'API_FOOTBALL_V3' or receipt['sports_only'] is not True
            or receipt['http_status'] != 200):
        raise ValueError('successful sports-only API-Football fixture receipt required')
    started, received = time(receipt['request_started_at']), time(receipt['received_at'])
    if started > received or (at is not None and received > time(at)):
        raise ValueError('future or impossible API receipt chronology')
    if (not isinstance(receipt['parameters'], dict) or set(receipt['parameters']) - PARAMETERS['fixtures']
            or any(isinstance(v, bool) or not isinstance(v, (str, int)) for v in receipt['parameters'].values())):
        raise ValueError('API parameters required')
    data = packet['data']
    if not isinstance(data, dict) or digest(data) != receipt['payload_hash']:
        raise ValueError('API payload integrity mismatch')
    rows = data.get('response')
    if data.get('errors') not in ([], {}) or not isinstance(rows, list):
        raise ValueError('provider rejected request; HTTP 200 is not success')
    integer(data.get('results'), 'API result count')
    if data['results'] != len(rows):
        raise ValueError('API result count mismatch')
    paging = data.get('paging')
    if (not isinstance(paging, dict) or type(paging.get('current')) is not int or paging['current'] != 1
            or type(paging.get('total')) is not int or paging['total'] not in (0, 1)):
        raise ValueError('incomplete API pagination')
    seen = set()
    for row in rows:
        fixture_identity(row)
        fid = row['fixture']['id']
        if fid in seen:
            raise ValueError('duplicate fixture within API response')
        seen.add(fid)
        text(row['fixture']['status']['short'], 'fixture status')
        if row['fixture']['status']['short'] == 'FT':
            if time(row['fixture']['date']) >= received:
                raise ValueError('impossible FT observation chronology')
            for side in ('home', 'away'):
                integer(row.get('score', {}).get('fulltime', {}).get(side), 'regulation goals', 0, 50)
    return packet


def read_archive(directory, at=None):
    root = Path(directory)
    if not root.is_dir():
        raise ValueError('sports archive does not exist')
    packets = []
    for path in sorted(root.glob('*.json')):
        if not re.fullmatch(r'[a-f0-9]{64}\.json', path.name):
            raise ValueError('unexpected sports archive filename')
        packet = validate_packet(json.loads(path.read_text(encoding='utf-8')), at)
        if digest(packet) != path.stem:
            raise ValueError('sports archive packet integrity mismatch')
        packets.append(packet)
    return packets


def archive_packets(packets, directory, at):
    if not isinstance(packets, list) or not packets:
        raise ValueError('nonempty API packet batch required')
    # Validate the whole input and the existing archive before writing anything.
    unique = {digest(validate_packet(p, at)): p for p in packets}
    root = Path(directory)
    existing = {digest(p) for p in read_archive(root, at)} if root.exists() else set()
    root.mkdir(parents=True, exist_ok=True)
    added = []
    for key, packet in sorted(unique.items()):
        target = root / (key + '.json')
        if key in existing:
            continue
        try:
            with target.open('x', encoding='utf-8') as file:
                json.dump(packet, file, ensure_ascii=False, indent=2, allow_nan=False)
                file.write('\n')
        except FileExistsError:
            if digest(validate_packet(json.loads(target.read_text(encoding='utf-8')), at)) != key:
                raise ValueError('concurrent sports archive conflict') from None
        else:
            added.append(key)
    return {'schema': 'sports-archive-import-v1', 'at': at, 'status': 'OBSERVATIONS_ARCHIVED',
            'added_packets': len(added), 'existing_packets': len(existing),
            'input_unique_packets': len(unique), 'added_hashes': added,
            'network_requests': 0, 'monetary_permission': False, 'execution_enabled': False}


def _identity(row):
    return (row['league']['id'], row['teams']['home']['id'], row['teams']['away']['id'])


def export_sports(directory, fixture_id, as_of, *, profile, source_reliability, policy=None):
    integer(fixture_id, 'fixture id', 1, MAX_PROVIDER_ID)
    number(source_reliability, 'operator source reliability', 0, 1)
    policy = policy or Policy()
    cutoff = time(as_of)
    packets = read_archive(directory)
    packet_ids = {id(packet): digest(packet) for packet in packets}
    observations = defaultdict(list)
    for packet in packets:
        if time(packet['receipt']['received_at']) > cutoff:
            continue
        for row in packet['data']['response']:
            observations[row['fixture']['id']].append((packet, row))
    for rows in observations.values():
        rows.sort(key=lambda item: (time(item[0]['receipt']['received_at']), packet_ids[id(item[0])]))
    if fixture_id not in observations:
        raise ValueError('fixture not observed by archive cutoff')
    targets = observations[fixture_id]
    if len({_identity(row) for _, row in targets}) != 1:
        raise ValueError('target fixture identity conflict')
    # Conflicting observations at the same instant cannot be ordered by hash.
    latest_at = time(targets[-1][0]['receipt']['received_at'])
    simultaneous = [row for p, row in targets if time(p['receipt']['received_at']) == latest_at]
    if len({digest(row) for row in simultaneous}) != 1:
        raise ValueError('simultaneous target observations conflict')
    target_packet, target = targets[-1]
    imported = normalize_sports(target_packet, fixture_id, [], profile=profile,
                                source_reliability=source_reliability)
    if cutoff >= time(imported['sports']['match']['kickoff']):
        raise ValueError('archive export is no longer prematch')
    target_names = {target['teams'][side]['id']: target['teams'][side]['name']
                    for side in ('home', 'away')}
    chosen = {packet_ids[id(target_packet)]: target_packet['receipt']}
    history, exclusions, seasons = [], [], Counter()
    for fid, rows in sorted(observations.items()):
        if fid == fixture_id:
            continue
        latest_packet, latest = rows[-1]
        if latest['league']['id'] != target['league']['id']:
            continue
        reason = None
        finals = [(p, r) for p, r in rows if r['fixture']['status']['short'] == 'FT']
        simultaneous = [r for p, r in rows if time(p['receipt']['received_at']) == time(latest_packet['receipt']['received_at'])]
        if len({_identity(row) for _, row in rows}) != 1:
            reason = 'FIXTURE_IDENTITY_CONFLICT'
        elif len({digest(row) for row in simultaneous}) != 1:
            reason = 'SIMULTANEOUS_OBSERVATION_CONFLICT'
        elif latest['fixture']['status']['short'] != 'FT':
            reason = 'NOT_CURRENT_REGULATION_FT'
        elif len({digest([r['fixture']['date'], r['score']['fulltime']]) for _, r in finals}) != 1:
            reason = 'RESULT_REVISION_CONFLICT'
        if reason:
            exclusions.append({'fixture_id': fid, 'reason': reason})
            continue
        first_packet, first = finals[0]
        ident = fixture_identity(first)
        if any(first['teams'][side]['id'] not in target_names and
               first['teams'][side]['name'] in target_names.values() for side in ('home', 'away')):
            exclusions.append({'fixture_id': fid, 'reason': 'TEAM_NAME_COLLISION'})
            continue
        names = {side: target_names.get(first['teams'][side]['id'], first['teams'][side]['name'])
                 for side in ('home', 'away')}
        history.append({'id': ident['id'], 'home': names['home'], 'away': names['away'],
                        'league': ident['league'], 'kickoff': ident['kickoff'],
                        'finished_at': first_packet['receipt']['received_at'],
                        'received_at': first_packet['receipt']['received_at'],
                        'home_goals': first['score']['fulltime']['home'],
                        'away_goals': first['score']['fulltime']['away'],
                        'source_id': 'api-football', 'competition_profile': profile})
        seasons[str(first['league'].get('season', 'UNKNOWN'))] += 1
        for p in (first_packet, latest_packet):
            chosen[packet_ids[id(p)]] = p['receipt']
    sports = imported['sports']
    sports['history'] = history
    sports['as_of'] = max((r['received_at'] for r in chosen.values()), key=time)
    usable, rejected = eligible_history(sports, policy)
    witness = inspect(sports, policy)
    counts = {side: sum(sports['match'][side] in (r['home'], r['away']) for r in usable)
              for side in ('home', 'away')}
    blockers = {i['code'] for i in witness['issues'] if i['severity'] == 'BLOCK'}
    if min(counts.values()) < policy.min_team_games:
        blockers.add('INSUFFICIENT_HISTORY')
    if (cutoff - time(target_packet['receipt']['received_at'])).total_seconds() > policy.fact_max_age_minutes * 60:
        blockers.add('TARGET_OBSERVATION_STALE')
    receipt = {**imported['receipt'], 'sports_hash': digest(sports),
               'source_receipts': [chosen[key] for key in sorted(chosen)],
               'archive_cutoff': as_of, 'archive_packets': len(packets),
               'future_packets_excluded': sum(time(p['receipt']['received_at']) > cutoff for p in packets),
               'excluded_history': exclusions,
               'team_name_mapping': 'Target names joined by exact API team ID; no guessed aliases',
               'profile_scope': 'Explicit operator assertion for this API league, not automatic classification',
               'timestamp_semantics': {**imported['receipt']['timestamp_semantics'],
                    'history_received_at': 'First actual FT receipt; repeated snapshots never refresh first knowledge'},
               'monetary_permission': False, 'execution_enabled': False}
    coverage = {'schema': 'sports-coverage-v1', 'status': 'SPORTS_DATA_INCOMPLETE' if blockers else 'SPORTS_DATA_GATES_PASSED',
                'fixture_id': fixture_id, 'match': sports['match'], 'archive_cutoff': as_of,
                'sports_as_of': sports['as_of'], 'target_observed_at': target_packet['receipt']['received_at'],
                'history_rows': len(history), 'eligible_history_rows': len(usable),
                'excluded_by_policy': rejected, 'exclusion_reasons': dict(Counter(e['reason'] for e in exclusions)),
                'observed_history_seasons': dict(sorted(seasons.items())),
                'teams': {side: {'name': sports['match'][side], 'eligible_games': counts[side],
                                'games_needed': max(0, policy.min_team_games - counts[side])}
                          for side in ('home', 'away')},
                'required_team_games': policy.min_team_games, 'blockers': sorted(blockers),
                'history_coverage_ready': min(counts.values()) >= policy.min_team_games,
                'price_recheck_useful': not blockers, 'source_reliability': source_reliability,
                'policy_hash': policy.fingerprint, 'forecast_created': False,
                'monetary_permission': False, 'execution_enabled': False,
                'limitations': ['API receipt hashes are not provider signatures',
                    'Archive deletion or full receipt fabrication is not detected',
                    'Data coverage is not calibration, holdout or monetary admission']}
    coverage['hash'] = digest(coverage)
    return {'sports': deepcopy(sports), 'receipt': receipt, 'coverage': coverage}
