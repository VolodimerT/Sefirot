"""Explicit local football-day contract; UTC instants are never rewritten."""
from datetime import date, datetime, time as wall_time, timedelta, timezone as utc
from zoneinfo import ZoneInfo

from sefirot.contracts import time
from sefirot.sports_archive import validate_packet
from sefirot.football_query import validate_fixture_query

ZONES = ('UTC', 'Europe/Kyiv')


def day_window(day, timezone='UTC'):
    if timezone not in ZONES:
        raise ValueError('DAY_TIMEZONE_UNSUPPORTED')
    d = date.fromisoformat(day)
    if d.isoformat() != day:
        raise ValueError('CANONICAL_DAY_REQUIRED')
    zone = ZoneInfo(timezone)
    start = datetime.combine(d, wall_time(), zone).astimezone(utc.utc)
    end = datetime.combine(d+timedelta(days=1), wall_time(), zone).astimezone(utc.utc)
    return {'day': day, 'timezone': timezone, 'start_utc': start.isoformat(),
            'end_utc_exclusive': end.isoformat(), 'duration_hours': (end-start).total_seconds()/3600}


def calendar_day(packet, day, at, timezone='UTC'):
    window = day_window(day, timezone)
    validate_packet(packet, at)
    params = packet['receipt']['parameters']
    allowed = [{'date': day, 'timezone': timezone}]
    if timezone == 'UTC':
        allowed.append({'date': day})
    if params not in allowed:
        raise ValueError('COMPLETE_LOCAL_DATE_QUERY_REQUIRED')
    validate_fixture_query(packet['data'], params)
    rows = packet['data']['response']
    if any(not time(window['start_utc']) <= time(r['fixture']['date']) < time(window['end_utc_exclusive']) for r in rows):
        raise ValueError('CALENDAR_DAY_MISMATCH')
    return sorted(rows, key=lambda r: (time(r['fixture']['date']), r['fixture']['id']))


def league_calendar_bundle(packets, day, at, timezone='UTC'):
    """Union complete saved league-season pages, without claiming global coverage."""
    if timezone != 'UTC' or not isinstance(packets, list) or not 1 <= len(packets) <= 100:
        raise ValueError('BOUNDED_UTC_LEAGUE_BUNDLE_REQUIRED')
    window = day_window(day, timezone)
    scope = set(); fixture_ids = set(); rows = []
    for packet in packets:
        validate_packet(packet, at)
        params = packet['receipt']['parameters']
        if not isinstance(params, dict) or set(params) != {'date', 'league', 'season'} or params['date'] != day:
            raise ValueError('EXACT_LEAGUE_DATE_SEASON_QUERY_REQUIRED')
        validate_fixture_query(packet['data'], params)
        try:
            league, season = int(params['league']), int(params['season'])
        except (ValueError, TypeError):
            raise ValueError('INVALID_LEAGUE_SEASON') from None
        if league <= 0 or season < 2000 or (league, season) in scope:
            raise ValueError('DUPLICATE_OR_INVALID_LEAGUE_SEASON')
        scope.add((league, season))
        for row in packet['data']['response']:
            fid = row['fixture']['id']
            if (row['league']['id'] != league or row['league']['season'] != season
                    or fid in fixture_ids or not time(window['start_utc']) <=
                    time(row['fixture']['date']) < time(window['end_utc_exclusive'])):
                raise ValueError('LEAGUE_BUNDLE_IDENTITY_OR_DAY_CONFLICT')
            fixture_ids.add(fid); rows.append(row)
    return (sorted(rows, key=lambda r: (time(r['fixture']['date']), r['fixture']['id'])),
            [list(pair) for pair in sorted(scope)])
