"""Optional, fail-closed pre-match main-market bridge for The Odds API v4.

Only a sealed prediction may request prices. API quotes never become sports
evidence or alter a probability. There is no live or wager endpoint here.
"""
from __future__ import annotations

import http.client
import json
import re
from urllib.parse import urlencode
from .credentials import credential
from .provider_transport import ProviderConnection, request_json

from .contracts import digest, number, time
from .markets import complete_overround, validate_quote, market_of


HOST = 'api.the-odds-api.com'
MAX_RESPONSE = 2_000_000
MARKET_KEYS = ('h2h', 'draw_no_bet', 'spreads', 'alternate_spreads',
               'totals', 'alternate_totals', 'btts', 'team_totals', 'alternate_team_totals')
FAMILY_KEYS = {'1X2': 'h2h', 'DNB': 'draw_no_bet', 'HANDICAP': 'spreads',
               'TOTAL': 'totals', 'BTTS': 'btts', 'TEAM_TOTAL': 'team_totals'}


def request_markets(keys):
    if not isinstance(keys, (list, tuple)) or not keys or len(keys) > len(MARKET_KEYS):
        raise ValueError('bounded main-market request required')
    if any(not isinstance(key, str) or key not in MARKET_KEYS for key in keys) or len(set(keys)) != len(keys):
        raise ValueError('unsupported or duplicate provider market')
    return tuple(key for key in MARKET_KEYS if key in keys)


def keys_for_candidates(candidates, *, alternate=False):
    kinds = {market_of(c['market']).kind for c in candidates}
    keys = [key for kind, key in FAMILY_KEYS.items() if kind in kinds]
    if alternate:
        keys += ['alternate_' + key for key in ('spreads', 'totals', 'team_totals') if key in keys]
    return request_markets(keys)


def _key(value, pattern, label):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f'invalid {label}')
    return value


def _api_key():
    return credential('SEFIROT_ODDS_API_KEY')


def _get_json(path, params, connection_factory=ProviderConnection):
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


def sports_catalogue(api_key=None, connection_factory=ProviderConnection):
    packet = request_json(HOST, '/v4/sports/', {}, {},
                          query_credential=api_key or _api_key(), connection_factory=connection_factory)
    if not isinstance(packet['data'], list):
        raise ValueError('odds provider sports directory malformed')
    return packet


def events(sport, api_key=None, connection_factory=ProviderConnection):
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


def event_odds(sport, event_id, region, api_key=None, connection_factory=ProviderConnection,
               *, market_keys=('h2h',), bookmaker_key=None):
    sport = _key(sport, r'soccer_[a-z0-9_]+', 'soccer sport key')
    event_id = _key(event_id, r'[A-Za-z0-9_-]{4,100}', 'event id')
    region = _key(region, r'(eu|uk|us|us2|au|ca|fr|se|fi)', 'region')
    params = {'apiKey': api_key or _api_key(), 'regions': region,
              'markets': ','.join(request_markets(market_keys)), 'oddsFormat': 'decimal'}
    if bookmaker_key is not None:
        params['bookmakers'] = _key(bookmaker_key, r'[a-z0-9_]{2,100}', 'bookmaker key')
    return _get_json(f'/v4/sports/{sport}/events/{event_id}/odds', params, connection_factory)


def quotes_from_event(event, prediction, sport, event_id, bookmaker_key, received_at,
                      *, rules_confirmed=False, max_age_seconds=120, market_keys=('h2h',)):
    """Import complete partitions only; never combine timestamps/books/lines.

    Expanded imports retain rejected lines and absent sealed candidates. The
    original h2h-only call remains strict and backward compatible.
    """
    requested = request_markets(market_keys)
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
    if requested != ('h2h',):
        return _main_quotes(books[0], prediction, sport, event_id, bookmaker_key,
                            received_at, requested, max_age_seconds, event)
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
            'quotes_hash': digest(quotes), 'payload_hash': digest(event),
            'rules_verified_by_operator': True, 'available_at_bookmaker': 'UNVERIFIED',
            'fixture_id': match['id']}}


def _outcome_contract(key, outcome, match):
    if not isinstance(outcome, dict):
        raise ValueError('malformed outcome')
    name = outcome.get('name')
    teams = {match['home']: 'HOME', match['away']: 'AWAY'}
    if len(teams) != 2 or 'Draw' in teams:
        raise ValueError('ambiguous team names')
    if key == 'h2h':
        sides = {**teams, 'Draw': 'DRAW'}
        if name not in sides: raise ValueError('unknown 1X2 outcome')
        contract = {'kind': '1X2', 'side': sides[name]}
    elif key == 'draw_no_bet':
        if name not in teams: raise ValueError('unknown DNB outcome')
        contract = {'kind': 'DNB', 'side': teams[name]}
    elif key == 'btts':
        if name not in ('Yes', 'No'): raise ValueError('unknown BTTS outcome')
        contract = {'kind': 'BTTS', 'side': name.upper()}
    else:
        point = number(outcome.get('point'), 'line', -100, 100)
        point = 0. if point == 0 else point
        if key.endswith('spreads'):
            if name not in teams: raise ValueError('unknown handicap team')
            contract = {'kind': 'HANDICAP', 'side': teams[name], 'line': point}
        else:
            if name not in ('Over', 'Under'): raise ValueError('unknown total outcome')
            if key.endswith('team_totals'):
                team = outcome.get('description')
                if team not in teams: raise ValueError('unknown team-total description')
                contract = {'kind': 'TEAM_TOTAL', 'side': teams[team] + '_' + name.upper(), 'line': point}
            else:
                contract = {'kind': 'TOTAL', 'side': name.upper(), 'line': point}
    market = market_of(contract)  # Reject quarter lines before assigning quotes.
    odds = number(outcome.get('price'), 'decimal odds', 1.00000001, 10000)
    if market.kind == 'HANDICAP':
        partition = (market.kind, market.line if market.side == 'HOME' else -market.line)
    elif market.kind == 'TEAM_TOTAL':
        partition = (market.kind, market.side.split('_')[0], market.line)
    else:
        partition = (market.kind, market.line)
    return partition, market, contract, odds


