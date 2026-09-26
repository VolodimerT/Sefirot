"""Point-in-time illustrative Elo estimator; not fitted or validated for betting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt

from .core import SportsOnlySnapshot, ProbabilitySeal, _utc


class InsufficientHistory(ValueError):
    """History for at least one team is below the prototype-only floor."""


@dataclass(frozen=True, slots=True)
class HistoricalMatch:
    match_id: str
    kickoff: datetime
    result_received_at: datetime
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    source: str

    def __post_init__(self) -> None:
        if not self.match_id or not self.source or not self.home_team or not self.away_team or self.home_team == self.away_team:
            raise ValueError("history needs distinct teams, source and match id")
        if _utc(self.result_received_at) < _utc(self.kickoff):
            raise ValueError("a result cannot be received before kickoff")
        if any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in (self.home_goals, self.away_goals)):
            raise ValueError("goals must be nonnegative integers")


@dataclass(frozen=True, slots=True)
class Estimate:
    probabilities: tuple[float, float, float]
    low: tuple[float, float, float]
    high: tuple[float, float, float]
    used_matches: tuple[str, ...]
    excluded_future: int
    min_team_games: int
    interval_status: str = "UNCALIBRATED"


def estimate_1x2(snapshot: SportsOnlySnapshot, history: tuple[HistoricalMatch, ...],
                 min_team_games: int = 3) -> Estimate:
    """Use results received before as_of; prices and market data are never inputs."""
    if not isinstance(history, tuple) or not isinstance(min_team_games, int) or isinstance(min_team_games, bool) or min_team_games < 1:
        raise ValueError("history must be an immutable tuple and floor must be positive")
    teams: dict[str, str] = {}
    for fact in snapshot.facts:
        if fact.key in ("sports.home_team", "sports.away_team"):
            if fact.key in teams:
                raise ValueError("ambiguous team identity")
            if fact.kind != "FACT" or not fact.value:
                raise ValueError("team identity needs a confirmed fact")
            teams[fact.key] = fact.value
    if len(teams) != 2 or teams["sports.home_team"] == teams["sports.away_team"]:
        raise ValueError("snapshot needs two distinct confirmed teams")

    seen: set[str] = set()
    for match in history:
        if not isinstance(match, HistoricalMatch) or match.match_id in seen:
            raise ValueError("history needs unique valid matches")
        seen.add(match.match_id)
    known = [m for m in history if _utc(m.kickoff) < _utc(snapshot.as_of)
             and _utc(m.result_received_at) <= _utc(snapshot.as_of)]
    known.sort(key=lambda m: (_utc(m.kickoff), m.match_id))
    rating: dict[str, float] = {}
    games: dict[str, int] = {}
    draws = 0
    for m in known:
        rh = rating.get(m.home_team, 1500.0)
        ra = rating.get(m.away_team, 1500.0)
        expected_home = 1 / (1 + 10 ** (-(rh + 55 - ra) / 400))
        home_result = 1.0 if m.home_goals > m.away_goals else (0.5 if m.home_goals == m.away_goals else 0.0)
        delta = 20 * (home_result - expected_home)
        rating[m.home_team], rating[m.away_team] = rh + delta, ra - delta
        games[m.home_team] = games.get(m.home_team, 0) + 1
        games[m.away_team] = games.get(m.away_team, 0) + 1
        draws += (m.home_goals == m.away_goals)
    home, away = teams["sports.home_team"], teams["sports.away_team"]
    least = min(games.get(home, 0), games.get(away, 0))
    if least < min_team_games:
        raise InsufficientHistory(f"team history {least} < floor {min_team_games}")

    conditional_home = 1 / (1 + 10 ** (-(rating[home] + 55 - rating[away]) / 400))
    # Illustrative priors/width: explicit heuristics, NOT fitted or coverage-tested.
    draw_base = (20 * 0.27 + draws) / (20 + len(known))
    p_draw = draw_base * (1 - 0.45 * abs(2 * conditional_home - 1))
    p_home = (1 - p_draw) * conditional_home
    p_away = 1 - p_draw - p_home
    probs = (p_home, p_draw, p_away)
    width = min(0.25, 0.5 / sqrt(least))
    return Estimate(probs, tuple(max(0, p-width) for p in probs),
                    tuple(min(1, p+width) for p in probs),
                    tuple(m.match_id for m in known), len(history)-len(known), least)


def seal_estimate(snapshot: SportsOnlySnapshot, estimate: Estimate,
                  sealed_at: datetime) -> ProbabilitySeal:
    """Place illustrative bounds on an immutable probability record."""
    if estimate.interval_status != "UNCALIBRATED":
        raise ValueError("prototype cannot certify calibration")
    return ProbabilitySeal.create(snapshot, "elo-demo-v0.4", sealed_at,
                                  estimate.probabilities, estimate.low, estimate.high)
