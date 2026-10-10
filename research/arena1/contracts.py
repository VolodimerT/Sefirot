"""Immutable, bounded hypotheses. Content binding is not external attestation."""
from dataclasses import asdict, dataclass, fields
import json

from scripts.arena_control import safe_id
from scripts.arena_shadow import ROLE_SPECS
from sefirot.contracts import canonical, strict, time

SCHEMA = 'arena1-finding-v1'
ROLES = {name: phase for name, phase, _ in ROLE_SPECS}
STATES = {'SUPPORTED', 'UNKNOWN', 'HARD_BLOCK'}


@dataclass(frozen=True, slots=True)
class Finding:
    schema: str
    fixture_id: str
    prediction_id: str
    decision_id: str | None
    model_hash: str
    code_hash: str
    policy_hash: str
    role: str
    phase: str
    category: str
    market_key: str | None
    premise_id: str | None
    evidence_ids: tuple[str, ...]
    independence_groups: tuple[str, ...]
    state: str
    effective_at: str
    mechanism: str
    test_condition: str
    expected_direction: str
    hypothesis_version: str
    unknowns: tuple[str, ...]
    counterexample: str | None
    action: str
    monetary_permission: bool

    def __post_init__(self):
        if self.schema != SCHEMA or self.hypothesis_version != '1.0':
            raise ValueError('finding schema/version')
        if not isinstance(self.role, str) or self.role not in ROLES or self.phase != ROLES[self.role]:
            raise ValueError('role/phase mismatch')
        if not isinstance(self.state, str) or self.state not in STATES:
            raise ValueError('finding state')
        if (self.expected_direction != 'UNQUANTIFIED' or self.action != 'REVIEW_ONLY'
                or self.monetary_permission is not False):
            raise ValueError('diagnostics cannot change probabilities or money')
        for key in ('fixture_id', 'prediction_id', 'model_hash', 'code_hash', 'policy_hash', 'category'):
            safe_id(getattr(self, key))
        for value in (self.decision_id, self.premise_id):
            if value is not None:
                safe_id(value)
        if self.market_key is not None:
            safe_id(self.market_key)
        for key in ('evidence_ids', 'independence_groups'):
            items = getattr(self, key)
            if type(items) is not tuple or len(items) > 24:
                raise ValueError('bounded unique identities required')
            for item in items:
                safe_id(item)
            if len(set(items)) != len(items):
                raise ValueError('bounded unique identities required')
        if (type(self.unknowns) is not tuple or len(self.unknowns) > 12
                or any(not isinstance(s, str) or not 1 <= len(s) <= 120 for s in self.unknowns)):
            raise ValueError('bounded unknowns required')
        for key in ('mechanism', 'test_condition'):
            value = getattr(self, key)
            if not isinstance(value, str) or not 1 <= len(value) <= 1000:
                raise ValueError('bounded hypothesis text required')
        if time(self.effective_at).isoformat() != self.effective_at:
            raise ValueError('canonical UTC effective_at required')
        if self.counterexample is not None:
            if not isinstance(self.counterexample, str) or len(self.counterexample) > 8000:
                raise ValueError('bounded numerical counterexample required')
            if canonical(json.loads(self.counterexample)) != self.counterexample:
                raise ValueError('canonical counterexample required')
        if self.state == 'HARD_BLOCK' and (self.market_key is None or not self.evidence_ids
                                            or self.premise_id not in self.evidence_ids):
            raise ValueError('market-local block needs a specific fact premise')
        if self.state == 'UNKNOWN' and not self.unknowns:
            raise ValueError('unknown must name missing information')

    def to_dict(self):
        return json.loads(canonical(asdict(self)))

    @classmethod
    def from_dict(cls, item):
        names = tuple(f.name for f in fields(cls))
        strict(item, names)
        converted = dict(item)
        for key in ('evidence_ids', 'independence_groups', 'unknowns'):
            if type(item[key]) is not list:
                raise ValueError('finding arrays required')
            converted[key] = tuple(item[key])
        return cls(**converted)
