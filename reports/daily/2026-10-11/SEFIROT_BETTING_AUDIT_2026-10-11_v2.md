# SEFIROT Daily Audit — 2026-10-11, version 2 (engineering addendum)

This v2 adds the **mandatory improvement/optimization review** to the previously archived v1. The original v1 is not modified. To avoid copying personal betting receipts into a public repository, the private full consolidated audit is provided as a separate local downloadable artifact. This public v2 records only implementation proposals.

## Lessons of this session

- Correlated LIVE tickets need aggregated per-match and per-outcome risk monitoring.
- First-half low xG and zero shots on target are not by themselves a valid second-half forecast.
- Same-match goal versus corner/card combinations lack an empirically validated joint distribution.
- A whole-number Asian line can PUSH, requiring a deterministic settlement recalculation.
- A winning research candidate does not retroactively convert an original PASS into a permitted BET.

## Improvement and optimization backlog

| ID | Priority | Proposal | Acceptance gate | State |
|---|---|---|---|---|
| SFR-001 | P0 | Aggregate match, coupon and dependent-outcome exposure under the existing risk caps | Duplicate and correlated scenario tests; block oversize exposure | PROPOSED |
| SFR-002 | P0 | Separate LIVE observations from prematch forecast; stale/contradictory event and quote timestamps fail closed | Score/minute/event mismatch tests, confirmed fresh receipts | PROPOSED |
| SFR-003 | P0 | Settlement engine with WIN, LOSS, integer Asian PUSH, VOID and mixed-parlay payout | Exact replay against verified bookmaker settlements | PROPOSED |
| SFR-004 | P0 | Explicit verified quote provenance and CORE PASS/RESEARCH labeling | No candidate without fresh matching quote and seal | PROPOSED |
| SFR-005 | P0 | Date-versioned audit checkpoint and read-back verification | Repeated runs do not overwrite originals; checksums verified | PROPOSED |
| SFR-006 | P1 | Licensed historical corners, cards, shots data with venue/referee/time validity | Independent chronological holdout >=100 fixtures per league and calibration benchmarks | PROPOSED |
| SFR-007 | P1 | Joint same-match probability for result, corners and cards | Tested dependence and bookmaker price comparison, no marginal multiplication | PROPOSED |
| SFR-008 | P1 | Situation-aware PREMATCH/LIVE routing and rapid quote-verified alternatives | No fabricated prices; an empty list produces PASS | PROPOSED |
| SFR-009 | P1 | Prospective decision/outcome scoring separated by tipster, CORE and research | Frozen predictions, outcome integrity and CLV coverage | PROPOSED |
| SFR-010 | P2 | Concise mobile LIVE decision card and recoverable receipts | Recovery test and short verified decision summary | PROPOSED |

## Next steps

Prioritize SFR-001 through SFR-005 before feature expansion. Keep CORE 2.4.2, BASELINE_V1, STRICT and pre-existing seals unchanged. Experimental changes require isolated tests and independent holdout validation before any discussion of monetary permission.

Every future daily audit must contain a dedicated **Improvement and optimization backlog**, with priority, evidence, intended change, acceptance criteria and explicit implementation status. See [daily report template](../DAILY_AUDIT_TEMPLATE_V1.md).

**Version policy:** preserve v1, publish corrections as v3/v4, and do not claim any proposed feature was deployed.