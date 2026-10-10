"""Predeclared probes of the archived BASELINE, never new sporting facts."""
from copy import deepcopy

from sefirot.contracts import Policy, number, time
from sefirot.markets import market_of, probabilities
from sefirot.probability import distribution, estimate

LAMBDA_FRACTION = .10
REVIEW_DELTA = .05


def simplex(vector):
    if not isinstance(vector, (list, tuple)) or len(vector) != 3:
        raise ValueError('three stress probabilities required')
    values = [number(p, 'stress probability', 0, 1) for p in vector]
    if abs(sum(values) - 1) > 1e-8:
        raise ValueError('stress probability simplex')
    return values


def project(prediction, mass):
    return {c['key']: simplex(probabilities(market_of(c['market']), mass))
            for c in prediction['candidates']}


def run_lab(prediction):
    policy = Policy(**prediction['policy'])
    if policy.goal_model != 'BASELINE_V1':
        return {'status': 'UNKNOWN', 'reason': 'ORIGINAL_DISTRIBUTION_ADAPTER_MISSING',
                'scenarios': [], 'monetary_permission': False}
    original = prediction['model']['rates']
    home, away = [number(original[k], 'archived lambda', .01, 12) for k in ('home', 'away')]
    mass, _ = distribution(home, away)
    base = project(prediction, mass)
    scenarios = []

    def add(name, rates, mass, removed=()):
        vectors = project(prediction, mass)
        scenarios.append({'name': name, 'label': 'SENSITIVITY_ONLY', 'rates': rates,
                          'removed_history_ids': list(removed), 'probabilities': vectors,
                          'max_absolute_win_delta': max(abs(vectors[k][0] - base[k][0]) for k in base),
                          'is_observed_event': False, 'probability_adjustment_allowed': False})

    for hsign, asign in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        h, a = [min(12., max(.01, v * (1 + sign * LAMBDA_FRACTION)))
                for v, sign in ((home, hsign), (away, asign))]
        changed, _ = distribution(h, a)
        add(f'lambda_{hsign:+d}_{asign:+d}', {'home': h, 'away': a}, changed)

    used = prediction['model']['used_history']
    rows = {r['id']: r for r in prediction['sports']['history']}
    if len(set(used)) != len(used) or any(rid not in rows for rid in used):
        raise ValueError('invalid original history identities')
    cutoff = time(prediction['sports']['as_of'])
    for rid in used:
        r = rows[rid]
        if r['id'] == prediction['sports']['match']['id'] or time(r['received_at']) > cutoff:
            raise ValueError('future or target result in sensitivity input')
    # Selection is fixed by historical goals/identity, never by the target outcome.
    if used:
        largest = max(used, key=lambda rid: (rows[rid]['home_goals'] + rows[rid]['away_goals'], rid))
        removals = [('largest_historical_score', [largest])]
        for side in ('home', 'away'):
            team = prediction['sports']['match'][side]
            removals.append(('remove_' + side + '_team',
                             [rid for rid in used if team in (rows[rid]['home'], rows[rid]['away'])]))
        leagues = sorted({rows[rid]['league'] for rid in used})
        for index, league in enumerate(leagues):
            removals.append((f'remove_league_{index}', [rid for rid in used if rows[rid]['league'] == league]))
        for name, removed in removals:
            sports = deepcopy(prediction['sports'])
            sports['history'] = [rows[rid] for rid in used if rid not in removed]
            changed, _, summary = estimate(sports, policy)
            add(name, summary['rates'], changed, sorted(removed))
    return {'status': 'SENSITIVITY_ONLY', 'lambda_fraction': LAMBDA_FRACTION,
            'review_delta': REVIEW_DELTA, 'range_registered_in_code': True,
            'baseline_projection': base, 'scenarios': scenarios,
            'season_probe': 'UNKNOWN_NO_SEASON_FIELD', 'lineup_effect': 'UNKNOWN_NO_VALIDATED_EFFECT_MODEL',
            'confidence_interval': False, 'monetary_permission': False}
