"""Explicit API checks without odds, credential values or account identity."""
from datetime import datetime, timezone
from .credentials import credential_status
from .football_provider import get, status_summary
from .odds_provider import sports_catalogue


def check():
    result = {'checked_at':datetime.now(timezone.utc).isoformat(),'credentials':credential_status(),
              'providers':{},'execution_enabled':False}
    try:
        football = status_summary(get('status'))
        result['providers']['api_football'] = {
            'status':'OK' if football['subscription_active'] is True else 'SUBSCRIPTION_INACTIVE',**football}
    except (ValueError,OSError,KeyError,TypeError):
        result['providers']['api_football'] = {'status':'FAILED; credential/network/provider response needs checking'}
    try:
        odds = sports_catalogue()
        result['providers']['the_odds_api'] = {'status':'OK','sports':len(odds['data']),
            'football_sports':sum(s.get('key','').startswith('soccer_') for s in odds['data']),
            'receipt':odds['receipt']}
    except (ValueError,OSError,KeyError,TypeError):
        result['providers']['the_odds_api'] = {'status':'FAILED; credential/network/provider response needs checking'}
    result['status'] = 'API_READY' if all(p['status']=='OK' for p in result['providers'].values()) else 'API_CHECK_FAILED'
    return result