def _main_quotes(book, prediction, sport, event_id, bookmaker, received, requested, max_age, event):
    match = prediction['sports']['match']; quotes = []; rejected = []; imported = []; seen = set()
    markets = book.get('markets')
    if not isinstance(markets, list): raise ValueError('malformed bookmaker markets; PASS')
    for key in requested:
        blocks = [m for m in markets if isinstance(m, dict) and m.get('key') == key]
        if not blocks:
            rejected.append({'provider_market': key, 'reason': 'MARKET_UNAVAILABLE'}); continue
        if len(blocks) != 1:
            rejected.append({'provider_market': key, 'reason': 'AMBIGUOUS_MARKET'}); continue
        block = blocks[0]
        observed = block.get('last_update', book.get('last_update'))
        try:
            age = (time(received) - time(observed)).total_seconds()
            if not 0 <= age <= max_age or time(observed) >= time(match['kickoff']):
                raise ValueError('stale, future or live timestamp')
            outcomes = block.get('outcomes')
            if not isinstance(outcomes, list) or not 1 <= len(outcomes) <= 256:
                raise ValueError('bounded outcomes required')
            partitions = {}
            for outcome in outcomes:
                partition, market, contract, odds = _outcome_contract(key, outcome, match)
                partitions.setdefault(partition, []).append((market, contract, odds))
        except (ValueError, TypeError, KeyError):
            # Reject the whole provider market if an outcome cannot be assigned
            # safely. Never salvage a duplicate or guess its opposite line.
            rejected.append({'provider_market': key, 'reason': 'INVALID_MARKET_OR_TIME'}); continue
        for partition, rows in sorted(partitions.items(), key=lambda item: repr(item[0])):
            kind = partition[0]
            expected = ({'HOME', 'DRAW', 'AWAY'} if kind == '1X2' else
                        {'HOME', 'AWAY'} if kind in ('HANDICAP', 'DNB') else
                        {'YES', 'NO'} if kind == 'BTTS' else
                        {partition[1] + '_OVER', partition[1] + '_UNDER'} if kind == 'TEAM_TOTAL' else {'OVER', 'UNDER'})
            sides = [row[0].side for row in rows]
            reason = ('INCOMPLETE_OR_DUPLICATE_LINE' if len(rows) != len(expected) or set(sides) != expected
                      else 'UNDERROUND_LINE' if sum(1/row[2] for row in rows) < 1 else None)
            if reason:
                rejected.append({'provider_market': key, 'partition': list(partition), 'reason': reason}); continue
            line_id = digest(['the-odds-api-v4', sport, event_id, bookmaker, key, observed, partition])
            line_quotes = [{'market': contract, 'bookmaker': bookmaker, 'odds': odds,
                            'observed_at': observed, 'received_at': received, 'phase': 'FINAL',
                            'rules': 'REGULATION_90', 'line_id': line_id}
                           for _, contract, odds in sorted(rows, key=lambda row: row[0].key)]
            # Featured and alternate blocks can repeat the same contract. Keep
            # the featured quote rather than shopping prices inside an import.
            for quote in line_quotes:
                validate_quote(quote, match['kickoff'], received, prediction['sealed_at'])
            if any(market_of(q['market']).key in seen for q in line_quotes):
                rejected.append({'provider_market': key, 'partition': list(partition), 'reason': 'DUPLICATE_CONTRACT_SOURCE'}); continue
            quotes.extend(line_quotes); seen.update(market_of(q['market']).key for q in line_quotes)
            imported.append({'provider_market': key, 'line_id': line_id, 'observed_at': observed,
                             'partition': list(partition), 'overround': sum(1/row[2] for row in rows)-1})
    if not quotes: raise ValueError('no complete supported main-market lines; PASS')
    return {'quotes': quotes, 'receipt': {'provider': 'THE_ODDS_API_V4', 'sport_key': sport,
            'event_id': event_id, 'bookmaker': bookmaker, 'received_at': received,
            'fixture_id': match['id'], 'requested_markets': list(requested), 'lines': imported,
            'rejected_lines': rejected, 'payload_hash': digest(event), 'quotes_hash': digest(quotes), 'overround': None,
            'missing_candidates': sorted(market_of(c['market']).key for c in prediction['candidates']
                                         if market_of(c['market']).key not in seen),
            'rules_verified_by_operator': True, 'available_at_bookmaker': 'UNVERIFIED'}}
