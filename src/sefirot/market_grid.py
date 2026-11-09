"""Frozen, price-blind main-market research; no monetary admission or journal writes."""
from .contracts import digest, time
from .engine import prepare, market_constraint_issues
from .identity import code_hash, model_code_hash
from .markets import market_of, probabilities, settle, validate_quote, payoff_ev, implied, market_reference
from .odds_provider import require_prematch_seal
from .probability import estimate, calibrate, ev_bounds

SCHEMA = 'main-market-grid-v1'


def _facts_first(prediction):
    """Present only sealed sports evidence; no market price enters this stage."""
    sports = prediction['sports']
    sources = {row['id']: row for row in sports['sources']}
    facts = []
    for key, row in sorted(prediction['witness']['resolved'].items()):
        source = sources[row['source_id']]
        facts.append({'id': row['id'], 'key': key, 'value': row['value'],
                      'kind': 'FACT', 'source_id': row['source_id'],
                      'source_group': source['independence_group'],
                      'source_reliability_asserted': source['reliability'],
                      'observed_at': row['observed_at'],
                      'published_at': row['published_at'],
                      'received_at': row['received_at']})
    return {'scenario': prediction['scenario']['type'],
            'facts': facts,
            'model_team_games': list(prediction['model']['team_games']),
            'history_rows_supplied': len(sports['history']),
            'source_issues': [issue['code'] for issue in prediction['issues']],
            'missing_metrics': ['XG_XGA_NOT_IN_CORE_SPORTS_CONTRACT',
                                'PLAYER_ROLES_NOT_VERIFIED',
                                'REST_AND_SCHEDULE_NOT_VERIFIED'],
            'fact_direction_for_market': 'NOT_INFERRED_FROM_FACT_LIST',
            'source_independence_from_bookmaker_lines': 'NOT_ATTESTED',
            'price_inputs_read': False}




def universe():
    """Fifty fixed regulation-time contracts, independent of prices/results."""
    rows = [{'kind': '1X2', 'side': side} for side in ('HOME', 'DRAW', 'AWAY')]
    rows += [{'kind': 'DOUBLE_CHANCE', 'side': side} for side in ('1X', 'X2', '12')]
    rows += [{'kind': 'DNB', 'side': side} for side in ('HOME', 'AWAY')]
    rows += [{'kind': 'HANDICAP', 'side': side, 'line': line}
             for side in ('HOME', 'AWAY') for line in (-1.5, -1., -.5, 0., .5, 1., 1.5)]
    rows += [{'kind': 'TOTAL', 'side': side, 'line': line}
             for side in ('OVER', 'UNDER') for line in (1.5, 2., 2.5, 3., 3.5)]
    rows += [{'kind': 'BTTS', 'side': side} for side in ('YES', 'NO')]
    rows += [{'kind': 'TEAM_TOTAL', 'side': team + '_' + side, 'line': line}
             for team in ('HOME', 'AWAY') for side in ('OVER', 'UNDER') for line in (.5, 1., 1.5, 2.)]
    return rows


def create_grid(prediction, policy, at):
    require_prematch_seal(prediction, at)
    if prediction['code_hash'] != code_hash() or prediction['model_hash'] != model_code_hash() or prediction['policy_hash'] != policy.fingerprint:
        raise ValueError('grid requires the original prediction build and policy')
    # Reproduce sporting results from the saved snapshot. A caller cannot
    # replace sealed probabilities with a different, price-driven distribution.
    original = prepare(prediction['sports'], prediction['market_pool'], policy,
                       prediction['calibrator'], prediction['goal_model'])
    if digest(original['candidates']) != digest(prediction['candidates']) or digest(original['model']) != digest(prediction['model']):
        raise ValueError('sealed sporting output does not reproduce')
    mass, variants, model = estimate(prediction['sports'], policy, prediction['goal_model'])
    sports_facts = _facts_first(prediction)
    rows = []
    for contract in universe():
        market = market_of(contract); raw = probabilities(market, mass)
        selection_issues = market_constraint_issues(market, original['scenario']['selection_constraints'])
        calibration = calibrate(market, raw, prediction['calibrator'], policy, model['competition_profile'])
        stresses = [probabilities(market, variant) for variant in variants]
        # The grid exposes sporting sensitivity and calibration separately.
        # Neither the rate envelope nor its min/max is a confidence interval.
        rows.append({'market': contract, 'key': market.key, 'raw': list(raw),
                     'base': calibration['base'], 'calibration': calibration['status'],
                     'calibration_n': calibration['n'], 'calibration_low': calibration['low'],
                     'calibration_high': calibration['high'],
                     'stress_probabilities': [list(p) for p in stresses],
                     'selection_issues': selection_issues,
                     'sports_scenario': {
                         'fact_ids': [fact['id'] for fact in sports_facts['facts']],
                         'model_raw_outcomes': list(raw),
                         'market_support_from_facts': 'NOT_VERIFIED',
                         'market_contradictions': [issue['code'] for issue in selection_issues],
                         'missing': sports_facts['missing_metrics']},
                     'selection_status': 'BLOCKED_BY_SCENARIO' if selection_issues else 'NO_EXPLICIT_CONFLICT',
                     'death_test': {'loss_probability_raw': raw[2],
                         'top_score_losses': [s for s in model['score_scenarios']
                                              if settle(market, s['home'], s['away']) == 'LOSS']},
                     'class': 'C', 'class_reason': 'PRICE_NOT_READ_AND_MODEL_UNVALIDATED',
                     'verdict': 'RESEARCH_ONLY', 'stake': 0.})
    grid = {'schema': SCHEMA, 'prediction_id': prediction['id'], 'match': prediction['sports']['match'],
            'sealed_at': at, 'source_sealed_at': prediction['sealed_at'],
            'code_hash': prediction['code_hash'], 'model_hash': prediction['model_hash'],
            'policy_hash': prediction['policy_hash'], 'universe_hash': digest(universe()),
            'candidates': rows, 'sports_facts': sports_facts, 'source_issues': prediction['issues'],
            'selection_constraints': original['scenario']['selection_constraints'],
            'synthetic': prediction['synthetic'], 'quotes_read': False,
            'monetary_permission': False, 'execution_enabled': False,
            'selection_validation': 'UNVALIDATED_EXPANDED_UNIVERSE',
            'uncertainty': 'Calibration bounds separate from raw rate sensitivity; no claimed coverage'}
    grid['hash'] = digest(grid)
    return grid


