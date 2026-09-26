"""Pure 1X2 arithmetic and point-in-time invariants for an architecture prototype."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite

OUTCOMES = ("home", "draw", "away")


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


@dataclass(frozen=True, slots=True)
class Fact:
    key: str
    value: str
    source: str
    published_at: datetime
    received_at: datetime
    kind: str = "FACT"

    def __post_init__(self) -> None:
        if not self.key.startswith("sports.") or not self.source or self.kind not in {"FACT", "INFERENCE", "ASSUMPTION"}:
            raise ValueError("a sports fact needs a sports.* key, source, and a valid evidence kind")
        if _utc(self.published_at) > _utc(self.received_at):
            raise ValueError("fact cannot be received before publication")


@dataclass(frozen=True, slots=True)
class SportsOnlySnapshot:
    match_id: str
    kickoff: datetime
    as_of: datetime
    facts: tuple[Fact, ...]

    def __post_init__(self) -> None:
        if not self.match_id or _utc(self.as_of) >= _utc(self.kickoff):
            raise ValueError("a snapshot needs a match before kickoff")
        if not isinstance(self.facts, tuple):
            raise ValueError("facts must be an immutable tuple")
        for fact in self.facts:
            if not isinstance(fact, Fact):
                raise ValueError("facts must contain Fact records")
            if _utc(fact.published_at) > _utc(self.as_of) or _utc(fact.received_at) > _utc(self.as_of):
                raise ValueError("future or unseen fact in a sports snapshot")

    def digest(self) -> str:
        data = {
            "match_id": self.match_id,
            "kickoff": _utc(self.kickoff).isoformat(),
            "as_of": _utc(self.as_of).isoformat(),
            "facts": [
                (f.key, f.value, f.source, _utc(f.published_at).isoformat(),
                 _utc(f.received_at).isoformat(), f.kind)
                for f in self.facts
            ],
        }
        return sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProbabilitySeal:
    snapshot_digest: str
    model_version: str
    sealed_at: datetime
    probabilities: tuple[float, float, float]
    low: tuple[float, float, float] | None = None
    high: tuple[float, float, float] | None = None
    interval_status: str = "UNCALIBRATED"

    def __post_init__(self) -> None:
        _utc(self.sealed_at)
        if not self.model_version or len(self.snapshot_digest) != 64 or any(c not in "0123456789abcdef" for c in self.snapshot_digest):
            raise ValueError("seal needs a valid snapshot digest and model version")
        if not isinstance(self.probabilities, tuple) or len(self.probabilities) != 3:
            raise ValueError("a seal needs three probabilities")
        p = tuple(_number(x, "probability") for x in self.probabilities)
        if any(x < 0 or x > 1 for x in p) or abs(sum(p) - 1.0) > 1e-9:
            raise ValueError("1X2 probabilities must sum to one")
        if (self.low is None) != (self.high is None):
            raise ValueError("low and high must be provided together")
        if self.interval_status != "UNCALIBRATED":
            raise ValueError("the prototype has no validated interval coverage")
        if self.low is not None:
            if not isinstance(self.low, tuple) or not isinstance(self.high, tuple) or len(self.low) != 3 or len(self.high) != 3:
                raise ValueError("bounds need three values each")
            for lower, middle, upper in zip(self.low, p, self.high):
                lower, upper = _number(lower, "low"), _number(upper, "high")
                if not 0 <= lower <= middle <= upper <= 1:
                    raise ValueError("low/base/high bounds must be ordered probabilities")

    @classmethod
    def create(cls, snapshot: SportsOnlySnapshot, model_version: str,
               sealed_at: datetime, probabilities: tuple[float, float, float],
               low: tuple[float, float, float] | None = None,
               high: tuple[float, float, float] | None = None) -> ProbabilitySeal:
        if not model_version or not isinstance(probabilities, tuple) or len(probabilities) != 3:
            raise ValueError("a version and three 1X2 probabilities are required")
        if _utc(sealed_at) < _utc(snapshot.as_of) or _utc(sealed_at) >= _utc(snapshot.kickoff):
            raise ValueError("probability must be sealed after the snapshot and before kickoff")
        p = tuple(_number(x, "probability") for x in probabilities)
        if any(x < 0 or x > 1 for x in p) or abs(sum(p) - 1.0) > 1e-9:
            raise ValueError("1X2 probabilities must sum to one")
        return cls(snapshot.digest(), model_version, sealed_at, p, low, high)


@dataclass(frozen=True, slots=True)
class ThreeWayQuote:
    bookmaker: str
    received_at: datetime
    odds: tuple[float, float, float]

    def __post_init__(self) -> None:
        _utc(self.received_at)
        if not self.bookmaker or not isinstance(self.odds, tuple) or len(self.odds) != 3:
            raise ValueError("a quote needs a bookmaker and three prices")
        if any(_number(o, "odds") <= 1 for o in self.odds):
            raise ValueError("decimal odds must exceed one")


def evaluate_1x2(snapshot: SportsOnlySnapshot, seal: ProbabilitySeal,
                 quote: ThreeWayQuote) -> dict[str, object]:
    """Compute diagnostics only; the monetary verdict is always PASS."""
    if seal.snapshot_digest != snapshot.digest() or not seal.model_version:
        raise ValueError("the probability seal belongs to another snapshot")
    if _utc(seal.sealed_at) < _utc(snapshot.as_of) or _utc(seal.sealed_at) >= _utc(snapshot.kickoff):
        raise ValueError("seal must be created in the prematch window")
    if _utc(quote.received_at) < _utc(seal.sealed_at) or _utc(quote.received_at) >= _utc(snapshot.kickoff):
        raise ValueError("the price must be received after the seal and before kickoff")
    implied = tuple(1 / _number(o, "odds") for o in quote.odds)
    report = {
        "snapshot_digest": seal.snapshot_digest,
        "model_version": seal.model_version,
        "implied": dict(zip(OUTCOMES, implied)),
        "overround": sum(implied) - 1,
        "ev": dict(zip(OUTCOMES, (p * o - 1 for p, o in zip(seal.probabilities, quote.odds)))),
        "monetary_verdict": "PASS",
        "reason": "shadow prototype: no validated probabilities or risk policy",
    }
    if seal.low is not None and seal.high is not None:
        report["ev_low"] = dict(zip(OUTCOMES, (p * o - 1 for p, o in zip(seal.low, quote.odds))))
        report["ev_high"] = dict(zip(OUTCOMES, (p * o - 1 for p, o in zip(seal.high, quote.odds))))
        report["interval_status"] = seal.interval_status
    return report
