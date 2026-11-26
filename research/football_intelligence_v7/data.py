"""Offline V7 report and priority queue over the existing guarded source ledger."""
from collections import Counter, defaultdict
from datetime import timedelta
from math import isfinite

from research import football_pipeline as pipeline
from sefirot.contracts import time
from sefirot.football_provider import validate_prematch_state
from sefirot.small_market import METRICS

FIELDS = {**METRICS, 'POSSESSION': 'Ball Possession', 'XG': 'expected_goals',
          'CROSSES': 'Total Crosses', 'PASSES': 'Total passes'}
WINDOW_END = timedelta(minutes=20)
WINDOW_START = timedelta(minutes=65)


def _value(field, value):
    if field not in ('POSSESSION', 'XG'):
        return value if type(value) is int and 0 <= value <= 10000 else None
    try:
        if type(value) not in (int, float, str):
            return None
        if field == 'POSSESSION':
            if not isinstance(value, str) or not value.endswith('%'):
                return None
            value = value[:-1]
        number = float(value)
        limit = 100 if field == 'POSSESSION' else 50
        return number if isfinite(number) and 0 <= number <= limit else None
    except (ValueError, OverflowError):
        return None


def _stat_fields(evidence, teams, first_ft):
    observed = defaultdict(set)
    sources = defaultdict(set)
    invalid = set()
    for rec, packet in evidence:
        receipt = packet['receipt']
        rows = packet['data']['response']
        if time(receipt['request_started_at']) < first_ft or set(receipt['parameters']) != {'fixture'}:
            continue
        if {row['team']['id'] for row in rows} != set(teams.values()):
            return {}, 'STATISTICS_TEAM_MISMATCH'
        for row in rows:
            for side, tid in teams.items():
                if row['team']['id'] != tid:
                    continue
                lookup = {item['type']: item.get('value') for item in row['statistics']}
                for field, label in FIELDS.items():
                    key = side, field
                    value = _value(field, lookup.get(label))
                    if value is None:
                        if lookup.get(label) is not None:
                            invalid.add(key)
                        continue
                    observed[key].add(value)
                    sources[key].add(rec['id'])
    return {key: {'value': next(iter(values)), 'source_ids': sorted(sources[key])}
            for key, values in observed.items() if len(values) == 1 and key not in invalid}, (
                'STATISTICS_FIELD_CONFLICT' if invalid or any(len(v) > 1 for v in observed.values()) else None)


def _lineup_sources(evidence, teams, kickoff):
    versions = []
    for rec, p in evidence:
        receipt, data = p['receipt'], p['data']
        supplied = data.get('parameters')
        if (time(rec['available_at']) >= kickoff
                or not kickoff - WINDOW_START <= time(receipt['received_at']) < kickoff
                or not isinstance(supplied, dict) or data.get('get') != 'fixtures/lineups'
                or {k: str(v) for k, v in supplied.items()} !=
                {k: str(v) for k, v in receipt['parameters'].items()}
                or set(receipt['parameters']) != {'fixture'}):
            continue
        try:
            rows = data['response']
            if len(rows) != 2 or {row['team']['id'] for row in rows} != set(teams.values()):
                continue
            lineups = {row['team']['id']: [v['player']['id'] for v in row['startXI']] for row in rows}
            ids = [pid for xi in lineups.values() for pid in xi]
            if (any(len(xi) != 11 for xi in lineups.values()) or
                    any(type(pid) is not int or pid <= 0 for pid in ids) or len(set(ids)) != 22):
                continue
            versions.append((p['receipt']['received_at'], rec['id'], lineups))
        except (AttributeError, KeyError, TypeError):
            continue
    if not versions:
        return []
    # A changed XI can be a legitimate update, but simultaneous disagreement is ambiguous.
    stamp = max(time(v[0]) for v in versions)
    latest = [(rid, xis) for observed, rid, xis in versions if time(observed) == stamp]
    return sorted(rid for rid, xis in latest if xis == latest[0][1]) if all(
        xis == latest[0][1] for _, xis in latest) else []


