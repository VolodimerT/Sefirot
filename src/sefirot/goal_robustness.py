"""Frozen history perturbations; raw research diagnostics, never a new model fit."""
from copy import deepcopy
from math import ceil

from .action_plan import passport
from .contracts import digest, time
from .evidence import eligible_history
from .market_grid import validate_grid, compare_grid, universe
from .markets import market_of, probabilities, payoff_ev, validate_quote
from .probability import estimate, grade_stress

SCHEMA = 'goal-history-robustness-v1'
METHOD = {'version': 'fixed-history-perturbations-v1', 'recent_games': 5,
          'percentile': .75, 'outlier_rule': 'highest total goals among eligible target-team fixtures; latest kickoff then id breaks ties',
          'cap_rule': 'nearest-rank P75 of each target team historical goals; cap its goals in its last five eligible fixtures',
          'calibration_applied': False, 'refit': False,
          'scope': 'BASELINE_V1 raw sensitivity only; no inferred optimal parameters'}


def _scenario(sports, policy, name, changes, available):
    mass, stresses, model = estimate(sports, policy)
    candidates = []
    for contract in universe():
        market = market_of(contract)
        candidates.append({'key': market.key, 'market': contract,
                           'raw': list(probabilities(market, mass)),
                           'raw_stress_probabilities': [list(probabilities(market, v)) for v in stresses]})
    return {'name': name, 'available': available, 'changes': changes,
            'counterfactual': name != 'BASELINE', 'rates': model['rates'],
            'team_games': model['team_games'], 'history_digest': model['history_digest'],
            'history_sufficient': min(model['team_games']) >= policy.min_team_games,
            'candidates': candidates}


def create_robustness(grid, prediction, policy, at):
    validate_grid(grid, prediction, policy, at)
    if policy.goal_model != 'BASELINE_V1':
        raise ValueError('history robustness requires BASELINE_V1; fitted challengers need a separate experiment')
    rows, excluded = eligible_history(prediction['sports'], policy)
    targets = {prediction['sports']['match'][side] for side in ('home', 'away')}
    target_rows = [r for r in rows if targets.intersection((r['home'], r['away']))]
    sports = deepcopy(prediction['sports'])
    # Use only admissible history; excluded late/foreign observations must not
    # influence perturbation selection, caps, priors or apparent completeness.
    sports['history'] = deepcopy(rows)
    baseline = _scenario(sports, policy, 'BASELINE', [], True)
    dropped = deepcopy(sports)
    largest = max(target_rows, key=lambda r: (r['home_goals'] + r['away_goals'], time(r['kickoff']), r['id']), default=None)
    removed = []
    if largest:
        dropped['history'] = [r for r in dropped['history'] if r['id'] != largest['id']]
        removed = [{'id': largest['id'], 'operation': 'REMOVE_FIXTURE',
                    'original_score': [largest['home_goals'], largest['away_goals']]}]
    capped = deepcopy(sports)
    thresholds = {}
    recent = {}
    for team in sorted(targets):
        games = [r for r in rows if team in (r['home'], r['away'])]
        values = sorted(r['home_goals'] if r['home'] == team else r['away_goals'] for r in games)
        thresholds[team] = values[ceil(len(values) * METHOD['percentile']) - 1] if values else None
        recent[team] = {r['id'] for r in games[-METHOD['recent_games']:]}
    changes = []
    for row in capped['history']:
        original = [row['home_goals'], row['away_goals']]
        for side in ('home', 'away'):
            team = row[side]
            if team in targets and row['id'] in recent[team]:
                row[side + '_goals'] = min(row[side + '_goals'], thresholds[team])
        updated = [row['home_goals'], row['away_goals']]
        if original != updated:
            changes.append({'id': row['id'], 'operation': 'COUNTERFACTUAL_CAP',
                            'original_score': original, 'counterfactual_score': updated})
    scenarios = [baseline, _scenario(dropped, policy, 'REMOVE_HIGHEST_TARGET_TOTAL', removed, largest is not None),
                 _scenario(capped, policy, 'CAP_RECENT_TARGET_GOALS', changes, all(v is not None for v in thresholds.values()))]
    source = {c['key']: c['raw'] for c in grid['candidates']}
    if any(source[c['key']] != c['raw'] for c in baseline['candidates']):
        raise ValueError('baseline differs from frozen grid')
    sufficient = all(s['history_sufficient'] and s['available'] for s in scenarios)
    output = {'schema': SCHEMA, 'prediction_id': prediction['id'], 'match': grid['match'],
              'sealed_at': at, 'grid': grid, 'grid_hash': grid['hash'], 'passport': passport(prediction),
              'method': deepcopy(METHOD), 'eligible_history': len(rows), 'excluded_history_ids': excluded,
              'target_history_count': len(target_rows), 'cap_thresholds': thresholds, 'scenarios': scenarios,
              'status': 'RESEARCH_DIAGNOSTIC' if sufficient else 'INSUFFICIENT_HISTORY_DIAGNOSTIC',
              'source_blockers': sorted({i['code'] for i in prediction['issues'] if i['severity'] == 'BLOCK'}),
              'quotes_read': False, 'monetary_permission': False, 'execution_enabled': False,
              'class': 'D', 'stake': 0., 'confidence_interval': False,
              'limitations': ['Perturbed scores are counterfactuals, not provider observations.',
                              'Unchanged classifications do not validate the model or remove any gate.',
                              'P75 and five games are fixed diagnostic probes, not learned betting thresholds.']}
    output['hash'] = digest(output)
    return output


