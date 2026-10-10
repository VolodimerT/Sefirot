"""Check a fixture response against the request, without rewriting either.

Local IANA rules make date/offset semantics replayable. They do not attest
provider origin or prove that a timezone is supported by the remote account.
"""
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import time

QUERY_ERROR_CODES = frozenset({
    'ENDPOINT_ECHO_MISMATCH', 'QUERY_ECHO_MISMATCH', 'QUERY_DATE_INVALID',
    'QUERY_TIMEZONE_UNSUPPORTED', 'QUERY_TIMEZONE_RESPONSE_MISMATCH',
    'QUERY_RESPONSE_MISMATCH', 'QUERY_RESPONSE_MALFORMED',
})


class FootballQueryError(ValueError):
    """Fixed codes only; response fields and credentials never enter errors."""
    def __init__(self, code):
        if code not in QUERY_ERROR_CODES:
            raise ValueError('unknown fixture query error')
        self.code = code
        super().__init__(code)


def fixture_query_zone(params):
    name = params.get('timezone', 'UTC')
    if not isinstance(name, str):
        raise FootballQueryError('QUERY_TIMEZONE_UNSUPPORTED')
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise FootballQueryError('QUERY_TIMEZONE_UNSUPPORTED') from None


def validate_fixture_echo(data, params):
    if not isinstance(data, dict) or data.get('get') != 'fixtures':
        raise FootballQueryError('ENDPOINT_ECHO_MISMATCH')
    echoed = data.get('parameters')
    # API echoes may stringify integers. Booleans, composites, missing/extra
    # keys and timezone aliases are not equivalent to the actual request.
    if (not isinstance(echoed, dict) or set(echoed) != set(params)
            or any(type(v) not in (str, int) for v in echoed.values())
            or any(type(v) not in (str, int) for v in params.values())
            or any(str(echoed[k]) != str(v) for k, v in params.items())):
        raise FootballQueryError('QUERY_ECHO_MISMATCH')


def _query_boundaries(params):
    boundaries = {}
    for key in ('date', 'from', 'to'):
        if key in params:
            value = params[key]
            try:
                if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
                    raise ValueError
                boundaries[key] = date.fromisoformat(value)
            except ValueError:
                raise FootballQueryError('QUERY_DATE_INVALID') from None
    if 'from' in boundaries and 'to' in boundaries and boundaries['from'] > boundaries['to']:
        raise FootballQueryError('QUERY_DATE_INVALID')
    return boundaries


def validate_fixture_query_parameters(params):
    """Local preflight, with no remote timezone lookup or credential access."""
    return fixture_query_zone(params), _query_boundaries(params)


def fixture_query_row_reason(params, row):
    """Return a fixed rejection or None, using the requested local calendar."""
    try:
        zone, boundaries = validate_fixture_query_parameters(params)
        fixture = row['fixture']
        raw_date = fixture['date']
        kickoff = time(raw_date)
        supplied = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
        local = kickoff.astimezone(zone)
        if (supplied.utcoffset() != local.utcoffset()
                or ('timezone' in fixture and fixture['timezone'] != zone.key)):
            return 'QUERY_TIMEZONE_RESPONSE_MISMATCH'
        for key, boundary in boundaries.items():
            if ((key == 'date' and local.date() != boundary)
                    or (key == 'from' and local.date() < boundary)
                    or (key == 'to' and local.date() > boundary)):
                return 'QUERY_RESPONSE_MISMATCH'
        for key, actual in (('id', fixture['id']), ('league', row['league']['id']),
                            ('season', row['league'].get('season'))):
            if key in params and str(params[key]) != str(actual):
                return 'QUERY_RESPONSE_MISMATCH'
        if 'ids' in params and str(fixture['id']) not in str(params['ids']).split('-'):
            return 'QUERY_RESPONSE_MISMATCH'
        if 'team' in params and str(params['team']) not in {str(row['teams'][s]['id']) for s in ('home', 'away')}:
            return 'QUERY_RESPONSE_MISMATCH'
        if 'status' in params and fixture['status']['short'] not in str(params['status']).split('-'):
            return 'QUERY_RESPONSE_MISMATCH'
        return None
    except FootballQueryError as exc:
        return exc.code
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return 'QUERY_RESPONSE_MALFORMED'


def validate_fixture_query(data, params):
    validate_fixture_echo(data, params)
    validate_fixture_query_parameters(params)  # Empty packets cannot hide invalid queries.
    rows = data.get('response')
    if not isinstance(rows, list):
        raise FootballQueryError('QUERY_RESPONSE_MALFORMED')
    for row in rows:
        reason = fixture_query_row_reason(params, row)
        if reason:
            raise FootballQueryError(reason)
