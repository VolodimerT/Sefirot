"""API-only statistic coverage and long/recent diagnostics; no probability model."""
from collections import Counter, defaultdict
from statistics import mean

from .contracts import PROFILES, digest, integer, strict, time
from .football_provider import HOST, MAX_PROVIDER_ID, PARAMETERS
from .sports_archive import validate_packet

METRICS = {'SHOTS': 'Total Shots', 'SOT': 'Shots on Goal', 'CORNERS': 'Corner Kicks',
           'FOULS': 'Fouls', 'CARDS': 'Yellow Cards'}
METHOD = {'schema': 'small-statistics-diagnostic-v1', 'recent_games': 3,
          'long_games_max': 20, 'long_games_min': 10, 'history_days': 730,
          'shrink_rule': 'recent mean weight = recent_n / (long_n + recent_n)',
          'status': 'FIXED_RESEARCH_DIAGNOSTICS_NOT_FITTED'}


def validate_statistics_packet(packet):
    strict(packet, ('data', 'receipt'))
    r = packet['receipt']
    strict(r, ('provider_host', 'endpoint', 'parameters', 'request_started_at', 'received_at',
               'payload_hash', 'http_status', 'provider', 'sports_only'), ('quota',))
    if (r['provider_host'] != HOST or r['endpoint'] != '/fixtures/statistics' or
            r['provider'] != 'API_FOOTBALL_V3' or r['http_status'] != 200 or r['sports_only'] is not True):
        raise ValueError('successful sports-only API statistics receipt required')
    if time(r['request_started_at']) > time(r['received_at']): raise ValueError('impossible statistics chronology')
    params = r['parameters']
    if (not isinstance(params, dict) or set(params) - PARAMETERS['fixtures/statistics'] or
            any(isinstance(v, bool) or not isinstance(v, (str, int)) for v in params.values())):
        raise ValueError('statistics API parameters required')
    # A half or live snapshot cannot stand in for a regulation FT count.
    if 'half' in params: raise ValueError('half statistics unsupported; full fixture counts required')
    fid = _id(params.get('fixture'), 'statistics fixture id')
    if 'team' in params: _id(params['team'], 'statistics filter team id')
    data = packet['data']
    if not isinstance(data, dict) or digest(data) != r['payload_hash']: raise ValueError('statistics payload integrity mismatch')
    if (data.get('get') != 'fixtures/statistics' or not isinstance(data.get('parameters'), dict) or
            {k: str(v) for k, v in data['parameters'].items()} != {k: str(v) for k, v in params.items()}):
        raise ValueError('statistics payload query differs from receipt')
    rows = data.get('response')
    if data.get('errors') not in ([], {}) or not isinstance(rows, list): raise ValueError('provider statistics request rejected')
    integer(data.get('results'), 'statistics count', 0, 2)
    if data['results'] != len(rows): raise ValueError('statistics result count mismatch')
    paging = data.get('paging', {})
    if type(paging.get('current')) is not int or paging['current'] != 1 or type(paging.get('total')) is not int or paging['total'] not in (0, 1):
        raise ValueError('incomplete statistics pagination')
    seen = set()
    for row in rows:
        tid = integer(row.get('team', {}).get('id'), 'statistics team id', 1, MAX_PROVIDER_ID)
        if tid in seen: raise ValueError('duplicate statistics team')
        seen.add(tid)
        if 'team' in params and tid != _id(params['team'], 'filter team'): raise ValueError('statistics filter/team mismatch')
        values = row.get('statistics')
        if not isinstance(values, list) or len(values) > 100: raise ValueError('bounded statistics list required')
        types = [v.get('type') for v in values if isinstance(v, dict)]
        if len(types) != len(values) or any(not isinstance(t, str) or not t for t in types) or len(set(types)) != len(types):
            raise ValueError('unique statistics types required')
        if 'type' in params and any(t != params['type'] for t in types): raise ValueError('statistics type filter mismatch')
        for value in values:
            if value['type'] in METRICS.values() and value.get('value') is not None:
                integer(value['value'], 'full-time statistic count', 0, 10000)
    return fid


def _id(value, name):
    if isinstance(value, str) and value.isascii() and value.isdigit(): value = int(value)
    return integer(value, name, 1, MAX_PROVIDER_ID)


