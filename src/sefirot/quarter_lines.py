"""Research-only Asian quarter-line settlement; never admits a CORE wager.

The existing sealed three-outcome probability contract cannot represent half
wins/losses. Keep these calculations outside CORE/Policy until independent
calibration and settlement-rule evidence exist.
"""
from math import fsum, isfinite
from .markets import Market, settle


def _number(value, name):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(name + " must be finite")
    return float(value)


def _contract(kind, side, line, odds):
    if kind not in ("HANDICAP", "TOTAL", "TEAM_TOTAL"):
        raise ValueError("unsupported quarter-line market")
    sides = {"HANDICAP": ("HOME", "AWAY"), "TOTAL": ("OVER", "UNDER"),
             "TEAM_TOTAL": ("HOME_OVER", "HOME_UNDER", "AWAY_OVER", "AWAY_UNDER")}
    if side not in sides[kind]:
        raise ValueError("unsupported quarter-line side")
    line = _number(line, "line")
    odds = _number(odds, "odds")
    if odds <= 1 or odds > 10000 or (kind != "HANDICAP" and line < 0):
        raise ValueError("invalid line or odds")
    quarter = round(line * 4)
    if abs(line * 4 - quarter) > 1e-9 or quarter % 2 != 1:
        raise ValueError("quarter line (.25 or .75) required")
    return line, odds


def quarter_payoff(kind, side, line, home, away, odds):
    """Net per unit stake and exact two half-line outcomes at regulation FT."""
    line, odds = _contract(kind, side, line, odds)
    if type(home) is not int or type(away) is not int or min(home, away) < 0:
        raise ValueError("nonnegative integer regulation scores required")
    lower = (round(line * 4) - 1) / 4
    upper = (round(line * 4) + 1) / 4
    outcomes = []
    for half_line in (lower, upper):
        if kind == "HANDICAP":
            difference = (home - away if side == "HOME" else away - home) + half_line
        else:
            goals = home + away if kind == "TOTAL" else (home if side.startswith("HOME") else away)
            difference = (goals - half_line) * (1 if side.endswith("OVER") else -1)
        outcomes.append("WIN" if difference > 0 else "PUSH" if difference == 0 else "LOSS")
    profit = fsum((odds - 1 if outcome == "WIN" else 0 if outcome == "PUSH" else -1) / 2
                  for outcome in outcomes)
    return {"half_lines": [lower, upper], "outcomes": outcomes,
            "net_per_unit": profit, "gross_return_per_unit": 1 + profit,
            "monetary_permission": False}


def quarter_review(kind, side, line, odds, score_mass):
    """Raw score-model diagnostic; unvalidated mass never becomes certified EV."""
    _contract(kind, side, line, odds)
    if not isinstance(score_mass, dict) or not score_mass:
        raise ValueError("nonempty score mass required")
    terms, wins, losses = [], [], []
    for score, probability in score_mass.items():
        if not isinstance(score, tuple) or len(score) != 2:
            raise ValueError("score pair required")
        p = _number(probability, "score probability")
        if not 0 <= p <= 1:
            raise ValueError("score probability out of range")
        payoff = quarter_payoff(kind, side, line, *score, odds)
        terms.append(p)
        wins.append(p * payoff["outcomes"].count("WIN") / 2)
        losses.append(p * payoff["outcomes"].count("LOSS") / 2)
    if abs(fsum(terms) - 1) > 1e-8:
        raise ValueError("score mass must sum to one")
    win_units, loss_units = fsum(wins), fsum(losses)
    return {"raw_model_ev_diagnostic": (odds - 1) * win_units - loss_units,
            "raw_fair_odds_diagnostic": 1 + loss_units / win_units if win_units else None,
            "validated_probability": None, "validated_ev": None,
            "class": "C", "decision": "PASS", "stake": 0.,
            "status": "QUARTER_LINE_RESEARCH_UNCALIBRATED",
            "monetary_permission": False, "execution_enabled": False}


