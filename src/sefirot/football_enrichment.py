"""Bounded fixture enrichment planning from saved API-Football receipts (research-only).

No network, forecast fitting, live-prediction or bookmaker coupling. Empty/missing
coverage and partial metadata fail closed rather than becoming invented facts.
"""
from datetime import datetime, timezone

from .contracts import digest, integer, time
from .football_provider import HOST, fixture_identity, validate_enrichment_request

MAX_CALLS = 8
RESERVE_MIN = 5
ALLOWED_PHASES = {'NS': 'PREMATCH', 'FT': 'POSTMATCH'}


def _packet(packet, endpoint, as_of):
    if not isinstance(packet, dict) or not isinstance(packet.get('data'), dict):
        raise ValueError('missing provider packet')
    data, receipt = packet['data'], packet.get('receipt', {})
    if (receipt.get('provider') != 'API_FOOTBALL_V3'
            or receipt.get('provider_host') != HOST
            or receipt.get('endpoint') != '/' + endpoint
            or receipt.get('sports_only') is not True
            or receipt.get('http_status') != 200
            or not isinstance(receipt.get('parameters'), dict)
            or receipt.get('payload_hash') != digest(data)):
        raise ValueError('provider packet receipt integrity mismatch')
    if time(receipt['received_at']) > as_of:
        raise ValueError('future provider receipt')
    if data.get('errors') not in ([], {}) or not isinstance(data.get('response'), list):
        raise ValueError('invalid provider response')
    if data.get('results') != len(data['response']) or data.get('paging', {}).get('total', 1) > 1:
        raise ValueError('incomplete provider response')
    return data['response']