def _report_rows(views, ledger, now):
    stats, lineups, calendars = defaultdict(list), defaultdict(list), defaultdict(list)
    for rec, packet in ledger:
        receipt = packet['receipt']
        endpoint = receipt['endpoint']
        if endpoint in ('/fixtures/statistics', '/fixtures/lineups'):
            raw_id = str(receipt['parameters'].get('fixture', ''))
            if raw_id.isascii() and raw_id.isdigit():
                (stats if endpoint == '/fixtures/statistics' else lineups)[int(raw_id)].append((rec, packet))
        elif endpoint == '/fixtures':
            for fixture in packet['data']['response']:
                calendars[fixture['fixture']['id']].append((rec, fixture))
    cross_scope_conflicts = {fid for fid, versions in calendars.items()
                             if len({(v['league']['id'], v['league']['season'])
                                     for _, v in versions}) > 1}
    rows = []
    for view in views:
        first_ft = {}
        for item in view['temporal_source_views']['POST_FT']:
            fid, observed = item['fixture_id'], time(item['received_at'])
            first_ft[fid] = min(first_ft.get(fid, observed), observed)
        for fid, item in sorted(view['fixtures'].items()):
            if fid in cross_scope_conflicts:
                view['reasons']['CROSS_SCOPE_FIXTURE_CONFLICT'] = view['reasons'].get('CROSS_SCOPE_FIXTURE_CONFLICT', 0) + 1
                continue
            teams = {side: team['id'] for side, team in item['teams'].items() if side in ('home', 'away')}
            fixture = item['fixture']
            kickoff = time(fixture['date'])
            prior = calendars[fid]
            sources = sorted({rec['id'] for rec, row in prior if row == item})
            latest = max((time(rec['source_packet']['receipt']['received_at'])
                          for rec, row in prior if row == item), default=None)
            state = fixture['status']['short']
            if state == 'NS':
                try:
                    validate_prematch_state(item)
                except ValueError:
                    state = 'INVALID_NS'
            fresh = latest is not None and now - latest <= timedelta(hours=24)
            verified_ft = fid in first_ft and state == 'FT' and kickoff < now
            fields, issue = _stat_fields(stats[fid], teams, first_ft[fid]) if verified_ft else ({}, None)
            rows.append({'fixture_id': fid, 'league': view['league'], 'season': view['season'],
                         'teams': teams, 'kickoff': fixture['date'], 'state': state,
                         'fixture_sources': sources, 'calendar_fresh': fresh,
                         'ft_receipted': verified_ft, 'goals': item['score']['fulltime'] if verified_ft else None,
                         'lineups': _lineup_sources(lineups[fid], teams, kickoff) if state == 'NS' and kickoff > now else [],
                         'quote_status': 'SEPARATE_APPROVED_GATEWAY_REQUIRED',
                         'tactical_fit': 'UNVERIFIED', 'referee_gate': 'NOT_EVALUATED',
                         'stats_packet_complete': fid in view['statistics_qc_fixture_ids'],
                         'stat_issue': issue, 'fields': {
                             side: {field: fields.get((side, field)) for field in FIELDS} for side in teams}})
    return rows


