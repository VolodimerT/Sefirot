"""Optional, fail-closed pre-match 1X2 bridge for The Odds API v4.

Only a sealed prediction may request prices. API quotes never become sports
evidence or alter a probability. There is no live or wager endpoint here.
"""
from __future__ import annotations

import http.client
import json
import os
import re
from urllib.parse import urlencode

from .contracts import digest, number, time
from .markets import complete_overround, validate_quote


HOST = 'api.the-odds-api.com'
MAX_RESPONSE = 2_000_000


def _key(value, pattern, label):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f'invalid {label}')
    return value


def _api_key():
    key = os.environ.get('SEFIROT_ODDS_API_KEY', '')
    if not key or key != key.strip():
        raise ValueError('SEFIROT_ODDS_API_KEY is missing or invalid')
    return key


def _get_json(path, params, connection_factory=http.client.HTTPSConnection):
    # No redirects: the key is a query parameter in the provider's v4 contract.
    connection = connection_factory(HOST, timeout=10)
    try:
        connection.request('GET', path + '?' + urlencode(params), headers={'Accept': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f'odds provider HTTP {int(response.status)}; PASS')
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('odds provider response exceeds limit; PASS')
        try:
            payload = json.loads(raw.decode('utf-8'))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('odds provider returned invalid JSON; PASS') from None
        return payload
    except (OSError, http.client.HTTPException):
        # Underlying network errors may contain the request URL and API key.
        raise ValueError('odds provider network error; PASS') from None
    finally:
        connection.close()


def events(sport, api_key=None, connection_factory=http.client.HTTPSConnection):
    """Read the provider's zero-quota event directory, filtering out live games."""
    sport = _key(sport, r'soccer_[a-z0-9_]+', 'soccer sport key')
    data = _get_json(f'/v4/sports/{sport}/events', {'apiKey': api_key or _api_key()}, connection_factory)
    if not isinstance(data, list):
        raise ValueError('odds provider events are malformed; PASS')
    return data


def event_candidates(data, prediction, sport, received_at):
    """Require an exact fixture; do not silently fuzzy-match team aliases."""
    if not isinstance(data, list):
        raise ValueError('events must be a list')
    match = _sealed_match(prediction, received_at)
    found = []
    for event in data:
        if not isinstance(event, dict):
            continue
        try:
            if event['sport_key'] != sport or event['home_team'] != match['home'] or event['away_team'] != match['away']:
                continue
            if time(event['commence_time']) != time(match['kickoff']):
                continue
            _key(event['id'], r'[A-Za-z0-9_-]{4,100}', 'event id')
            found.append({'event_id': event['id'], 'home': match['home'], 'away': match['away'],
                          'kickoff': match['kickoff'], 'sport_key': sport})
        except (KeyError, ValueError, TypeError):
            continue
    if len(found) != 1:
        raise ValueError('fixture missing or ambiguous in odds provider; PASS')
    return found[0]


def _sealed_match(prediction, received_at):
    if not isinstance(prediction, dict) or not prediction.get('captured_prematch') or prediction.get('reconstructed'):
        raise ValueError('only a real prematch sealed prediction can request odds')
    match = prediction['sports']['match']
    if match['sport'] != 'football' or match['format'] != 'REGULATION_90':
        raise ValueError('unsupported match format')
    if time(received_at) < time(prediction['sealed_at']) or time(received_at) >= time(match['kickoff']):
        raise ValueError('price receipt must be prematch after probability seal; PASS')
    return match


def require_prematch_seal(prediction, received_at):
    """Reject an unsealed, reconstructed or already started event before HTTP."""
    return _sealed_match(prediction, received_at)


def event_odds(sport, event_id, region, api_key=None, connection_factory=http.client.HTTPSConnection):
    sport = _key(sport, r'soccer_[a-z0-9_]+', 'soccer sport key')
    event_id = _key(event_id, r'[A-Za-z0-9_-]{4,100}', 'event id')
    region = _key(region, r'(eu|uk|us|us2|au|ca|fr|se|fi)', 'region')
    params = {'apiKey': api_key or _api_key(), 'regions': region, 'markets': 'h2h', 'oddsFormat': 'decimal'}
    return _get_json(f'/v4/sports/{sport}/events/{event_id}/odds', params, connection_factory)


def quotes_from_event(event, prediction, sport, event_id, bookmaker_key, received_at,
                      *, rules_confirmed=False, max_age_seconds=120):
    """Convert one bookmaker's complete regulation-time 1X2 into CORE quotes."""
    match = _sealed_match(prediction, received_at)
    if not rules_confirmed:
        raise ValueError('bookmaker REGULATION_90 settlement must be confirmed; PASS')
    _key(sport, r'soccer_[a-z0-9_]+', 'soccer sport key')
    _key(event_id, r'[A-Za-z0-9_-]{4,100}', 'event id')
    _key(bookmaker_key, r'[a-z0-9_]{2,100}', 'bookmaker key')
    number(max_age_seconds, 'max quote age', 0)
    if not isinstance(event, dict) or event.get('id') != event_id or event.get('sport_key') != sport:
        raise ValueError('provider fixture id/sport mismatch; PASS')
    if event.get('home_team') != match['home'] or event.get('away_team') != match['away'] or time(event['commence_time']) != time(match['kickoff']):
        raise ValueError('provider fixture team/kickoff mismatch; PASS')
    books = [b for b in event.get('bookmakers', []) if isinstance(b, dict) and b.get('key') == bookmaker_key]
    if len(books) != 1:
        raise ValueError('selected bookmaker missing or ambiguous; PASS')
    markets = [m for m in books[0].get('markets', []) if isinstance(m, dict) and m.get('key') == 'h2h']
    if len(markets) != 1:
        raise ValueError('complete 1X2 market is unavailable; PASS')
    market = markets[0]
    observed_at = market.get('last_update', books[0].get('last_update'))
    if not observed_at:
        raise ValueError('quote observation time missing; PASS')
    age = (time(received_at) - time(observed_at)).total_seconds()
    if age < 0 or age > max_age_seconds or time(observed_at) >= time(match['kickoff']):
        raise ValueError('quote time is stale, future or live; PASS')
    names = {match['home']: 'HOME', match['away']: 'AWAY', 'Draw': 'DRAW'}
    outcomes = market.get('outcomes')
    if not isinstance(outcomes, list) or len(outcomes) != 3:
        raise ValueError('complete soccer 1X2 outcomes required; PASS')
    prices = {}
    for outcome in outcomes:
        if not isinstance(outcome, dict) or outcome.get('name') not in names or outcome['name'] in prices:
            raise ValueError('duplicate or unknown soccer 1X2 outcome; PASS')
        prices[outcome['name']] = number(outcome.get('price'), 'decimal odds', 1.00000001, 10000)
    if set(prices) != set(names) or sum(1 / p for p in prices.values()) < 1:
        raise ValueError('incomplete or underround bookmaker line; PASS')
    line_id = digest(['the-odds-api-v4', sport, event_id, bookmaker_key, observed_at])
    quotes = [{'market': {'kind': '1X2', 'side': side}, 'bookmaker': bookmaker_key,
               'odds': prices[name], 'observed_at': observed_at, 'received_at': received_at,
               'phase': 'FINAL', 'rules': 'REGULATION_90', 'line_id': line_id}
              for name, side in ((match['home'], 'HOME'), ('Draw', 'DRAW'), (match['away'], 'AWAY'))]
    for quote in quotes:
        validate_quote(quote, match['kickoff'], received_at, prediction['sealed_at'])
    return {'quotes': quotes, 'receipt': {'provider': 'THE_ODDS_API_V4', 'sport_key': sport,
            'event_id': event_id, 'bookmaker': bookmaker_key, 'received_at': received_at,
            'observed_at': observed_at, 'line_id': line_id, 'overround': complete_overround(quotes)[0]['overround'],
            'rules_verified_by_operator': True, 'available_at_bookmaker': 'UNVERIFIED',
            'fixture_id': match['id']}}