def compare_robustness(report, prediction, quotes, policy, at, receipt=None):
    if not isinstance(report, dict): raise ValueError('robustness report object required')
    saved = dict(report); signature = saved.pop('hash', None)
    if report.get('schema') != SCHEMA or digest(saved) != signature:
        raise ValueError('robustness hash/schema mismatch')
    if time(report['sealed_at']) > time(at): raise ValueError('future robustness seal')
    expected = create_robustness(report['grid'], prediction, policy, report['sealed_at'])
    if report != expected: raise ValueError('robustness report does not reproduce')
    comparison = compare_grid(report['grid'], prediction, quotes, policy, at, receipt)
    by_scenario = {s['name']: {c['key']: c for c in s['candidates']}
                   for s in report['scenarios'] if s['available']}
    for quote in quotes:
        validate_quote(quote, report['match']['kickoff'], at, report['sealed_at'])
    rows = []
    for original in comparison['candidates']:
        prices = []
        for price in original['prices']:
            scenarios = []
            for name, candidates in by_scenario.items():
                candidate = candidates[original['key']]
                ev = payoff_ev(*candidate['raw'][:2], price['odds'])
                stress = min(payoff_ev(*p[:2], price['odds']) for p in candidate['raw_stress_probabilities'])
                scenarios.append({'name': name, 'raw': candidate['raw'], 'raw_ev': ev,
                                  'raw_stress_ev_min': stress,
                                  'diagnostic_class': grade_stress(ev, stress, policy.min_ev)['class']})
            changed = len({s['diagnostic_class'] for s in scenarios}) > 1
            signs_changed = len({s['raw_ev'] >= 0 for s in scenarios}) > 1
            prices.append({'bookmaker': price['bookmaker'], 'odds': price['odds'],
                           'observed_at': price['observed_at'], 'line_id': price['line_id'],
                           'scenarios': scenarios, 'diagnostic_class_changed': changed,
                           'raw_ev_sign_changed': signs_changed,
                           'research_review_required': changed or signs_changed or report['status'] != 'RESEARCH_DIAGNOSTIC',
                           'calibration_applied': False, 'monetary_permission': False})
        rows.append({'key': original['key'], 'market': original['market'], 'prices': prices,
                     'price_status': original['price_status'], 'class': 'D', 'stake': 0.,
                     'monetary_permission': False})
    output = {'schema': 'goal-history-comparison-v1', 'at': at, 'prediction_id': prediction['id'],
              'robustness_hash': report['hash'], 'grid_hash': report['grid_hash'],
              'quotes_hash': digest(quotes), 'api_receipt_hash': digest(receipt),
              'passport': report['passport'], 'candidates': rows, 'candidate_count': len(rows),
              'priced_count': sum(bool(r['prices']) for r in rows),
              'class_changed_contracts': sum(any(p['diagnostic_class_changed'] for p in r['prices']) for r in rows),
              'raw_ev_sign_changed_contracts': sum(any(p['raw_ev_sign_changed'] for p in r['prices']) for r in rows),
              'source_blockers': report['source_blockers'], 'calibration_applied': False,
              'status': 'RESEARCH_REVIEW_REQUIRED' if any(p['research_review_required'] for r in rows for p in r['prices']) else 'RESEARCH_ONLY',
              'class': 'D', 'stake': 0., 'monetary_permission': False, 'execution_enabled': False,
              'next_action': 'Review sensitivity and collect independent evidence; unchanged raw labels grant no admission.'}
    output['hash'] = digest(output)
    return output


def render_robustness(report):
    match = report['match']
    lines = [f"{match['home']} — {match['away']}: {report['status']} | RESEARCH_ONLY | класс D"]
    for scenario in report['scenarios']:
        rates = scenario['rates']
        lines.append(f"{scenario['name']}: λ {rates['home']:.3f}/{rates['away']:.3f}; игр {scenario['team_games']}; изменений {len(scenario['changes'])}")
    lines.append('Это чувствительность к контрфактической истории; исходный прогноз и разрешения не меняются.')
    return '\n'.join(lines)