def simulate_express(legs, hypothetical_stake, max_hypothetical_exposure):
    """Offline two/three-leg return arithmetic, never a placement instruction."""
    if not isinstance(legs, list) or len(legs) not in (2, 3):
        raise ValueError("express requires two or three legs")
    stake = _number(hypothetical_stake, "hypothetical stake")
    limit = _number(max_hypothetical_exposure, "hypothetical exposure")
    if stake <= 0 or limit <= 0 or stake > limit:
        raise ValueError("hypothetical exposure exceeded")
    fixtures = [leg.get("fixture_id") for leg in legs if isinstance(leg, dict)]
    if len(fixtures) != len(legs) or any(not isinstance(fid, str) or not fid for fid in fixtures):
        raise ValueError("fixture identity required")
    if len(set(fixtures)) != len(fixtures):
        raise ValueError("correlated same-fixture legs require a joint builder contract")
    gross = 1.
    for leg in legs:
        kind, side, line = leg["kind"], leg["side"], leg.get("line")
        odds = _number(leg["odds"], "odds")
        if odds <= 1 or odds > 10000:
            raise ValueError("invalid odds")
        if kind in ("HANDICAP", "TOTAL", "TEAM_TOTAL") and line is not None:
            line = _number(line, "line")
            units = round(line * 4)
            is_quarter = abs(line * 4 - units) <= 1e-9 and units % 2 == 1
        else:
            is_quarter = False
        if is_quarter:
            leg_return = quarter_payoff(kind, side, line, leg["home"],
                                        leg["away"], odds)["gross_return_per_unit"]
        else:
            outcome = settle(Market(kind, side, line), leg["home"], leg["away"])
            leg_return = odds if outcome == "WIN" else 1. if outcome == "PUSH" else 0.
        gross *= leg_return
    return {"hypothetical_stake": stake, "hypothetical_exposure_cap": limit,
            "gross_return": stake * gross, "net_result": stake * (gross - 1),
            "decision": "PASS", "stake": 0., "monetary_permission": False,
            "execution_enabled": False}


def pairwise_correlations(rows):
    """Name every overlapping fixture pair; never infer independence from a third leg."""
    from .contracts import time

    findings = []
    for index, left in enumerate(rows):
        for right in rows[index + 1:]:
            factors = []
            same_league = left['league'] == right['league']
            if same_league:
                factors.append('SHARED_LEAGUE_FACTORS_UNQUANTIFIED')
            if time(left['kickoff']).date() == time(right['kickoff']).date():
                factors.append('SHARED_MATCH_DAY_FACTORS_UNQUANTIFIED')
            if set(left['teams']) & set(right['teams']):
                factors.append('SHARED_TEAM_ACROSS_FIXTURES' if same_league
                               else 'SAME_TEAM_NAME_IDENTITY_UNVERIFIED')
            if set(left['source_groups']) & set(right['source_groups']):
                factors.append('SHARED_SOURCE_GROUP_UNQUANTIFIED')
            if factors:
                findings.append({'fixture_ids': [left['fixture_id'], right['fixture_id']],
                                 'factors': factors})
    return findings


