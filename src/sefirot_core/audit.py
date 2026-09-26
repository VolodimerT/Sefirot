"""Immutable evidence ledger and fail-closed controls drawn from execution audits.

Historical execution can be logged even when it violated policy; logging never
turns it into a system-authorized bet. This module offers no monetary permission.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from .core import _utc


class DecisionStatus(str, Enum):
    NOT_EVALUABLE = "NOT_EVALUABLE"
    WAIT_ACTIVE = "WAIT_ACTIVE"
    WAIT_EXPIRED = "WAIT_EXPIRED"
    PASS_NO_EDGE = "PASS_NO_EDGE"
    PASS_RISK = "PASS_RISK"
    SHADOW_EXPERIMENT = "SHADOW_EXPERIMENT"


def _money(value: object, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be finite money") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{name} must be finite nonnegative money")
    return number


def _odds(value: object) -> Decimal:
    number = _money(value, "odds")
    if number <= 1:
        raise ValueError("decimal odds must exceed one")
    return number


@dataclass(frozen=True, slots=True)
class SourceSignal:
    signal_id: str
    event_id: str
    source_id: str
    market: str
    published_at: datetime
    received_at: datetime
    odds: Decimal

    def __post_init__(self) -> None:
        if not all((self.signal_id, self.event_id, self.source_id, self.market)):
            raise ValueError("source signal needs identity, event, market and source")
        if _utc(self.published_at) > _utc(self.received_at):
            raise ValueError("signal received before publication")
        _odds(self.odds)


@dataclass(frozen=True, slots=True)
class SystemDecision:
    decision_id: str
    event_id: str
    kickoff: datetime
    decided_at: datetime
    status: DecisionStatus
    reason: str
    probability_seal: str | None = None
    source_signal_id: str | None = None

    def __post_init__(self) -> None:
        if not self.decision_id or not self.event_id or not self.reason:
            raise ValueError("decision needs ids and reason")
        if not isinstance(self.status, DecisionStatus) or _utc(self.decided_at) >= _utc(self.kickoff):
            raise ValueError("only prematch decision status can be logged")


@dataclass(frozen=True, slots=True)
class WaitCase:
    decision_id: str
    owner: str
    awaiting: str
    deadline: datetime

    def __post_init__(self) -> None:
        if not self.decision_id or not self.owner or not self.awaiting:
            raise ValueError("WAIT must name an owner and missing evidence")
        _utc(self.deadline)


@dataclass(frozen=True, slots=True)
class Execution:
    bet_id: str
    event_id: str
    kickoff: datetime
    placed_at: datetime
    market: str
    odds: Decimal
    stake: Decimal
    payout: Decimal | None
    bet_type: str = "SINGLE"
    decision_id: str | None = None
    source_signal_id: str | None = None

    def __post_init__(self) -> None:
        if not self.bet_id or not self.event_id or not self.market or self.bet_type not in {"SINGLE", "EXPRESS"}:
            raise ValueError("execution needs ids, market and valid type")
        _utc(self.kickoff)
        _utc(self.placed_at)
        _odds(self.odds)
        if _money(self.stake, "stake") == 0:
            raise ValueError("stake must exceed zero")
        if self.payout is not None:
            _money(self.payout, "payout")


@dataclass(frozen=True, slots=True)
class ExecutionAssessment:
    bet_id: str
    flags: tuple[str, ...]
    system_bet: bool = False


@dataclass(frozen=True, slots=True)
class PrematchCandidate:
    event_id: str
    kickoff: datetime
    checked_at: datetime
    market_kind: str
    has_probability_seal: bool
    has_current_price: bool
    wait_owner: str | None = None
    wait_deadline: datetime | None = None


@dataclass(frozen=True, slots=True)
class CandidateScreen:
    status: DecisionStatus
    reasons: tuple[str, ...]
    monetary_authorized: bool = False


def screen_candidate(candidate: PrematchCandidate, ledger: AuditLedger) -> CandidateScreen:
    """Prematch and event exposure lock before any paper analysis.

    Unsupported markets never become payable just because a price exists.
    """
    if not candidate.event_id:
        raise ValueError("event id is required")
    _utc(candidate.checked_at)
    _utc(candidate.kickoff)
    if _utc(candidate.checked_at) >= _utc(candidate.kickoff):
        return CandidateScreen(DecisionStatus.PASS_RISK, ("LIVE_OUTSIDE_PREMATCH",))
    if any(x.event_id == candidate.event_id for x in ledger.executions):
        return CandidateScreen(DecisionStatus.PASS_RISK, ("EVENT_ALREADY_EXECUTED",))
    if candidate.market_kind == "EXPRESS":
        return CandidateScreen(DecisionStatus.PASS_RISK, ("EXPRESS_NOT_IMPLEMENTED",))
    if candidate.market_kind != "1X2":
        return CandidateScreen(DecisionStatus.NOT_EVALUABLE, ("MARKET_NOT_MODELED",))
    if not candidate.has_probability_seal:
        return CandidateScreen(DecisionStatus.NOT_EVALUABLE, ("P_UNAVAILABLE",))
    if not candidate.has_current_price:
        if candidate.wait_owner and candidate.wait_deadline is not None:
            if _utc(candidate.wait_deadline) < _utc(candidate.kickoff):
                if _utc(candidate.wait_deadline) <= _utc(candidate.checked_at):
                    return CandidateScreen(DecisionStatus.WAIT_EXPIRED, ("PRICE_NOT_RECEIVED",))
                return CandidateScreen(DecisionStatus.WAIT_ACTIVE, ("PRICE_PENDING",))
        return CandidateScreen(DecisionStatus.NOT_EVALUABLE, ("PRICE_UNAVAILABLE_WITHOUT_VALID_WAIT",))
    return CandidateScreen(DecisionStatus.SHADOW_EXPERIMENT, ("UNVALIDATED_MODEL_AND_RISK",))


@dataclass(frozen=True, slots=True)
class AuditLedger:
    signals: tuple[SourceSignal, ...] = ()
    decisions: tuple[SystemDecision, ...] = ()
    executions: tuple[Execution, ...] = ()
    waits: tuple[WaitCase, ...] = ()

    def with_signal(self, signal: SourceSignal) -> AuditLedger:
        if any(x.signal_id == signal.signal_id for x in self.signals):
            raise ValueError("duplicate signal id")
        return replace(self, signals=self.signals + (signal,))

    def with_decision(self, decision: SystemDecision, wait: WaitCase | None = None) -> AuditLedger:
        if any(x.decision_id == decision.decision_id for x in self.decisions):
            raise ValueError("duplicate decision id")
        if decision.source_signal_id is not None:
            signal = next((s for s in self.signals if s.signal_id == decision.source_signal_id), None)
            if signal is None or signal.event_id != decision.event_id or _utc(signal.received_at) > _utc(decision.decided_at):
                raise ValueError("decision cannot cite unknown, late or wrong-event signal")
        if decision.status is DecisionStatus.WAIT_ACTIVE:
            if wait is None or wait.decision_id != decision.decision_id or _utc(wait.deadline) <= _utc(decision.decided_at) or _utc(wait.deadline) >= _utc(decision.kickoff):
                raise ValueError("WAIT needs a named owner and future prematch deadline")
        elif wait is not None:
            raise ValueError("wait metadata belongs only to active WAIT")
        return replace(self, decisions=self.decisions + (decision,),
                       waits=self.waits + ((wait,) if wait else ()))

    def with_execution(self, execution: Execution) -> tuple[AuditLedger, ExecutionAssessment]:
        if any(x.bet_id == execution.bet_id for x in self.executions):
            raise ValueError("duplicate bet id")
        flags: list[str] = []
        if _utc(execution.placed_at) >= _utc(execution.kickoff):
            flags.append("LIVE_OUTSIDE_PREMATCH")
        if execution.bet_type == "EXPRESS":
            flags.append("EXPRESS_NOT_IMPLEMENTED")
        if any(x.event_id == execution.event_id for x in self.executions):
            flags.append("DUPLICATE_EVENT_EXPOSURE")
        decision = next((d for d in self.decisions if d.decision_id == execution.decision_id), None)
        if decision is None or decision.event_id != execution.event_id or _utc(decision.decided_at) > _utc(execution.placed_at):
            flags.append("NO_MATCHING_PREMATCH_SYSTEM_DECISION")
        else:
            flags.append("NO_MONETARY_AUTHORITY_IN_SHADOW_MODE")
        if execution.source_signal_id is not None and not any(s.signal_id == execution.source_signal_id and s.event_id == execution.event_id and _utc(s.received_at) <= _utc(execution.placed_at) for s in self.signals):
            flags.append("UNKNOWN_SOURCE_SIGNAL")
        # An actual user coupon must remain visible for accounting, even if flags reveal a breach.
        return replace(self, executions=self.executions + (execution,)), ExecutionAssessment(execution.bet_id, tuple(flags))

    def expire_waits(self, now: datetime) -> tuple[str, ...]:
        _utc(now)
        return tuple(w.decision_id for w in self.waits if _utc(now) >= _utc(w.deadline))

    def settled_totals(self) -> tuple[Decimal, Decimal, Decimal]:
        settled = tuple(x for x in self.executions if x.payout is not None)
        turnover = sum((x.stake for x in settled), Decimal(0))
        payout = sum((x.payout for x in settled), Decimal(0))
        return turnover, payout, payout - turnover
