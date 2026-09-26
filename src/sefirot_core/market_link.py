"""Payoff branches for audit stress tests; no probability or betting permission."""

from dataclasses import dataclass
from enum import Enum


class ScoreMarket(str, Enum):
    ONE_X_TWO_HOME = "1X2_HOME"
    ONE_X_TWO_DRAW = "1X2_DRAW"
    ONE_X_TWO_AWAY = "1X2_AWAY"
    OVER_2_5 = "OVER_2_5"
    OVER_3 = "OVER_3"
    BTTS_OVER_2_5 = "BTTS_OVER_2_5"
    HOME_WIN_OVER_2_5 = "HOME_WIN_OVER_2_5"
    AWAY_MINUS_1 = "AWAY_MINUS_1"


class Settlement(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    PUSH = "PUSH"


def settle_score(market: ScoreMarket, home: int, away: int) -> Settlement:
    """Illustrative full-time settlement; verify actual bookmaker terms separately."""
    if not isinstance(market, ScoreMarket):
        raise ValueError("unsupported market; small markets and live have no route")
    if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (home, away)):
        raise ValueError("scores must be nonnegative integers")
    total = home + away
    win = {
        ScoreMarket.ONE_X_TWO_HOME: home > away,
        ScoreMarket.ONE_X_TWO_DRAW: home == away,
        ScoreMarket.ONE_X_TWO_AWAY: home < away,
        ScoreMarket.OVER_2_5: total >= 3,
        ScoreMarket.OVER_3: total >= 4,
        ScoreMarket.BTTS_OVER_2_5: home > 0 and away > 0 and total >= 3,
        ScoreMarket.HOME_WIN_OVER_2_5: home > away and total >= 3,
        ScoreMarket.AWAY_MINUS_1: away - home >= 2,
    }
    if market is ScoreMarket.OVER_3 and total == 3:
        return Settlement.PUSH
    if market is ScoreMarket.AWAY_MINUS_1 and away - home == 1:
        return Settlement.PUSH
    return Settlement.WIN if win[market] else Settlement.LOSS


@dataclass(frozen=True, slots=True)
class Branch:
    home_goals: int
    away_goals: int
    supports_thesis: bool
    rationale: str


@dataclass(frozen=True, slots=True)
class LinkDiagnostic:
    market: ScoreMarket
    tested_branches: tuple[tuple[Branch, Settlement], ...]
    thesis_consistent_losses: tuple[Branch, ...]
    quantified: bool = False
    authority: str = "RESEARCH_ONLY"


def inspect_market_link(market: ScoreMarket, branches: tuple[Branch, ...]) -> LinkDiagnostic:
    """Find a thesis-consistent losing scoreline, without inventing its P."""
    if not branches or not isinstance(branches, tuple):
        raise ValueError("at least one explicit scenario branch is required")
    tested = tuple((b, settle_score(market, b.home_goals, b.away_goals)) for b in branches)
    if any(b.supports_thesis and not b.rationale.strip() for b, _ in tested):
        raise ValueError("thesis-consistent branches need an explicit reason")
    return LinkDiagnostic(market, tested,
                          tuple(b for b, settlement in tested if b.supports_thesis and settlement is Settlement.LOSS))