def validate_grid(grid, prediction, policy, at):
    if not isinstance(grid, dict): raise ValueError('grid object required')
    saved = dict(grid); signature = saved.pop('hash', None)
    if digest(saved) != signature or grid.get('schema') != SCHEMA:
        raise ValueError('grid hash/schema mismatch')
    if time(grid['sealed_at']) > time(at): raise ValueError('future grid seal')
    expected = create_grid(prediction, policy, grid['sealed_at'])
    if expected != grid: raise ValueError('grid differs from its fixed sporting universe')
    require_prematch_seal(prediction, at)
    return grid


def compare_grid(grid, prediction, quotes, policy, at, receipt=None):
    validate_grid(grid, prediction, policy, at)
    if not isinstance(quotes, list) or len(quotes) > 1000: raise ValueError('bounded quote list required')
    if (not isinstance(receipt, dict) or receipt.get('provider') != 'THE_ODDS_API_V4'
        or receipt.get('quotes_hash') != digest(quotes) or receipt.get('grid_hash') != grid['hash']
        or receipt.get('fixture_id') != grid['match']['id']):
        raise ValueError('matching API receipt required; manual or altered quotes rejected')
    by_key = {}; eligible_quotes = []
    for quote in quotes:
        if quote.get('bookmaker') != receipt.get('bookmaker') or quote.get('received_at') != receipt.get('received_at'):
            raise ValueError('quote differs from API receipt')
        market = validate_quote(quote, grid['match']['kickoff'], at, grid['sealed_at'])
        if quote['phase'] not in ('FINAL', 'ENTRY'): continue
        age = (time(at) - time(quote['observed_at'])).total_seconds()
        if age > policy.quote_max_age_seconds: continue
        by_key.setdefault(market.key, []).append(quote)
        eligible_quotes.append(quote)
    rows = []
    for candidate in grid['candidates']:
        sources = by_key.get(candidate['key'], [])
        prices = []
        for quote in sorted(sources, key=lambda q: (q['bookmaker'], q['observed_at'], q.get('line_id', ''), q['odds'])):
            base = candidate['base']; odds = quote['odds']
            low, high = ev_bounds(candidate['calibration_low'], candidate['calibration_high'], odds)
            prices.append({'bookmaker': quote['bookmaker'], 'odds': odds,
                           'observed_at': quote['observed_at'], 'line_id': quote.get('line_id'),
                           'implied_probability': implied(odds),
                           'ev_raw': payoff_ev(*candidate['raw'][:2], odds),
                           'ev_base': payoff_ev(*base[:2], odds),
                           'calibration_ev_low': low, 'calibration_ev_high': high,
                           'raw_stress_ev_min': min(payoff_ev(*p[:2], odds) for p in candidate['stress_probabilities']),
                           'market_reference': market_reference(eligible_quotes, quote, *base[:2]),
                           'reference_interpretation': 'BENCHMARK_NOT_TRUE_PROBABILITY',
                           'validated_probability': None, 'validated_ev': None,
                           'ev_reliability': 'RAW_OR_BIN_DIAGNOSTIC_NOT_HOLDOUT_VERIFIED',
                           'tactical_fit': 'SOURCE_SEAL_ONLY; no added sporting facts',
                           'public_trap': 'UNASSESSED; no public positioning data'})
        critical_source = any(issue['code'] in ('FIXTURE_IDENTITY_CONFLICT',
            'UNRESOLVED_CONFLICT', 'LIVE_FORBIDDEN', 'UNSUPPORTED_FORMAT',
            'CALIBRATION_COHERENCE_CONFLICT') for issue in grid['source_issues'])
        conflict = critical_source or any(issue['code'] == 'SCENARIO_MARKET_CONFLICT'
                       for issue in candidate['selection_issues'])
        reason = ('CRITICAL_SOURCE_CONFLICT' if critical_source else
                  'SCENARIO_MARKET_CONFLICT' if conflict else
                  'PRICE_MISSING_OR_STALE' if not prices else
                  'SELECTION_AND_HOLDOUT_UNVALIDATED')
        rows.append({**candidate, 'prices': prices, 'price_status': 'PRICED' if prices else 'MISSING_OR_STALE',
                     'class': 'RED' if conflict else 'C', 'class_reason': reason,
                     'decision': 'PASS', 'bet_eligible': False,
                     'verdict': 'RESEARCH_ONLY', 'monetary_permission': False})
    return {'schema': 'main-market-comparison-v1', 'grid_hash': grid['hash'],
            'prediction_id': prediction['id'], 'at': at, 'candidates': rows,
            'candidate_count': len(rows), 'priced_count': sum(bool(row['prices']) for row in rows),
            'quotes_hash': digest(quotes), 'api_receipt_hash': digest(receipt),
            'provenance': 'Local API adapter receipt; content binding, not a provider digital signature',
            'monetary_permission': False, 'execution_enabled': False,
            'selection_validation': grid['selection_validation'],
            'next_action': 'Validate the full frozen selection procedure on unseen matches; EV alone grants no admission'}
