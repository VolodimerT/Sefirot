"""Research-only Asian quarter-line settlement; never admits a CORE wager.

The existing sealed three-outcome probability contract cannot represent half
wins/losses. Keep these calculations outside CORE/Policy until independent
calibration and settlement-rule evidence exist.
"""
from math import fsum, isfinite


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
        gross *= quarter_payoff(leg["kind"], leg["side"], leg["line"],
                                leg["home"], leg["away"], leg["odds"])["gross_return_per_unit"]
    return {"hypothetical_stake": stake, "hypothetical_exposure_cap": limit,
            "gross_return": stake * gross, "net_result": stake * (gross - 1),
            "decision": "PASS", "stake": 0., "monetary_permission": False,
            "execution_enabled": False}