def review_small_market(dataset, at):
    strict(dataset, ('schema', 'as_of', 'fixture_id', 'team_id', 'profile', 'metric', 'fixture_packets', 'statistic_packets'))
    if dataset['schema'] != 'small-market-input-v1': raise ValueError('small-market API input schema required')
    if dataset['profile'] not in PROFILES or dataset['profile'] == 'UNKNOWN': raise ValueError('explicit competition profile required')
    if dataset['metric'] not in METRICS: raise ValueError('supported statistic metric required')
    cutoff = time(dataset['as_of'])
    if cutoff > time(at): raise ValueError('future small-market cutoff')
    fid = integer(dataset['fixture_id'], 'target fixture id', 1, MAX_PROVIDER_ID)
    tid = integer(dataset['team_id'], 'target team id', 1, MAX_PROVIDER_ID)
    for field in ('fixture_packets', 'statistic_packets'):
        if not isinstance(dataset[field], list) or len(dataset[field]) > 1000: raise ValueError('bounded API packets required')
    fixtures, statistics = defaultdict(list), defaultdict(list)
    future_packets = 0
    for packet in dataset['fixture_packets']:
        validate_packet(packet)
        if time(packet['receipt']['received_at']) > cutoff: future_packets += 1; continue
        for row in packet['data']['response']: fixtures[row['fixture']['id']].append((packet, row))
    for packet in dataset['statistic_packets']:
        sfid = validate_statistics_packet(packet)
        if time(packet['receipt']['received_at']) > cutoff: future_packets += 1; continue
        statistics[sfid].append(packet)
    if fid not in fixtures: raise ValueError('target fixture missing at cutoff')
    identity = lambda r: (r['league']['id'], r['teams']['home']['id'], r['teams']['away']['id'], time(r['fixture']['date']))
    targets = fixtures[fid]
    if len({identity(r) for _, r in targets}) != 1: raise ValueError('target fixture identity conflict')
    latest = max(time(p['receipt']['received_at']) for p, _ in targets)
    target_rows = [r for p, r in targets if time(p['receipt']['received_at']) == latest]
    if len({digest(r) for r in target_rows}) != 1: raise ValueError('simultaneous target conflict')
    target = target_rows[0]
    if target['fixture']['status']['short'] != 'NS' or cutoff >= time(target['fixture']['date']): raise ValueError('small-market target must be prematch')
    if tid not in (target['teams']['home']['id'], target['teams']['away']['id']): raise ValueError('team not in target fixture')
    metric = METRICS[dataset['metric']]
    opponent = next(target['teams'][side]['id'] for side in ('home', 'away') if target['teams'][side]['id'] != tid)
    observations, excluded = _observations(fixtures, statistics, target, fid, tid, metric, cutoff)
    opponent_rows, opponent_excluded = _observations(fixtures, statistics, target, fid, opponent, metric, cutoff)
    allowed_rows = [r for r in opponent_rows if r['opponent_count'] is not None]
    opponent_recent = allowed_rows[-METHOD['recent_games']:]
    opponent_long = allowed_rows[:-len(opponent_recent)][-METHOD['long_games_max']:] if opponent_recent else []
    opponent_allowed = {
        'team_id': opponent, 'long_games': len(opponent_long), 'recent_games': len(opponent_recent),
        'long_fixture_ids': [r['fixture_id'] for r in opponent_long],
        'recent_fixture_ids': [r['fixture_id'] for r in opponent_recent],
        'long_mean': mean(r['opponent_count'] for r in opponent_long) if opponent_long else None,
        'recent_mean': mean(r['opponent_count'] for r in opponent_recent) if opponent_recent else None,
        'exclusion_reasons': dict(sorted(opponent_excluded.items())),
        'missing_other_team_count': len(opponent_rows)-len(allowed_rows),
        'sufficient_long_baseline': len(opponent_long) >= METHOD['long_games_min']}
    # Last three are a modifier, not part of the independent longer baseline.
    recent = observations[-METHOD['recent_games']:]
    long = observations[:-len(recent)][-METHOD['long_games_max']:] if recent else []
    long_mean = mean(r['count'] for r in long) if long else None
    recent_mean = mean(r['count'] for r in recent) if recent else None
    weight = len(recent) / (len(long) + len(recent)) if long else None
    shrink = long_mean * (1-weight) + recent_mean * weight if weight is not None else None
    largest = max(long, key=lambda r: (r['count'], time(r['kickoff']), r['fixture_id']), default=None)
    without = [r for r in long if r != largest]
    venue = 'HOME' if target['teams']['home']['id'] == tid else 'AWAY'
    venue_long = [r for r in long if r['venue'] == venue]
    blockers = ['SMALL_MARKET_MODEL_UNVALIDATED', 'NO_API_PRICE_COMPARISON']
    if not opponent_allowed['sufficient_long_baseline']: blockers.append('OPPONENT_ALLOWED_BASELINE_INSUFFICIENT')
    if len(long) < METHOD['long_games_min']: blockers.append('LONG_BASELINE_INSUFFICIENT')
    if len(recent) < METHOD['recent_games']: blockers.append('RECENT_MODIFIER_INSUFFICIENT')
    if len(venue_long) < METHOD['long_games_min']: blockers.append('SAME_VENUE_BASELINE_INSUFFICIENT')
    if dataset['metric'] == 'CARDS': blockers.append('REFEREE_GATE_UNSUPPORTED')
    output = {'schema': 'small-market-review-v1', 'at': at, 'as_of': dataset['as_of'],
              'dataset_hash': digest(dataset), 'fixture_id': fid, 'team_id': tid, 'opponent_id': opponent,
              'profile': dataset['profile'], 'profile_provenance': 'OPERATOR_ASSERTION_SAME_LEAGUE_NOT_INDEPENDENT_VERIFICATION',
              'metric': dataset['metric'], 'provider_type': metric, 'method': dict(METHOD),
              'eligible_games': len(observations), 'future_packets_excluded': future_packets,
              'exclusion_reasons': dict(sorted(excluded.items())),
              'long_fixture_ids': [r['fixture_id'] for r in long], 'recent_fixture_ids': [r['fixture_id'] for r in recent],
              'long_mean': long_mean, 'recent_mean': recent_mean, 'recent_weight': weight,
              'shrunk_recent_mean': shrink, 'mean_without_largest_long': mean(r['count'] for r in without) if without else None,
              'largest_long_fixture_id': largest['fixture_id'] if largest else None,
              'same_venue_long_games': len(venue_long), 'same_venue_long_mean': mean(r['count'] for r in venue_long) if venue_long else None,
              'opponent_allowed_baseline': opponent_allowed,
              'observations': observations, 'blockers': sorted(blockers),
              'status': 'INSUFFICIENT_BASELINE' if len(long) < METHOD['long_games_min'] else 'DESCRIPTIVE_RESEARCH_ONLY',
              'probability': None, 'ev': None, 'class': 'D', 'stake': 0.,
              'monetary_permission': False, 'execution_enabled': False, 'holdout_eligible': False,
              'limitations': ['No learned count distribution, line probability, joint goal/statistic model or admission.',
                              'Allowed counts describe what other teams recorded against the next opponent, without opponent strength adjustment.',
                              'Fixed shrink/outlier probes are diagnostics, not calibrated thresholds.',
                              'Local receipt hashes bind bytes, not provider authenticity; completeness not certified.',
                              'Fouls never supply referee/card evidence.']}
    output['hash'] = digest(output)
    return output


