"""Price-blind, same-fixture goal conjunctions; research only, never admission."""
from functools import lru_cache
from math import prod

from .contracts import digest, integer, number, time
from .engine import market_constraint_issues
from .goal_robustness import create_robustness
from .market_grid import compare_grid, universe
from .markets import market_of, settle
from .probability import distribution

SCHEMA = 'goal-builder-grid-v1'
BRANCHES = ('HOME_WIN_DRY', 'HOME_WIN_BTTS', 'DRAW_0_0', 'DRAW_BTTS',
            'AWAY_WIN_DRY', 'AWAY_WIN_BTTS')


def builder_universe():
    """Fixed before prices: no search over arbitrary combinations or padding."""
    dc = lambda side: {'kind': 'DOUBLE_CHANCE', 'side': side}
    btts = {'kind': 'BTTS', 'side': 'YES'}
    total = lambda side, line: {'kind': 'TOTAL', 'side': side, 'line': line}
    tt = lambda side, line: {'kind': 'TEAM_TOTAL', 'side': side + '_OVER', 'line': line}
    return [[dc('1X'), btts], [dc('X2'), btts],
            [dc('1X'), total('OVER', 1.5)], [dc('X2'), total('OVER', 1.5)],
            [btts, total('OVER', 2.5)],
            [dc('1X'), total('UNDER', 3.5)], [dc('X2'), total('UNDER', 3.5)],
            [{'kind': '1X2', 'side': 'HOME'}, btts], [{'kind': '1X2', 'side': 'AWAY'}, btts],
            [tt('HOME', 1.5), tt('AWAY', .5)],
            [dc('1X'), tt('HOME', 1.5)], [dc('X2'), tt('AWAY', 1.5)],
            [dc('1X'), btts, total('OVER', 2.5)], [dc('X2'), btts, total('OVER', 2.5)]]


@lru_cache(maxsize=50)
def _wins(market):
    return frozenset((h, a) for h in range(36) for a in range(36)
                     if settle(market, h, a) == 'WIN')


def builder_contract(legs):
    if not isinstance(legs, list) or not 2 <= len(legs) <= 3:
        raise ValueError('same-fixture builder requires two or three goal legs')
    markets = [market_of(leg) for leg in legs]
    keys = [m.key for m in markets]
    if len(set(keys)) != len(keys): raise ValueError('duplicate builder leg')
    if any(m.push_possible for m in markets):
        raise ValueError('builder PUSH/repricing rules unsupported; use push-free legs')
    allowed = {market_of(m).key for m in universe()}
    if not set(keys) <= allowed: raise ValueError('builder leg outside frozen goal universe')
    events = [_wins(m) for m in markets]
    joint = frozenset.intersection(*events)
    if not joint: raise ValueError('contradictory builder legs')
    for index in range(len(events)):
        if frozenset.intersection(*(e for i, e in enumerate(events) if i != index)) == joint:
            raise ValueError('redundant implied builder leg')
    return markets, joint


def _branch(score):
    h, a = score
    if h == a: return 'DRAW_BTTS' if h else 'DRAW_0_0'
    return ('HOME_WIN' if h > a else 'AWAY_WIN') + ('_BTTS' if h and a else '_DRY')


def joint_probability(legs, mass):
    """Integrate an AND event over shared score cells; never multiply marginals."""
    markets, joint = builder_contract(legs)
    if not isinstance(mass, dict) or any(s not in _SCORES for s in mass):
        raise ValueError('bounded regulation score distribution required')
    for score in mass:
        for goal in score: integer(goal, 'score goal', 0, 35)
    if abs(sum(number(p, 'score mass', 0, 1) for p in mass.values()) - 1) > 1e-8:
        raise ValueError('score mass must sum to one')
    p = sum(value for score, value in mass.items() if score in joint)
    marginals = [sum(value for score, value in mass.items() if score in _wins(m)) for m in markets]
    branches = {name: sum(value for score, value in mass.items()
                          if score in joint and _branch(score) == name) for name in BRANCHES}
    return {'joint_probability_raw': p, 'marginals_raw': marginals,
            'independence_product_diagnostic': prod(marginals),
            'dependence_gap': p - prod(marginals),
            'fair_odds_raw': 1 / p if p else None,
            'terminal_branch_contributions': branches,
            'terminal_branches_given_win': {k: v / p if p else None for k, v in branches.items()}}


_SCORES = frozenset((h, a) for h in range(36) for a in range(36))


