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
