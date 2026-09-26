"""Local single-writer, hash-linked capture of prematch shadow observations.

The local clock is a receipt clock, not independent proof of source authenticity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Callable

from .core import Fact, ProbabilitySeal, SportsOnlySnapshot, ThreeWayQuote, _utc, evaluate_1x2
from .audit import DecisionStatus, SourceSignal, SystemDecision


def _canonical(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat()


def _parse(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value))


def _snapshot_payload(snapshot: SportsOnlySnapshot) -> dict:
    return {"match_id": snapshot.match_id, "kickoff": _timestamp(snapshot.kickoff),
            "as_of": _timestamp(snapshot.as_of), "digest": snapshot.digest(),
            "facts": [{"key": f.key, "value": f.value, "source": f.source,
                       "published_at": _timestamp(f.published_at), "received_at": _timestamp(f.received_at),
                       "kind": f.kind} for f in snapshot.facts]}


def _restore_snapshot(p: dict) -> SportsOnlySnapshot:
    facts = tuple(Fact(f["key"], f["value"], f["source"], _parse(f["published_at"]),
                       _parse(f["received_at"]), f["kind"]) for f in p["facts"])
    obj = SportsOnlySnapshot(p["match_id"], _parse(p["kickoff"]), _parse(p["as_of"]), facts)
    if obj.digest() != p["digest"]:
        raise ValueError("snapshot digest mismatch")
    return obj


def _restore_seal(p: dict) -> ProbabilitySeal:
    return ProbabilitySeal(p["snapshot_digest"], p["model_version"], _parse(p["sealed_at"]),
                           tuple(p["probabilities"]),
                           tuple(p["low"]) if p["low"] is not None else None,
                           tuple(p["high"]) if p["high"] is not None else None,
                           p["interval_status"])


@dataclass(frozen=True, slots=True)
class CapturedEvent:
    kind: str
    recorded_at: datetime
    payload: dict
    previous_hash: str
    hash: str


class CaptureJournal:
    """One snapshot and seal per file, then any number of quotes and assessments.

    Exclusive creation of a sibling lock prevents concurrent writers. A crash may
    leave the lock in place; inspect/repair externally before removing it.
    """

    def __init__(self, path: str | Path, clock: Callable[[], datetime] | None = None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def read(self) -> tuple[CapturedEvent, ...]:
        if not self.path.exists():
            return ()
        events: list[CapturedEvent] = []
        previous = "0" * 64
        snapshot = seal = None
        snapshot_receipt = seal_receipt = None
        quotes: dict[str, tuple[ThreeWayQuote, datetime]] = {}
        signals: dict[str, SourceSignal] = {}
        assessments: dict[str, datetime] = {}
        decisions: set[str] = set()
        with self.path.open("rb") as stream:
            for number, line in enumerate(stream, 1):
                try:
                    if not line.endswith(b"\n"):
                        raise ValueError("incomplete record")
                    obj = json.loads(line)
                    body = {k: obj[k] for k in ("kind", "recorded_at", "payload", "previous_hash")}
                    digest = sha256(_canonical(body)).hexdigest()
                    if obj["previous_hash"] != previous or obj["hash"] != digest:
                        raise ValueError("broken hash chain")
                    when = _parse(obj["recorded_at"])
                    if events and when < events[-1].recorded_at:
                        raise ValueError("receipt clock moved backwards")
                    kind, p = obj["kind"], obj["payload"]
                    if kind == "snapshot":
                        if snapshot is not None or events:
                            raise ValueError("snapshot must be first and unique")
                        snapshot = _restore_snapshot(p)
                        if _utc(snapshot.as_of) > when or when >= _utc(snapshot.kickoff):
                            raise ValueError("snapshot captured outside prematch window")
                        snapshot_receipt = when
                    elif kind == "seal":
                        if snapshot is None or seal is not None:
                            raise ValueError("seal needs one existing snapshot")
                        seal = _restore_seal(p)
                        if (seal.snapshot_digest != snapshot.digest() or
                            not snapshot_receipt <= _utc(seal.sealed_at) <= when or
                            when >= _utc(snapshot.kickoff)):
                            raise ValueError("late or mismatched seal")
                        seal_receipt = when
                    elif kind == "quote":
                        if snapshot is None or seal is None:
                            raise ValueError("quote needs a prior probability seal")
                        quote = ThreeWayQuote(p["bookmaker"], _parse(p["received_at"]), tuple(p["odds"]))
                        if not seal_receipt <= _utc(quote.received_at) <= when or when >= _utc(snapshot.kickoff):
                            raise ValueError("late or backdated quote")
                        evaluate_1x2(snapshot, seal, quote)
                        quotes[digest] = quote, when
                    elif kind == "source_signal":
                        if snapshot is None or seal is None:
                            raise ValueError("market-bearing source signal needs a prior seal")
                        signal = SourceSignal(p["signal_id"], p["event_id"], p["source_id"],
                                              p["market"], _parse(p["published_at"]),
                                              _parse(p["received_at"]), p["odds"])
                        if (signal.signal_id in signals or signal.event_id != snapshot.match_id or
                            not seal_receipt <= _utc(signal.received_at) <= when or
                            when >= _utc(snapshot.kickoff)):
                            raise ValueError("source signal is early, late, duplicated or mismatched")
                        signals[signal.signal_id] = signal
                    elif kind == "assessment":
                        if p["quote_hash"] not in quotes or snapshot is None or seal is None:
                            raise ValueError("assessment needs recorded quote")
                        quote, quote_receipt = quotes[p["quote_hash"]]
                        if (quote_receipt > when or when >= _utc(snapshot.kickoff) or
                            p["report"] != evaluate_1x2(snapshot, seal, quote)):
                            raise ValueError("assessment differs from sealed evaluation")
                        assessments[digest] = when
                    elif kind == "decision":
                        if snapshot is None or seal is None or not assessments:
                            raise ValueError("decision needs prior assessment")
                        decision = SystemDecision(p["decision_id"], p["event_id"],
                                                  _parse(p["kickoff"]), _parse(p["decided_at"]),
                                                  DecisionStatus(p["status"]), p["reason"],
                                                  p["probability_seal"], p["source_signal_id"])
                        ref = p["assessment_hash"]
                        source = signals.get(decision.source_signal_id) if decision.source_signal_id else None
                        if (decision.decision_id in decisions or decision.event_id != snapshot.match_id or
                            _utc(decision.kickoff) != _utc(snapshot.kickoff) or
                            decision.probability_seal != seal.snapshot_digest or
                            decision.status is not DecisionStatus.SHADOW_EXPERIMENT or
                            p["monetary_authorized"] is not False or ref not in assessments or
                            not assessments[ref] <= _utc(decision.decided_at) <= when or
                            when >= _utc(snapshot.kickoff) or
                            (decision.source_signal_id is not None and (source is None or
                             _utc(source.received_at) > _utc(decision.decided_at)))):
                            raise ValueError("decision violates chronology or shadow-only policy")
                        decisions.add(decision.decision_id)
                    else:
                        raise ValueError("unknown event type")
                    events.append(CapturedEvent(kind, when, p, previous, digest))
                    previous = digest
                except (KeyError, TypeError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    raise ValueError(f"invalid capture record at line {number}: {exc}") from exc
        return tuple(events)

    def _append(self, kind: str, payload: dict) -> CapturedEvent:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".lock")
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(f"pid={os.getpid()}\n")
                f.flush()
                os.fsync(f.fileno())
            existing = self.read()
            now = _utc(self.clock())
            previous = existing[-1].hash if existing else "0" * 64
            body = {"kind": kind, "recorded_at": _timestamp(now),
                    "payload": payload, "previous_hash": previous}
            obj = dict(body, hash=sha256(_canonical(body)).hexdigest())
            # Recheck the full sequence and temporal barriers before changing disk.
            staged = self.path.with_name(self.path.name + ".staged")
            try:
                with staged.open("wb") as out:
                    if self.path.exists():
                        out.write(self.path.read_bytes())
                    out.write(_canonical(obj) + b"\n")
                    out.flush()
                    os.fsync(out.fileno())
                CaptureJournal(staged, lambda: now).read()
                with self.path.open("ab") as out:
                    out.write(_canonical(obj) + b"\n")
                    out.flush()
                    os.fsync(out.fileno())
            finally:
                staged.unlink(missing_ok=True)
            return CapturedEvent(kind, now, payload, previous, obj["hash"])
        finally:
            lock.unlink()

    def capture_snapshot(self, snapshot: SportsOnlySnapshot) -> CapturedEvent:
        return self._append("snapshot", _snapshot_payload(snapshot))

    def capture_seal(self, seal: ProbabilitySeal) -> CapturedEvent:
        return self._append("seal", {"snapshot_digest": seal.snapshot_digest,
                      "model_version": seal.model_version, "sealed_at": _timestamp(seal.sealed_at),
                      "probabilities": seal.probabilities, "low": seal.low, "high": seal.high,
                      "interval_status": seal.interval_status})

    def capture_quote(self, quote: ThreeWayQuote) -> CapturedEvent:
        return self._append("quote", {"bookmaker": quote.bookmaker,
                                     "received_at": _timestamp(quote.received_at), "odds": quote.odds})

    def capture_assessment(self, quote_hash: str) -> CapturedEvent:
        events = self.read()
        snapshot = next((_restore_snapshot(e.payload) for e in events if e.kind == "snapshot"), None)
        seal = next((_restore_seal(e.payload) for e in events if e.kind == "seal"), None)
        quoted = next((e for e in events if e.kind == "quote" and e.hash == quote_hash), None)
        if snapshot is None or seal is None or quoted is None:
            raise ValueError("unknown quote or missing sealed probability")
        p = quoted.payload
        quote = ThreeWayQuote(p["bookmaker"], _parse(p["received_at"]), tuple(p["odds"]))
        return self._append("assessment", {"quote_hash": quote_hash,
                                            "report": evaluate_1x2(snapshot, seal, quote)})

    def capture_source_signal(self, signal: SourceSignal) -> CapturedEvent:
        return self._append("source_signal", {
            "signal_id": signal.signal_id, "event_id": signal.event_id,
            "source_id": signal.source_id, "market": signal.market,
            "published_at": _timestamp(signal.published_at),
            "received_at": _timestamp(signal.received_at), "odds": str(signal.odds)})

    def capture_shadow_decision(self, assessment_hash: str, decision_id: str,
                                source_signal_id: str | None = None) -> CapturedEvent:
        events = self.read()
        snapshot = next((_restore_snapshot(e.payload) for e in events if e.kind == "snapshot"), None)
        seal = next((_restore_seal(e.payload) for e in events if e.kind == "seal"), None)
        if snapshot is None or seal is None or not any(
                e.kind == "assessment" and e.hash == assessment_hash for e in events):
            raise ValueError("unknown assessment or missing sealed probability")
        return self._append("decision", {
            "decision_id": decision_id, "event_id": snapshot.match_id,
            "kickoff": _timestamp(snapshot.kickoff), "decided_at": _timestamp(_utc(self.clock())),
            "status": DecisionStatus.SHADOW_EXPERIMENT.value,
            "reason": "uncalibrated model; no monetary authority",
            "probability_seal": seal.snapshot_digest,
            "source_signal_id": source_signal_id,
            "assessment_hash": assessment_hash, "monetary_authorized": False})