def create_builder_grid(grid, prediction, policy, at):
    history = create_robustness(grid, prediction, policy, at)
    masses, max_tail = {}, 0.
    s = policy.stress_rate_fraction
    for scenario in history['scenarios']:
        if not scenario['available']: continue
        h, a = scenario['rates']['home'], scenario['rates']['away']
        probes = []
        for hm, am in ((1, 1), (1-s, 1-s), (1-s, 1+s), (1+s, 1-s), (1+s, 1+s)):
            mass, tail = distribution(min(12., max(.05, h*hm)), min(12., max(.05, a*am)))
            probes.append(mass); max_tail = max(max_tail, tail)
        masses[scenario['name']] = probes
    rows = []
    for legs in builder_universe():
        markets, cells = builder_contract(legs)
        base = joint_probability(legs, masses['BASELINE'][0])
        sensitivities = [{'name': name, 'joint_probability_raw': sum(m.get(c, 0.) for c in cells),
                          'rate_stress_probabilities_raw': [sum(v.get(c, 0.) for c in cells) for v in probes[1:]]}
                         for name, probes in masses.items() for m in probes[:1]]
        floor = min(p for row in sensitivities for p in
                    [row['joint_probability_raw'], *row['rate_stress_probabilities_raw']])
        selection_issues = [issue for market in markets for issue in
                            market_constraint_issues(market, grid['selection_constraints'])]
        rows.append({'key': ' AND '.join(sorted(m.key for m in markets)), 'legs': legs, **base,
                     'selection_issues': selection_issues,
                     'selection_status': 'BLOCKED_BY_SCENARIO' if selection_issues else 'NO_EXPLICIT_CONFLICT',
                     'history_sensitivity': sensitivities, 'sensitivity_probability_min': floor,
                     'sensitivity_break_even_odds_raw': 1 / floor if floor else None,
                     'confidence_interval': False, 'builder_odds': None, 'builder_ev': None,
                     'class': 'D', 'stake': 0., 'monetary_permission': False})
    output = {'schema': SCHEMA, 'prediction_id': prediction['id'], 'sealed_at': at,
              'match': grid['match'], 'grid': grid, 'grid_hash': grid['hash'],
              'passport': history['passport'], 'universe_hash': digest(builder_universe()),
              'method': 'Exact conjunction over BASELINE_V1 score cells; push-free REGULATION_90',
              'candidates': rows, 'candidate_count': len(rows), 'tail_bound': max_tail,
              'terminal_scenarios_raw': {name: sum(p for score, p in masses['BASELINE'][0].items()
                                                 if _branch(score) == name) for name in BRANCHES},
              'history_status': history['status'], 'source_blockers': history['source_blockers'],
              'unmodelled_death_tests': ['FIRST_GOAL_PATH', 'LEVEL_AT_60', 'TEMPO', 'ATTACKER_ABSENCE', 'REFEREE_VARIANCE'],
              'unsupported_joint_dimensions': ['SHOTS', 'CORNERS', 'FOULS', 'CARDS'],
              'calibration_applied': False, 'joint_calibration_status': 'UNVALIDATED',
              'quotes_read': False, 'class': 'D', 'stake': 0., 'monetary_permission': False,
              'execution_enabled': False, 'holdout_eligible': False,
              'limitations': ['Dependence follows the raw goal model; it is not empirical joint calibration.',
                              'Terminal scores are not a first-goal or minute-by-minute scenario model.',
                              'No combined API quote: joint EV and superiority to singles remain unknown.',
                              'Receipt hashes bind content, not provider authenticity.']}
    output['hash'] = digest(output)
    return output


def compare_builder_singles(report, prediction, quotes, policy, at, receipt=None):
    if not isinstance(report, dict): raise ValueError('builder report required')
    saved = dict(report); signature = saved.pop('hash', None)
    if report.get('schema') != SCHEMA or digest(saved) != signature:
        raise ValueError('builder hash/schema mismatch')
    if time(report['sealed_at']) > time(at): raise ValueError('future builder seal')
    if report != create_builder_grid(report['grid'], prediction, policy, report['sealed_at']):
        raise ValueError('builder report does not reproduce')
    if not isinstance(quotes, list) or len(quotes) > 1000: raise ValueError('bounded single quote list required')
    # Quotes must arrive after the builder freeze as well as after the source grid.
    if any(time(q['received_at']) < time(report['sealed_at']) for q in quotes):
        raise ValueError('single price received before builder freeze')
    singles = compare_grid(report['grid'], prediction, quotes, policy, at, receipt)
    eligible = [(r, p) for r in singles['candidates'] if not r['selection_issues'] for p in r['prices']]
    ranked = sorted(eligible, key=lambda item: (-item[1]['raw_stress_ev_min'], -item[1]['ev_raw'],
                                             item[0]['key'], item[1]['bookmaker']))
    best = ({'key': ranked[0][0]['key'], 'market': ranked[0][0]['market'], **ranked[0][1],
             'selection': 'RAW_STRESS_EV_THEN_RAW_EV; research diagnostic only'} if ranked else None)
    output = {'schema': 'builder-single-comparison-v1', 'at': at, 'builder_hash': report['hash'],
              'prediction_id': prediction['id'], 'quotes_hash': digest(quotes), 'api_receipt_hash': digest(receipt),
              'best_single_diagnostic': best, 'priced_single_count': singles['priced_count'],
              'status': 'MISSING_API_BUILDER_QUOTE', 'candidates': report['candidates'],
              'builder_beats_best_single': None, 'joint_calibration_status': 'UNVALIDATED',
              'class': 'D', 'stake': 0., 'monetary_permission': False, 'execution_enabled': False}
    output['hash'] = digest(output)
    return output
