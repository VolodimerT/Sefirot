"""One bounded sports-only collection, predeclared cohort and research capture."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .contracts import PROFILES, Policy, digest, integer, number, time
from .football_gateway import get_sports, transport_status
from .football_provider import HOST, MAX_PROVIDER_ID, FootballRequestError, status_summary
from .football_query import FootballQueryError, validate_fixture_query
from .forward import create_plan, capture_plan, inspect_plan
from .identity import code_hash, model_code_hash
from .repository import Repository
from .service import Service
from .sports_archive import archive_packets, read_archive, validate_packet


def _write(path, value):
    with Path(path).open('x', encoding='utf-8') as file:
        json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write('\n')


def _reason(exc):
    if isinstance(exc, FootballQueryError):
        return exc.code
    if isinstance(exc, FootballRequestError):
        return exc.code
    message = str(exc).lower()
    if 'missing or invalid' in message:
        return 'CREDENTIAL_MISSING_OR_INVALID'
    if 'http 401' in message or 'http 403' in message:
        return 'PROVIDER_AUTH_FAILED'
    if 'http 429' in message:
        return 'PROVIDER_QUOTA_EXHAUSTED'
    if 'network unavailable' in message:
        return 'PROVIDER_NETWORK_UNAVAILABLE'
    return 'INVALID_OR_UNAVAILABLE_PROVIDER_RESPONSE'


def collect_session(directory, day, profiles, *, source_reliability, max_requests=12,
                    quota_reserve=5, source_archive=None, timezone_name='Europe/Kyiv',
                    history_seasons_back=0,
                    policy=None, getter=None, clock=None, research_grids=False):
    if not isinstance(research_grids, bool):
        raise ValueError('research_grids must be an explicit boolean')
    policy = policy or Policy()
    if policy.goal_model != 'BASELINE_V1':
        raise ValueError('data session currently requires BASELINE_V1')
    integer(max_requests, 'session request limit', 2, 50)
    integer(quota_reserve, 'daily quota reserve', 0, 10000)
    integer(history_seasons_back, 'extra preceding seasons', 0, 2)
    number(source_reliability, 'operator source reliability', 0, 1)
    zone = ZoneInfo(timezone_name)
    selected_day = date.fromisoformat(day)
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = time(clock().isoformat())
    if not now.astimezone(zone).date() <= selected_day <= now.astimezone(zone).date() + timedelta(days=7):
        raise ValueError('session date must be today or within the next seven days')
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError('explicit API league/profile mapping required')
    for league, profile in profiles.items():
        integer(league, 'API league id', 1, MAX_PROVIDER_ID)
        if profile not in PROFILES or profile == 'UNKNOWN':
            raise ValueError('explicit competition profile required')
    previous = read_archive(source_archive, now.isoformat()) if source_archive else []
    # Read old receipts as recorded. A new collection must not reuse a packet
    # whose provider echo or date scope disagrees with its original request.
    for packet in previous:
        validate_fixture_query(packet['data'], packet['receipt']['parameters'])
    root = Path(directory)
    if root.exists():
        raise ValueError('data session directory already exists; choose a new directory')
    root.mkdir(parents=True)
    archive = root / 'sports-archive'
    archive.mkdir()
    getter = getter or get_sports
    report = {'schema': 'api-data-session-v1', 'started_at': now.isoformat(), 'day': day,
        'timezone': timezone_name, 'code_hash': code_hash(), 'model_hash': model_code_hash(),
        'policy_hash': policy.fingerprint, 'transport': transport_status(), 'output_directory': str(root.resolve()),
        'profiles': {str(k): profiles[k] for k in sorted(profiles)},
        'source_reliability': 'operator assertion: ' + str(source_reliability),
        'max_requests': max_requests, 'quota_reserve': quota_reserve, 'requests': [],
        'history_seasons_back': history_seasons_back,
        'history_season_selection': 'CURRENT_AND_PRECEDING_WITH_EXPLICIT_OPT_IN',
        'planned_fixtures': 0, 'forecasts_created': 0, 'plan_id': None, 'fixtures': [],
        'status': 'COLLECTION_INCOMPLETE', 'blockers': [], 'prices_requested': False,
        'holdout_passed': False, 'monetary_permission': False, 'execution_enabled': False,
        'research_grids_enabled': research_grids,
        'limitations': ['Research cohort, not validation or profitability proof',
            'Missing lineup/injury/coach/rotation/tactical facts remain missing',
            'Gateway receipts are local provenance, not provider signatures']}
    quota_remaining = None
    minute_remaining = None
    stopped = None
    repo = None

    def fetch(endpoint, params):
        nonlocal quota_remaining, minute_remaining, stopped
        if stopped or len(report['requests']) >= max_requests:
            return None, stopped or 'SESSION_REQUEST_BUDGET_EXHAUSTED'
        if quota_remaining is not None and quota_remaining <= quota_reserve:
            return None, 'DAILY_QUOTA_RESERVE_REACHED'
        if minute_remaining is not None and minute_remaining <= 0:
            return None, 'PROVIDER_RATE_LIMIT_WINDOW_EXHAUSTED'
        attempt = {'endpoint': endpoint, 'parameters': params, 'started_at': clock().isoformat()}
        report['requests'].append(attempt)
        if quota_remaining is not None:
            quota_remaining -= 1
        if minute_remaining is not None:
            minute_remaining -= 1
        try:
            packet = getter(endpoint, params)
            receipt = packet['receipt']
            if (receipt['provider_host'] != HOST or receipt['endpoint'] != '/' + endpoint
                    or receipt['parameters'] != params or receipt['http_status'] != 200
                    or receipt['provider'] != 'API_FOOTBALL_V3' or receipt['sports_only'] is not True
                    or digest(packet['data']) != receipt['payload_hash']
                    or time(receipt['request_started_at']) < time(attempt['started_at'])
                    or time(receipt['request_started_at']) > time(receipt['received_at'])
                    or time(receipt['received_at']) > time(clock().isoformat())):
                raise ValueError('provider receipt mismatch')
            if endpoint == 'fixtures':
                validate_packet(packet, clock().isoformat())
                validate_fixture_query(packet['data'], params)
                if 'league' in params and any(r['league']['id'] != params['league']
                        or r['league'].get('season') != params['season']
                        or r['fixture']['status']['short'] != 'FT'
                        or not date.fromisoformat(params['from']) <= time(r['fixture']['date']).astimezone(zone).date()
                            <= date.fromisoformat(params['to']) for r in packet['data']['response']):
                    raise ValueError('provider history query scope mismatch')
            header_remaining = receipt.get('quota', {}).get('x-ratelimit-requests-remaining')
            if header_remaining is not None:
                remaining = int(header_remaining)
                integer(remaining, 'provider remaining quota')
                quota_remaining = remaining if quota_remaining is None else min(remaining, quota_remaining)
            minute_header = receipt.get('quota', {}).get('x-ratelimit-remaining')
            if minute_header is not None:
                if not isinstance(minute_header, str) or not minute_header.isascii() or not minute_header.isdecimal():
                    raise ValueError('provider minute quota malformed')
                remaining = int(minute_header)
                integer(remaining, 'provider minute quota')
                minute_remaining = remaining if minute_remaining is None else min(remaining, minute_remaining)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            reason = _reason(exc)
            attempt.update(status=reason, finished_at=clock().isoformat())
            if isinstance(exc, FootballQueryError) or reason in ('PROVIDER_AUTH_FAILED', 'PROVIDER_QUOTA_EXHAUSTED',
                          'PROVIDER_ACCESS_DENIED', 'PROVIDER_ACCOUNT_SUSPENDED',
                          'PROVIDER_NETWORK_UNAVAILABLE', 'CREDENTIAL_MISSING_OR_INVALID'):
                stopped = reason
            return None, reason
        attempt.update(status='RECEIVED', receipt=receipt, finished_at=clock().isoformat())
        if endpoint == 'fixtures':
            archive_packets([packet], archive, clock().isoformat())
        return packet, None

    try:
        if previous:
            report['prior_archive_import'] = archive_packets(previous, archive, clock().isoformat())
        status, failure = fetch('status', {})
        if failure:
            report['blockers'].append(failure)
            return report
        health = status_summary(status)
        report['provider_health'] = health
        if health['subscription_active'] is not True:
            report['blockers'].append('SUBSCRIPTION_INACTIVE')
            return report
        used, limit = health['requests_current'], health['requests_limit_day']
        integer(used, 'provider quota used'); integer(limit, 'provider daily quota', 1)
        if used > limit:
            raise ValueError('provider quota response inconsistent')
        # Conservatively include this status request even if the provider has not.
        remaining = max(0, limit - used - 1)
        quota_remaining = remaining if quota_remaining is None else min(remaining, quota_remaining)
        target, failure = fetch('fixtures', {'date': day, 'timezone': timezone_name})
        if failure:
            report['blockers'].append(failure)
            return report
        eligible = []
        for row in target['data']['response']:
            if time(row['fixture']['date']).astimezone(zone).date() != selected_day:
                raise ValueError('API response contains fixtures outside requested local date')
            if (row['league']['id'] in profiles and row['fixture']['status']['short'] == 'NS'
                    and time(row['fixture']['date']) > time(clock().isoformat())):
                integer(row['league'].get('season'), 'API season', 1900, 2200)
                eligible.append(row)
        report['api_fixtures_received'] = len(target['data']['response'])
        if not eligible:
            report.update(status='NO_FUTURE_FIXTURES_IN_DECLARED_LEAGUES')
            return report
        repo = Repository(root / 'research.sqlite')
        service = Service(repo, policy, clock=clock)
        plan = create_plan(service, target, profiles, source_reliability=source_reliability)
        _write(root / 'plan.json', plan)
        report.update(plan_id=plan['id'], planned_fixtures=len(plan['members']))
        # Scope is committed before history, forecasts or any outcome inspection.
        # All history query seasons are committed *before* requesting history
        # or observing a forecast. This does not react to match outcomes,
        # prices or which side lacks enough observations.
        current = sorted({(r['league']['id'], r['league']['season']) for r in eligible})
        queries = sorted({(league, season - offset)
            for league, season in current
            for offset in range(history_seasons_back + 1)
            if season - offset >= 1900}, key=lambda item: (item[0], -item[1]))
        report['predeclared_history_queries'] = [
            {'league': league, 'season': season} for league, season in queries]
        report['history_queries'] = []
        for league, season in queries:
            params = {'league': league, 'season': season, 'status': 'FT',
                'from': (now.astimezone(zone).date() - timedelta(days=policy.history_days)).isoformat(),
                'to': now.astimezone(zone).date().isoformat(), 'timezone': timezone_name}
            packet, failure = fetch('fixtures', params)
            report['history_queries'].append({'league': league, 'season': season,
                'status': failure or 'RECEIVED', 'rows': len(packet['data']['response']) if packet else 0})
            if failure:
                report['blockers'].append(failure)
            # Existing archive remains usable even after a new provider refusal.
        capture = capture_plan(service, plan['id'], archive)
        _write(root / 'capture.json', capture)
        status = inspect_plan(service, plan['id'])
        _write(root / 'status.json', status)
        report['fixtures'] = [dict(attempt) for attempt in capture['attempts']]
        for item in report['fixtures']:
            attempt = item
            if attempt['status'] == 'SEALED_RESEARCH':
                report['forecasts_created'] += 1
                prediction = repo.get('predictions', attempt['prediction_id'])
                if not research_grids:
                    item.update(artifact_status='SEALED_FORECAST_ONLY',
                                main_research_contracts=0, goal_builders=0)
                    continue
                try:
                    from .market_grid import create_grid
                    from .builder_research import create_builder_grid
                    grid = create_grid(prediction, policy, service.now())
                    builder = create_builder_grid(grid, prediction, policy, service.now())
                    fid = next(m['fixture_id'] for m in plan['members'] if m['match']['id'] == attempt['match_id'])
                    folder = root / str(fid)
                    folder.mkdir()
                    _write(folder / 'market-grid.json', grid)
                    _write(folder / 'builder-grid.json', builder)
                except (ValueError, OSError, KeyError, TypeError):
                    item['artifact_status'] = 'RESEARCH_GRID_UNAVAILABLE'
                    report['blockers'].append('RESEARCH_GRID_UNAVAILABLE')
                else:
                    item.update(artifact_status='GRIDS_CREATED', main_research_contracts=len(grid['candidates']),
                        goal_builders=len(builder['candidates']), market_grid_file=str(fid) + '/market-grid.json',
                        builder_grid_file=str(fid) + '/builder-grid.json')
        report['fixture_counts'] = dict(Counter(r['status'] for r in report['fixtures']))
        report['journal_integrity'] = repo.verify()
        report['status'] = ('RESEARCH_FORECASTS_COLLECTED' if report['forecasts_created'] == report['planned_fixtures']
            else 'PARTIAL_RESEARCH_COLLECTION' if report['forecasts_created'] else 'NO_USABLE_RESEARCH_FORECASTS')
        if 'RESEARCH_GRID_UNAVAILABLE' in report['blockers']:
            report['status'] = 'RESEARCH_COLLECTION_WITH_ARTIFACT_GAPS'
    except (ValueError, OSError, KeyError, TypeError) as exc:
        report['blockers'].append(_reason(exc))
        report['status'] = 'COLLECTION_INCOMPLETE'
    finally:
        if repo:
            report['journal_integrity'] = repo.verify()
            repo.close()
        report['finished_at'] = clock().isoformat()
        report['request_attempts'] = len(report['requests'])
        report['received_packets'] = sum(r['status'] == 'RECEIVED' for r in report['requests'])
        report['network_requests_upper_bound'] = sum(r['status'] != 'CREDENTIAL_MISSING_OR_INVALID' for r in report['requests'])
        report['quota_remaining_conservative'] = quota_remaining
        report['minute_remaining_conservative'] = minute_remaining
        report['blockers'] = sorted(set(report['blockers']))
        report['hash'] = digest(report)
        _write(root / 'REPORT.json', report)
    return report


def render_session(report):
    lines = ['СЕФИРОТ — API-сбор ' + report['day'],
        'Статус: ' + report['status'],
        'Research-сетки: ' + ('LABS включены' if report.get('research_grids_enabled') else 'выключены'),
        f"Попытки запросов: {report['request_attempts']}/{report['max_requests']}; резерв: {report['quota_reserve']}",
        f"Предыдущих сезонов истории: {report['history_seasons_back']}",
        f"Назначено матчей: {report['planned_fixtures']}; research прогнозов: {report['forecasts_created']}"]
    for row in report['fixtures']:
        coverage = row.get('coverage', {})
        teams = coverage.get('teams', {})
        counts = ', '.join(f"{s}: {v['eligible_games']}/{coverage['required_team_games']}" for s, v in teams.items())
        lines.append(row['match_id'] + ': ' + row['status'] + ('; ' + counts if counts else ''))
    if report['blockers']:
        lines.append('Блокеры: ' + ', '.join(report['blockers']))
    lines.append('Исследование, stake=0; API-цены и денежный допуск не запрошены.')
    return '\n'.join(lines)