def _collection_plan(views, rows, ledger, attempts, now):
    def key(endpoint, params):
        return endpoint.lstrip('/'), tuple(sorted((k, str(v)) for k, v in params.items()))

    latest = {}
    for rec, packet in ledger:
        r = packet['receipt']
        k = key(r['endpoint'], r['parameters'])
        received = time(r['received_at'])
        latest[k] = max(latest.get(k, received), received)
    today = now.date()
    sent = {key(a['query']['endpoint'], a['query']['params']) for a in attempts
            if time(a['at']).date() == today}
    unresolved = {k for a in attempts
                  if (k := key(a['query']['endpoint'], a['query']['params'])) not in latest
                  or latest[k] < time(a['at'])}
    capability_observations = defaultdict(list)
    for _, p in ledger:
        receipt, data = p['receipt'], p['data']
        echo = data.get('parameters')
        if (receipt['endpoint'] == '/leagues' and data.get('get') == 'leagues'
                and isinstance(echo, dict)
                and {k: str(v) for k, v in echo.items()} ==
                {k: str(v) for k, v in receipt['parameters'].items()}):
            for row in p['data']['response']:
                if not isinstance(row, dict) or not isinstance(row.get('league'), dict):
                    continue
                for season in row.get('seasons') or []:
                    if not isinstance(season, dict):
                        continue
                    flags = season.get('coverage')
                    fixtures = flags.get('fixtures') if isinstance(flags, dict) else None
                    league_id, year = row['league'].get('id'), season.get('year')
                    if not isinstance(fixtures, dict) or type(league_id) is not int or type(year) is not int:
                        continue
                    for selector, value in [('id', league_id), ('season', year)]:
                        if selector in echo and str(echo[selector]) != str(value):
                            break
                    else:
                        capability_observations[(league_id, year)].append(
                            (time(receipt['received_at']), fixtures.get('lineups') is True))
    capabilities = {scope for scope, observations in capability_observations.items()
                    if all(flag for stamp, flag in observations
                           if stamp == max(t for t, _ in observations))}
    proposals = {}

    def offer(priority, due, category, endpoint, params, reason):
        k = key(endpoint, params)
        if k in sent or k in unresolved:
            return
        proposals.setdefault(k, (priority, due, category, k, endpoint, params, reason))

    for view in views:
        params = {'league': view['league'], 'season': view['season']}
        receipt = latest.get(key('fixtures', params))
        if receipt is None or now - receipt >= timedelta(hours=24):
            offer(3, now.timestamp(), 'HISTORY', 'fixtures', params, 'LEAGUE_CALENDAR_REFRESH')

    pending = Counter()
    for row in rows:
        fid, cutoff = row['fixture_id'], time(row['kickoff'])
        gap = cutoff - now
        if row['state'] == 'NS' and gap > WINDOW_END:
            pending['ODDS_SEPARATE_APPROVED_GATEWAY_REQUIRED'] += 1
            pending['TACTICAL_CONTEXT_PREMATCH_EVIDENCE_REQUIRED'] += 1
            if gap <= WINDOW_START:
                if not row['calendar_fresh']:
                    offer(0, cutoff.timestamp(), 'CONTEXT', 'fixtures', {'id': fid}, 'STALE_KICKOFF_EVIDENCE')
                elif row['lineups']:
                    continue
                elif (row['league'], row['season']) in capabilities:
                    params = {'fixture': fid}
                    observed = latest.get(key('fixtures/lineups', params))
                    if observed is None or now - observed >= timedelta(minutes=15):
                        offer(1, cutoff.timestamp(), 'LINEUPS', 'fixtures/lineups', params, 'MISSING_BOUND_LINEUPS')
                    else:
                        pending['LINEUP_REFRESH_COOLDOWN'] += 1
                else:
                    pending['LINEUP_SOURCE_COVERAGE_UNVERIFIED'] += 1
            else:
                pending['LINEUP_WINDOW_NOT_YET_OPEN'] += 1
        elif row['state'] == 'NS' and -timedelta(days=2) <= gap <= -timedelta(hours=3):
            received = latest.get(key('fixtures', {'id': fid}))
            if received is None or received < cutoff + timedelta(hours=3):
                offer(2, cutoff.timestamp(), 'FT', 'fixtures', {'id': fid}, 'AWAITING_REGULATION_RESULT')
        elif row['ft_receipted'] and not row['stats_packet_complete'] and not row['stat_issue']:
            # A saved empty statistics response is deliberately not re-downloaded
            # every day. A new collection requires separately verified coverage.
            if key('fixtures/statistics', {'fixture': fid}) not in latest:
                offer(4, -cutoff.timestamp(), 'HISTORY',
                      'fixtures/statistics', {'fixture': fid}, 'FIRST_BOUND_FT_STATISTICS')

    fenced = any(v['pending_qc_packets'] or v['qc_rejected_packets'] or v['rejected_matches']
                 or v['reasons'].get('CROSS_SCOPE_FIXTURE_CONFLICT') for v in views)
    used = sum(time(a['at']).date() == today for a in attempts)
    room = max(0, 5 - used)
    ordered = sorted(proposals.values(), key=lambda v: (v[0], v[1], v[3]))
    return {'queries': [{'category': c, 'endpoint': e, 'params': p, 'reason': reason}
                        for _, _, c, _, e, p, reason in ordered[:room]] if not fenced else [],
            'daily_limit': 5, 'minute_limit': 1, 'reserve': 5,
            'local_slots_remaining': room, 'prior_attempts_today': used,
            'unresolved_queries': len(unresolved), 'quality_fenced': fenced,
            'deferred': dict(pending), 'budget_action': 'NONE',
            'provider_permit': 'RECHECK_SHARED_GATEWAY_BEFORE_EXECUTION',
            'automatic_retry': False, 'execution_enabled': False}


