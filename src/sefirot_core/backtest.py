"""Chronological shadow evaluation with explicitly captured prematch snapshots."""

from __future__ import annotations

from dataclasses import dataclass

from .core import SportsOnlySnapshot, _utc, _number
from .model import HistoricalMatch, InsufficientHistory, estimate_1x2


@dataclass(frozen=True, slots=True)
class BacktestCase:
    snapshot: SportsOnlySnapshot
    eventual_result: HistoricalMatch


@dataclass(frozen=True, slots=True)
class BacktestRecord:
    match_id: str
    probabilities: tuple[float, float, float]
    used_matches: tuple[str, ...]
    brier: float


@dataclass(frozen=True, slots=True)
class BacktestReport:
    records: tuple[BacktestRecord, ...]
    insufficient_history: tuple[str, ...]
    mean_brier: float | None


def multiclass_brier(probabilities: tuple[float, float, float], outcome: int) -> float:
    """Unnormalized 3-class Brier: sum of squared errors; range [0, 2]."""
    if not isinstance(probabilities, tuple) or len(probabilities) != 3 or isinstance(outcome, bool) or outcome not in (0, 1, 2):
        raise ValueError("three probabilities and a valid outcome index required")
    p = tuple(_number(x, "probability") for x in probabilities)
    if any(x < 0 or x > 1 for x in p) or abs(sum(p) - 1) > 1e-9:
        raise ValueError("probabilities must sum to one")
    return sum((x - int(i == outcome)) ** 2 for i, x in enumerate(p))


def walk_forward_1x2(history: tuple[HistoricalMatch, ...],
                     cases: tuple[BacktestCase, ...], min_team_games: int = 3) -> BacktestReport:
    """Score only recorded prematch inputs; never reconstruct them from final results."""
    if not isinstance(cases, tuple) or not isinstance(history, tuple):
        raise ValueError("history and cases must be immutable tuples")
    records: list[BacktestRecord] = []
    skipped: list[str] = []
    ids: set[str] = set()
    for case in sorted(cases, key=lambda x: (_utc(x.snapshot.as_of), x.snapshot.match_id)):
        snap, result = case.snapshot, case.eventual_result
        if snap.match_id in ids:
            raise ValueError("duplicate backtest case")
        ids.add(snap.match_id)
        if snap.match_id != result.match_id or _utc(snap.kickoff) != _utc(result.kickoff):
            raise ValueError("result does not match the captured fixture")
        if _utc(result.result_received_at) <= _utc(snap.as_of):
            raise ValueError("result was already available at forecast time")
        team_facts = {f.key: f.value for f in snap.facts if f.key in {"sports.home_team", "sports.away_team"}}
        if team_facts != {"sports.home_team": result.home_team, "sports.away_team": result.away_team}:
            raise ValueError("result teams differ from prematch fixture")
        try:
            estimate = estimate_1x2(snap, history, min_team_games)
        except InsufficientHistory:
            skipped.append(snap.match_id)
            continue
        if snap.match_id in estimate.used_matches:
            raise ValueError("target result leaked into its prediction")
        outcome = 0 if result.home_goals > result.away_goals else (1 if result.home_goals == result.away_goals else 2)
        brier = multiclass_brier(estimate.probabilities, outcome)
        records.append(BacktestRecord(snap.match_id, estimate.probabilities, estimate.used_matches, brier))
    return BacktestReport(tuple(records), tuple(skipped),
                          sum(r.brier for r in records) / len(records) if records else None)
