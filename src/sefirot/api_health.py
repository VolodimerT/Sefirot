"""Explicit catalogue checks without prices, account identity or execution."""
from datetime import datetime, timezone
import re

from .credentials import credential_status
from .football_provider import FootballRequestError, status_summary
from .football_gateway import get_sports as get, transport_status
from .odds_provider import sports_catalogue


def _missing():
    return {'status': 'CREDENTIAL_UNAVAILABLE', 'request_attempted': False,
            'reason': 'MISSING_OR_INVALID_CREDENTIAL'}


def _failure(exc):
    result = {'status': 'REQUEST_FAILED', 'request_attempted': True,
              'reason': 'NETWORK_OR_PROVIDER_RESPONSE'}
    if isinstance(exc, FootballRequestError):
        result['reason'] = exc.code
    else:
        # Only match the providers' fixed public HTTP errors, never echo text.
        match = re.fullmatch(r'(?:provider|odds provider|sports gateway) HTTP ([1-5][0-9]{2})(?:; PASS)?', str(exc))
        if match:
            result.update(reason='HTTP_ERROR', http_status=int(match.group(1)))
    return result


def _stake_check(credentials):
    scope = {'scope': 'EVENT_CATALOGUE_ONLY', 'market_access': 'NOT_CHECKED',
             'settlement': 'UNVERIFIED', 'freshness': 'RECEIPT_TIME_ONLY',
             'monetary_permission': False, 'execution_enabled': False}
    if credentials['STAKE_API_TOKEN'] != 'CONFIGURED':
        return {**scope, **_missing()}
    from .stake_provider import StakeRequestError, sports_events
    try:
        packet = sports_events(first=5, sport_slug='soccer', match_type='upcoming')
        return {**scope, 'status': 'OK', 'request_attempted': True,
                'events': len(packet['events']), 'event_limit': 5,
                'receipt': packet['receipt']}
    except StakeRequestError as exc:
        reason = {'401': 'HTTP_AUTH_REJECTED', '403': 'HTTP_ACCESS_DENIED',
                  '429': 'HTTP_RATE_LIMITED'}.get(str(exc.http_status), exc.code)
        return {**scope, 'status': 'REQUEST_FAILED', 'request_attempted': True,
                'reason': reason, 'http_status': exc.http_status}
    except (ValueError, OSError, KeyError, TypeError):
        return {**scope, 'status': 'REQUEST_FAILED', 'request_attempted': True,
                'reason': 'NETWORK_OR_PROVIDER_RESPONSE'}


def check(*, odds_provider='the-odds-api'):
    if odds_provider not in {'the-odds-api', 'stake'}:
        raise ValueError('unsupported health-check odds provider')
    credentials, transport = credential_status(), transport_status()
    result = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'credentials': credentials, 'providers': {},
              'football_transport': transport, 'odds_provider': odds_provider,
              'admission_ready': False, 'monetary_permission': False,
              'execution_enabled': False}
    if not transport['credential_configured']:
        result['providers']['api_football'] = _missing()
    else:
        try:
            football = status_summary(get('status'))
            result['providers']['api_football'] = {
                'status': 'OK' if football['subscription_active'] is True else 'SUBSCRIPTION_INACTIVE',
                'request_attempted': True, **football}
        except (ValueError, OSError, KeyError, TypeError) as exc:
            result['providers']['api_football'] = _failure(exc)
    if odds_provider == 'stake':
        result['providers']['stake'] = _stake_check(credentials)
    elif credentials['SEFIROT_ODDS_API_KEY'] != 'CONFIGURED':
        result['providers']['the_odds_api'] = _missing()
    else:
        try:
            odds = sports_catalogue()
            result['providers']['the_odds_api'] = {
                'status': 'OK', 'request_attempted': True, 'sports': len(odds['data']),
                'football_sports': sum(s.get('key', '').startswith('soccer_') for s in odds['data']),
                'receipt': odds['receipt']}
        except (ValueError, OSError, KeyError, TypeError) as exc:
            result['providers']['the_odds_api'] = _failure(exc)
    ready = all(p['status'] == 'OK' for p in result['providers'].values())
    result['status'] = ('RESEARCH_API_READY' if odds_provider == 'stake' else 'API_READY') if ready else 'API_CHECK_FAILED'
    return result
