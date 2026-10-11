"""Strict status-only bridge contracts. Client fields are assertions, never facts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timezone
import re

from sefirot.contracts import digest, time


def identifier(value, name, maximum=128):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9:_./-]{1," + str(maximum) + "}", value):
        raise ValueError("invalid " + name)
    return value


def hash_id(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("invalid " + name)
    return value


def utc(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be an aware ISO string")
    return time(value).astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    source_id: str
    source_revision: int
    receipt_hash: str
    model_hash: str

    def __post_init__(self):
        identifier(self.source_id, "source_id")
        if type(self.source_revision) is not int or not 0 <= self.source_revision <= 2**31-1:
            raise ValueError("invalid source_revision")
        hash_id(self.receipt_hash, "receipt_hash")
        hash_id(self.model_hash, "model_hash")


@dataclass(frozen=True, slots=True)
class SituationRequest:
    fixture_id: str
    provider_status: str
    kickoff: str
    status_observed_at: str
    request_at: str
    intent: str
    depth: str
    original_provider_receipt_id: str
    identity: SourceIdentity

    def __post_init__(self):
        identifier(self.fixture_id, "fixture_id")
        if not isinstance(self.provider_status, str) or not re.fullmatch(r"[A-Z0-9_]{1,16}", self.provider_status):
            raise ValueError("invalid provider_status")
        for key in ("kickoff", "status_observed_at", "request_at"):
            object.__setattr__(self, key, utc(getattr(self, key)))
        if self.intent not in ("auto", "prematch", "live") or self.depth not in ("auto", "fast", "deep"):
            raise ValueError("unsupported intent or depth")
        hash_id(self.original_provider_receipt_id, "original_provider_receipt_id")
        if not isinstance(self.identity, SourceIdentity):
            raise ValueError("typed source identity required")
        if self.original_provider_receipt_id != self.identity.receipt_hash:
            raise ValueError("receipt identity mismatch")

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("exact situation request contract required")
        identity = data["identity"]
        if not isinstance(identity, dict) or set(identity) != set(SourceIdentity.__dataclass_fields__):
            raise ValueError("exact source identity required")
        return cls(**{**data, "identity": SourceIdentity(**identity)})

    def to_dict(self):
        return asdict(self)

    @property
    def request_key(self):
        return digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class SituationResponse:
    schema: str
    fixture_id: str
    phase: str
    depth: str
    reasons: tuple[str, ...]
    next_action: str
    request_at: str
    evaluated_at: str
    original_provider_receipt_id: str
    source_identity: SourceIdentity
    source_attestation: str
    collector_authenticated: bool
    external_origin_verified: bool
    synthetic: bool
    provider_status: str | None
    kickoff: str | None
    status_observed_at: str | None
    status_received_at: str | None
    source_age_seconds: float | None
    core_verdict: str
    core_invoked: bool
    prematch_core_allowed: bool
    live_betting_allowed: bool
    monetary_permission: bool
    execution_enabled: bool
    model_hash: str
    code_hash: str
    policy_hash: str
    request_key: str
    measured_processing_ms: float
    latency_scope: str
    latency_target_validated: bool
    summary: str

    def __post_init__(self):
        if self.phase not in ("PREMATCH", "LIVE_RESEARCH", "POSTMATCH", "HOLD"):
            raise ValueError("invalid response phase")
        if any((self.core_invoked, self.prematch_core_allowed, self.live_betting_allowed,
                self.monetary_permission, self.execution_enabled, self.external_origin_verified)):
            raise ValueError("P1 status-only response cannot grant permissions")
        if self.core_verdict not in ("NO_SOURCE", "NOT_EVALUABLE") or len(self.reasons) != 1:
            raise ValueError("one reason and unchanged CORE verdict required")
        if self.measured_processing_ms < 0:
            raise ValueError("invalid measured processing time")

    def to_dict(self):
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        return result