def plan_fixture_enrichment(fixture_packet, league_packet, status_packet, fixture_id, *,
                            at, max_calls=6, reserve=RESERVE_MIN, spent_since_status=0):
    """Generate a frozen, budget-bound single-fixture plan, never execute it."""
    integer(fixture_id, 'fixture id', 1)
    integer(max_calls, 'max calls', 1, MAX_CALLS)
    integer(reserve, 'quota reserve', RESERVE_MIN, 1000000)
    integer(spent_since_status, 'requests since status', 0, MAX_CALLS)
    cutoff = time(at)
    if cutoff > datetime.now(timezone.utc):
        raise ValueError('future analysis cutoff not allowed')
    fixtures = _packet(fixture_packet, 'fixtures', cutoff)
    leagues = _packet(league_packet, 'leagues', cutoff)
    sd, sr = status_packet.get('data', {}), status_packet.get('receipt', {})
    if (sr.get('endpoint') != '/status' or sr.get('provider_host') != HOST
            or sr.get('provider') != 'API_FOOTBALL_V3' or sr.get('sports_only') is not True
            or sr.get('payload_hash') != digest(sd) or time(sr['received_at']) > cutoff):
        raise ValueError('status receipt invalid')
    if (cutoff - time(sr['received_at'])).total_seconds() > 300:
        raise ValueError('provider quota snapshot stale; refresh status first')
    if sd.get('errors') not in ([], {}) or not isinstance(sd.get('response'), dict):
        raise ValueError('status provider error')
    info = sd['response']
    if info.get('subscription', {}).get('active') is not True:
        raise ValueError('subscription inactive')
    usage = info.get('requests', {})
    used = integer(usage.get('current'), 'quota used', 0)
    limit = integer(usage.get('limit_day'), 'quota limit', 1)
    if used > limit:
        raise ValueError('quota status inconsistent')
    minute = sr.get('quota', {}).get('x-ratelimit-remaining')
    if minute is not None and (not isinstance(minute, str) or
                               not minute.isascii() or not minute.isdecimal()):
        raise ValueError('invalid minute quota header')
    budget = max(0, min(max_calls, limit - used - reserve - spent_since_status,
                        int(minute) - spent_since_status if minute is not None else max_calls))
    matches = [r for r in fixtures if r.get('fixture', {}).get('id') == fixture_id]
    if len(matches) != 1:
        raise ValueError('unique target fixture required')
    match = matches[0]
    ident = fixture_identity(match)
    season, league_id = match['league'].get('season'), match['league'].get('id')
    integer(season, 'season', 1990, 2200)
    current = match.get('fixture', {}).get('status', {}).get('short')
    if current not in ALLOWED_PHASES:
        raise ValueError('live/extra-time/postponed fixture cannot be enriched here')
    if current == 'NS' and cutoff >= time(ident['kickoff']):
        raise ValueError('prematch collection after kickoff is forbidden')
    if current == 'FT' and cutoff <= time(ident['kickoff']):
        raise ValueError('FT before kickoff')
    matching = []
    for row in leagues:
        if row.get('league', {}).get('id') != league_id:
            continue
        matching.extend(x for x in row.get('seasons', []) if x.get('year') == season)
    if len(matching) != 1:
        raise ValueError('unique league-season coverage record required')
    coverage = matching[0].get('coverage')
    if not isinstance(coverage, dict):
        raise ValueError('league-season coverage missing')
    def covered(*keys):
        value = coverage
        for key in keys:
            if not isinstance(value, dict):
                return False
            value = value.get(key)
        return value is True
    home = integer(match['teams']['home']['id'], 'home team', 1)
    away = integer(match['teams']['away']['id'], 'away team', 1)
    if home == away:
        raise ValueError('fixture teams match')
    options = []
    def offer(endpoint, params, flag, reason):
        if flag:
            validate_enrichment_request(endpoint, params)
            options.append({'endpoint': endpoint, 'params': params, 'reason': reason})
    if current == 'NS':
        offer('standings', {'league': league_id, 'season': season},
              covered('standings'), 'LEAGUE_RANKINGS')
        for team in (home, away):
            offer('teams/statistics', {'league': league_id, 'season': season,
                  'team': team, 'date': cutoff.date().isoformat()},
                  True, 'TEAM_SEASON_TOTALS; AS_OBSERVED_NOW')
        offer('fixtures/headtohead', {'h2h': str(home) + '-' + str(away),
              'league': league_id, 'last': 5}, True, 'H2H_CONTEXT_ONLY; NOT_BASELINE')
        offer('injuries', {'fixture': fixture_id}, covered('injuries'), 'INJURIES_BY_FIXTURE')
        for team in (home, away):
            offer('coachs', {'team': team}, True, 'COACH_HISTORY_AS_OBSERVED')
        # The source itself says lineups typically appear 30-60m before kickoff.
        mins = (time(ident['kickoff']) - cutoff).total_seconds() / 60
        offer('fixtures/lineups', {'fixture': fixture_id},
              covered('fixtures', 'lineups') and 0 < mins <= 65, 'CONFIRMED_LINEUP_ONLY')
    else:
        offer('fixtures/events', {'fixture': fixture_id},
              covered('fixtures', 'events'), 'FT_EVENTS_ONLY')
        offer('fixtures/statistics', {'fixture': fixture_id},
              covered('fixtures', 'statistics_fixtures'), 'FT_TEAM_COUNTS_ONLY')
        offer('fixtures/players', {'fixture': fixture_id},
              covered('fixtures', 'statistics_players'), 'FT_PLAYER_COUNTS_ONLY')
    selected = options[:budget]
    result = {'schema': 'sefirot-api-football-enrichment-plan-v1', 'fixture_id': fixture_id,
              'phase': ALLOWED_PHASES[current], 'cutoff': cutoff.isoformat(),
              'source_hashes': [fixture_packet['receipt']['payload_hash'],
                                league_packet['receipt']['payload_hash'],
                                status_packet['receipt']['payload_hash']],
              'quota': {'used': used, 'limit_day': limit, 'reserve': reserve,
                        'minute_remaining': int(minute) if minute is not None else None,
                        'spent_since_status': spent_since_status, 'budget': budget},
              'requested': selected, 'skipped': len(options) - len(selected),
              'coverage_available': len(options), 'status': 'READY_FOR_MANUAL_FETCH'
                if selected else 'NO_ADMISSIBLE_REQUESTS',
              'monetary_permission': False, 'execution_enabled': False,
              'prediction_changed': False, 'live_enabled': False}
    return {**result, 'hash': digest(result)}
