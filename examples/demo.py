"""Synthetic, deterministic illustration. No real-world bet can be placed."""

import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot_core import (Fact, SportsOnlySnapshot, HistoricalMatch, ThreeWayQuote,
                          estimate_1x2, seal_estimate, evaluate_1x2)

now = datetime(2026, 9, 26, 10, tzinfo=timezone.utc)
snapshot = SportsOnlySnapshot("synthetic-demo", now + timedelta(hours=3), now, (
    Fact("sports.home_team", "Team A", "demo", now-timedelta(days=1), now-timedelta(hours=2)),
    Fact("sports.away_team", "Team B", "demo", now-timedelta(days=1), now-timedelta(hours=2)),
))
history = tuple(HistoricalMatch(
    f"demo-{n}", now-timedelta(days=10-n), now-timedelta(days=10-n)+timedelta(hours=2),
    "Team A" if n%2 else "Team C", "Team B" if n%2 else "Team A", n%3, (n+1)%2, "demo")
    for n in range(1, 8))
estimate = estimate_1x2(snapshot, history)
seal = seal_estimate(snapshot, estimate, now + timedelta(minutes=1))
quote = ThreeWayQuote("synthetic-book", now + timedelta(minutes=2), (1.8, 3.5, 5.0))
report = evaluate_1x2(snapshot, seal, quote)
print("SEFIROT shadow 1X2 (synthetic only)")
print("p(home/draw/away):", tuple(round(p, 4) for p in estimate.probabilities))
print("illustrative Low/Base/High home:", tuple(round(x, 4) for x in
      (estimate.low[0], estimate.probabilities[0], estimate.high[0])))
print("implied home:", round(report["implied"]["home"], 4))
print("EV home (arithmetic only):", round(report["ev"]["home"], 4))
print("monetary verdict:", report["monetary_verdict"])