def inspect(repo, scopes, *, as_of=None):
    """Return a bounded report from hash/chronology-verified source records."""
    stamp = as_of or pipeline.utcnow()
    now = time(stamp)
    scopes = sorted(set(scopes))
    if not 1 <= len(scopes) <= 32 or now > time(pipeline.utcnow()):
        raise ValueError('INVALID_V7_SCOPE_OR_CUTOFF')
    pipeline.source_only(repo)
    ledger = pipeline.packets(repo, stamp)
    views = [pipeline.league_view(repo, league, season, as_of=stamp) for league, season in scopes]
    rows = _report_rows(views, ledger, now)
    teams = defaultdict(Counter)
    leagues = []
    for v in views:
        league, season = v['league'], v['season']
        matches = [r for r in rows if (r['league'], r['season']) == (league, season)]
        historical = [r for r in matches if r['ft_receipted']]
        upcoming = [r for r in matches if r['state'] == 'NS' and time(r['kickoff']) > now]
        for row in matches:
            for side, tid in row['teams'].items():
                counter = teams[(league, season, tid)]
                counter['observed_matches'] += 1
                counter['receipted_ft'] += int(row['ft_receipted'])
                counter.update(field for field, value in row['fields'][side].items() if value is not None)
        leagues.append({'league': league, 'season': season, 'expected_matches': v['expected_matches'],
                        'observed_matches': v['observed_matches'], 'usable_matches': len(matches),
                        'receipted_ft': len(historical), 'upcoming': len(upcoming),
                        'prematch_lineups': sum(bool(r['lineups']) for r in upcoming),
                        'fresh_calendar_upcoming': sum(r['calendar_fresh'] for r in upcoming),
                        'field_denominator_ft': len(historical),
                        'paired_fields': {f: sum(all(r['fields'][s][f] is not None for s in ('home', 'away'))
                                                 for r in historical) for f in FIELDS},
                        'issues': v['reasons']})
    attempts = [a for a in pipeline._records(repo, pipeline.ATTEMPT) if time(a['at']) <= now]
    return {'as_of': stamp, 'leagues': leagues, 'fixtures': rows,
            'teams': [{'league': l, 'season': s, 'team_id': t, 'coverage': dict(c)}
                      for (l, s, t), c in sorted(teams.items())],
            'queue': _collection_plan(views, rows, ledger, attempts, now),
            'verified_quotes': None, 'decision': 'PASS', 'provider_requests': 0,
            'fit_allowed': False, 'monetary_permission': False}