def review_independent_express(legs, policy, at):
    """Review two/three sealed, distinct-fixture main legs without placing bets.

    A product of marginal score-model returns is an *assumption diagnostic*;
    different fixture IDs alone do not establish stochastic independence.
    Quote receipts prove local content binding, not bookmaker acceptance of a
    combined ticket or its actual settlement rules.
    """
    from .market_grid import compare_grid

    if not isinstance(legs, list) or len(legs) not in (2, 3):
        raise ValueError('two or three predeclared legs required')
    rows = []; fixture_ids = set(); bookmakers = set(); risk = set()
    for leg in legs:
        if not isinstance(leg, dict) or set(leg) != {
                'grid', 'prediction', 'quotes', 'receipt', 'market_key', 'line_id'}:
            raise ValueError('sealed research leg contract required')
        grid = leg['grid']; match = grid['match']; fid = match['id']
        if fid in fixture_ids:
            raise ValueError('same-fixture legs require the joint builder model')
        fixture_ids.add(fid)
        comparison = compare_grid(grid, leg['prediction'], leg['quotes'], policy, at, leg['receipt'])
        matching = [row for row in comparison['candidates'] if row['key'] == leg['market_key']]
        if len(matching) != 1 or matching[0]['class'] == 'RED':
            raise ValueError('unavailable or conflicting prematch leg')
        candidate = matching[0]
        prices = [p for p in candidate['prices'] if p['line_id'] == leg['line_id']]
        if len(prices) != 1 or not isinstance(leg['line_id'], str) or not leg['line_id']:
            raise ValueError('one fresh receipt-bound line required for each leg')
        price = prices[0]; odds = price['odds']
        win, push, loss = candidate['raw']
        if abs(fsum((win, push, loss)) - 1) > 1e-8:
            raise ValueError('invalid sealed outcome mass')
        bookmakers.add(price['bookmaker'])
        rows.append({'fixture_id': fid, 'league': match['league'],
                     'kickoff': match['kickoff'], 'market_key': candidate['key'],
                     'teams': [match['home'], match['away']],
                     'source_groups': sorted({fact['source_group'] for fact in
                         grid['sports_facts']['facts']}),
                     'bookmaker': price['bookmaker'], 'line_id': price['line_id'],
                     'odds': odds, 'raw_win': win, 'raw_push': push,
                     'raw_loss': loss, 'sport_quality': candidate['sport_quality']['status'],
                     'raw_stress_expected_gross_min': min(
                         p[0] * odds + p[1] for p in candidate['stress_probabilities']),
                     'bet_value': candidate['bet_value']['status'],
                     'raw_expected_gross': win * odds + push,
                     'raw_single_ev': win * odds + push - 1,
                     'synthetic': grid['synthetic']})
    findings = pairwise_correlations(rows)
    risk.update(factor for finding in findings for factor in finding['factors'])
    if len(bookmakers) != 1: risk.add('CROSS_BOOKMAKER_PRICES')
    if any(r['synthetic'] for r in rows): risk.add('SYNTHETIC_SOURCE')
    # PUSH returns one unit on that leg. A half-win/loss needs the separate
    # quarter-line contract and a verified bookmaker repricing rule.
    raw_gross = 1.; full_win_odds = 1.; full_win_probability = 1.
    no_full_loss = 1.; stressed_gross_floor = 1.
    for row in rows:
        raw_gross *= row['raw_expected_gross']
        full_win_odds *= row['odds']
        full_win_probability *= row['raw_win']
        no_full_loss *= 1 - row['raw_loss']
        stressed_gross_floor *= row['raw_stress_expected_gross_min']
    best = max(rows, key=lambda r: (r['raw_single_ev'], r['fixture_id'], r['market_key']))
    return {'schema': 'independent-express-research-v1', 'at': at, 'legs': rows,
            'mode': 'INDEPENDENT_EXPRESS', 'sport_quality': 'UNVERIFIED',
            'bet_value': 'UNVERIFIED', 'independence': 'ASSUMED_NOT_ESTABLISHED',
            'correlation_findings': findings,
            'correlation_risks': sorted(risk),
            'raw_full_win_probability_if_independent': full_win_probability,
            'raw_expected_gross_if_independent': raw_gross,
            'raw_ev_if_independent': raw_gross - 1,
            'quoted_full_win_odds_product_diagnostic': full_win_odds,
            'actual_combined_bookmaker_price': None,
            'best_single_raw_diagnostic': {'fixture_id': best['fixture_id'],
                'market_key': best['market_key'], 'raw_ev': best['raw_single_ev']},
            'best_confirmed_single': None,
            'validated_probability': None, 'validated_ev': None,
            'death_test': {'status': 'RAW_INDEPENDENCE_DIAGNOSTIC_ONLY',
                'any_full_loss_probability_if_independent': 1 - no_full_loss,
                'stressed_expected_gross_floor_if_independent': stressed_gross_floor,
                'correlation_unmodelled': bool(findings)},
            'class': 'C', 'decision': 'PASS', 'stake': 0.,
            'monetary_permission': False, 'execution_enabled': False}
