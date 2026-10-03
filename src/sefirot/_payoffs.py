"""Full-time football main-market contracts. No combinations or live markets."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import isfinite

MAIN_ORDER = ("1X2", "DOUBLE_CHANCE", "DNB", "HANDICAP", "TOTAL", "BTTS", "TEAM_TOTAL")


def number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        raise ValueError(f"{name} must be finite")
    return float(value)


@dataclass(frozen=True)
class Market:
    kind: str
    side: str
    line: float | None = None

    def __post_init__(self):
        if self.kind not in MAIN_ORDER:
            raise ValueError("unsupported market (small, express and live disabled)")
        allowed = {"1X2": {"HOME", "DRAW", "AWAY"}, "DOUBLE_CHANCE": {"1X", "X2", "12"},
                   "DNB": {"HOME", "AWAY"}, "HANDICAP": {"HOME", "AWAY"},
                   "TOTAL": {"OVER", "UNDER"}, "BTTS": {"YES", "NO"},
                   "TEAM_TOTAL": {"HOME_OVER", "HOME_UNDER", "AWAY_OVER", "AWAY_UNDER"}}
        if self.side not in allowed[self.kind]:
            raise ValueError("unsupported market side")
        if self.kind in {"HANDICAP", "TOTAL", "TEAM_TOTAL"}:
            if self.line is None or number(self.line, "line") * 2 != round(number(self.line, "line") * 2):
                raise ValueError("only integer/half-goal lines supported")
            if self.kind != "HANDICAP" and self.line < 0:
                raise ValueError("total line must be nonnegative")
        elif self.line is not None:
            raise ValueError("line is not used for this market")

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.side}" + (f":{self.line:g}" if self.line is not None else "")

    @property
    def push_possible(self) -> bool:
        """Settlement support, independent of the estimated score distribution."""
        return self.kind == 'DNB' or (self.line is not None and float(self.line).is_integer())


def settle(market: Market, home: int, away: int) -> str:
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (home, away)):
        raise ValueError("scores must be nonnegative integers")
    k, s, line = market.kind, market.side, market.line
    if k == "1X2":
        return "WIN" if s == ("HOME" if home > away else "DRAW" if home == away else "AWAY") else "LOSS"
    if k == "DOUBLE_CHANCE":
        return "WIN" if (s == "1X" and home >= away) or (s == "X2" and away >= home) or (s == "12" and home != away) else "LOSS"
    if k == "BTTS":
        return "WIN" if ((home > 0 and away > 0) == (s == "YES")) else "LOSS"
    if k == "DNB":
        value = (home - away) * (1 if s == "HOME" else -1)
    elif k == "HANDICAP":
        value = (home - away if s == "HOME" else away - home) + line
    else:
        goals = home + away if k == "TOTAL" else (home if s.startswith("HOME") else away)
        value = (goals - line) * (1 if s.endswith("OVER") else -1)
    return "WIN" if value > 0 else "PUSH" if value == 0 else "LOSS"


def implied(odds: float) -> float:
    odds = number(odds, "odds")
    if odds <= 1:
        raise ValueError("odds must exceed one")
    return 1 / odds


def margin(prices: tuple[float, ...]) -> float:
    if len(prices) < 2:
        raise ValueError("complete competing line required")
    return sum(implied(o) for o in prices) - 1


def payoff_ev(win: float, push: float, odds: float) -> float:
    win, push = number(win, "win"), number(push, "push")
    implied(odds)
    if min(win, push) < 0 or win + push > 1 + 1e-10:
        raise ValueError("invalid win/push probabilities")
    return win * (odds - 1) - (1 - win - push)


def fair_odds(win: float, push: float) -> float:
    win, push = number(win, "win"), number(push, "push")
    if win <= 0 or push < 0 or win + push > 1 + 1e-10:
        raise ValueError("fair odds undefined")
    return (1 - push) / win


@lru_cache(maxsize=64)
def _score_outcomes(market: Market, scores: tuple[tuple[int, int], ...]) -> tuple[str, ...]:
    """Cache settlement rules only; probabilities and prices are never cached."""
    return tuple(settle(market, home, away) for home, away in scores)


def probabilities(market: Market, score_mass: dict[tuple[int, int], float]) -> tuple[float, float, float]:
    scores = tuple(score_mass)
    values = []
    for (home, away), p in zip(scores, score_mass.values()):
        value = number(p, "score probability")
        if value < 0:
            raise ValueError("negative probability")
        # Validate every call before cache lookup: bool/float keys compare equal
        # to integer keys in Python and must not inherit a cached valid result.
        if type(home) is int and type(away) is int:
            invalid = home < 0 or away < 0
        else:
            invalid = any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in (home, away))
        if invalid:
            raise ValueError("scores must be nonnegative integers")
        values.append(value)
    # Bound both cache entry count and support size. Preserve the uncached path
    # for larger grids and duck-typed callers of the original public function.
    outcomes = (_score_outcomes(market, scores) if isinstance(market, Market) and len(scores) <= 4096
                else tuple(settle(market, home, away) for home, away in scores))
    result = {"WIN": 0., "PUSH": 0., "LOSS": 0.}
    for outcome, value in zip(outcomes, values):
        result[outcome] += value
    if abs(sum(result.values()) - 1) > 1e-8:
        raise ValueError("score mass must sum to one")
    return result["WIN"], result["PUSH"], result["LOSS"]