def _observations(fixtures, statistics, target, fid, tid, metric, cutoff):
    identity = lambda r: (r['league']['id'], r['teams']['home']['id'], r['teams']['away']['id'], time(r['fixture']['date']))
    observations, excluded = [], Counter()
    for hid, histories in sorted(fixtures.items()):
        if hid == fid: continue
        if len({identity(r) for _, r in histories}) != 1: excluded['FIXTURE_IDENTITY_CONFLICT'] += 1; continue
        r = histories[0][1]
        if r['league']['id'] != target['league']['id']: excluded['OTHER_LEAGUE'] += 1; continue
        teams = {r['teams'][side]['id'] for side in ('home', 'away')}
        if tid not in teams: continue
        statuses = {v['fixture']['status']['short'] for _, v in histories}
        ft = [(p, v) for p, v in histories if v['fixture']['status']['short'] == 'FT']
        if not ft or not statuses <= {'NS', 'FT'}: excluded['NOT_REGULATION_FT'] += 1; continue
        if len({digest(v['score']['fulltime']) for _, v in ft}) != 1: excluded['RESULT_REVISION_CONFLICT'] += 1; continue
        kickoff = time(r['fixture']['date'])
        if not 0 < (cutoff - kickoff).total_seconds() <= METHOD['history_days'] * 86400:
            excluded['HISTORY_CUTOFF'] += 1; continue
        first_ft = min(time(p['receipt']['received_at']) for p, _ in ft)
        packets = [p for p in statistics.get(hid, []) if time(p['receipt']['request_started_at']) >= first_ft]
        if not packets: excluded['NO_POST_FT_STATISTICS'] += 1; continue
        counts = defaultdict(set)
        bad_team = False
        for p in packets:
            for block in p['data']['response']:
                stid = block['team']['id']
                if stid not in teams: bad_team = True; continue
                for item in block['statistics']:
                    if item['type'] == metric and item.get('value') is not None:
                        counts[stid].add(item['value'])
        if bad_team: excluded['STATISTICS_TEAM_MISMATCH'] += 1; continue
        if any(len(values) > 1 for values in counts.values()): excluded['STATISTICS_REVISION_CONFLICT'] += 1; continue
        if not counts[tid]: excluded['NULL_OR_MISSING_STATISTIC'] += 1; continue
        opponent = next(iter(teams - {tid}))
        observations.append({'fixture_id': hid, 'kickoff': r['fixture']['date'],
                             'venue': 'HOME' if r['teams']['home']['id'] == tid else 'AWAY',
                             'opponent_id': opponent, 'count': next(iter(counts[tid])),
                             'opponent_count': next(iter(counts[opponent])) if counts[opponent] else None})
    observations.sort(key=lambda r: (time(r['kickoff']), r['fixture_id']))
    return observations, excluded
