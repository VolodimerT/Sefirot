> Историческая оценка CORE 0.7. Текущая матрица: [AUDIT_TRACEABILITY.md](AUDIT_TRACEABILITY.md).

# SEFIROT audit foundation: implementation status

**Checked:** 2026-09-26  
**Code checked:** SEFIROT CORE v0.7 in this repository  
**Purpose:** trace the requirements in `SEFIROT_AUDIT_FOUNDATION_v0.1.md` to code that currently exists. A passing test suite proves only the behaviors covered by those tests; it does not mean this matrix is complete.

## Status definitions

- **Partial:** a narrow mechanism exists, but the audit requirement is not satisfied end to end.
- **Missing:** there is no operative implementation in the current CLI/core.
- **Deferred by foundation:** the source audit explicitly leaves the topic for later; it must not be presented as finished.

## Constitution

| Rule | Status | What the code actually does / remaining gap |
|---|---|---|
| F1 independent probability before odds | Partial | `model.py` estimates 1X2 before the CLI asks for prices. It is a hand-set Elo illustration, not a calibrated or validated probability model. |
| F2 final permission gate | Partial | CLI always ends in PASS and cannot place a bet. There is no playable/conditions/skip/unplayable verdict system or risk approval. |
| F3 unseen-data validation | Partial | `CaptureJournal` orders and hashes snapshots, probability seals, and later quotes. There is no trustworthy external timestamp, curated unseen dataset, or release validation proving generalization. |
| F4 degradation detection and isolation | Missing | No monitoring, market/model health states, freeze/rollback workflow, or recovery gate. |
| F5 explanation and reproducibility | Partial | Selected inputs and events are serialized and hash chained. Full scenario, evidence rationale, conflicts, stress results, and final decision reasons are not captured as one reproducible analysis. Local hashes are not tamper-proof. |
| F6 unknown mode | Partial | New teams without enough history produce PASS. No novelty detection for league, format, coach, roster, style, or market movement. |
| F7 fact / inference / assumption | Partial | Inputs can be marked FACT or ASSUMPTION. Inferences are not a distinct typed evidence state and key assumptions are not scored. |
| F8 critical weakness cannot be averaged away | Missing | There is no trust-score aggregation. The program does not yet implement the required evidence/quality/conflict gates. |

## Elevated requirements

| Rule | Status | Remaining gap |
|---|---|---|
| P1 match pre-filter | Partial | Insufficient model history stops the calculation; no separate match eligibility/data-quality screen. |
| P2 scenario before market | Partial | A 1X2 probability is produced before odds, but there is no modeled match scenario or later market comparison. |
| P3 evidence-backed probability/range | Partial | Elo output and Low/Base/High values are heuristic and explicitly uncalibrated; roster/context/scenario evidence is absent. |
| P4 conflict and recalculation | Missing | No conflict registry, authority/recency comparison, dependency graph, or mandatory recalculation path. |
| P5 independent death test | Partial | `market_link.py` can settle selected scorelines against a small supported market set. It does not generate complete scenarios or block the end-to-end decision. |
| P6 data/source quality | Partial | Source name and timestamps are required for captured facts; source identity/reliability and corroboration are not verified. |
| P7 pre-match recheck/price freshness | Missing | No lineup/news refresh, current-price recheck, opening/final/entry/closing odds comparison, or stale-data gate. |
| P8 error memory | Partial | A local decision/execution ledger records a limited set of process states. It does not classify model misses and feed recurring causes into subsystem health. |
| P9 post-match decision audit | Partial | `backtest.py` computes multiclass Brier on eligible 1X2 history. It does not compare scenario, price, data, and decision quality after each result. |
| P10 competence by league/market/scenario | Missing | No competence zones or stratified history. |
| P11 risk sizing and limits | Missing | No stake sizing, per-match/day limits, drawdown-aware limits, or risk engine. Monetary execution remains disabled. |
| P12 correlated exposure | Partial | `audit.py` can flag repeated event exposure in an in-memory ledger. It does not quantify dependence by team/league/scenario/model or manage portfolio risk. |
| P13 noise protection | Missing | No sample-size confidence, stability test, independent-period validation, or signal-promotion gate. |
| P14 version comparison/rollback | Partial | A walk-forward 1X2 Brier calculation exists. No paired old/new evaluation, improvement threshold, or rollback process. |
| P15 manual override control | Partial | Some execution deviations can be represented in the ledger. There is no full immutable before/after decision record with allowed-cause validation. |
| P16 contextual Sephirot ratings | Missing | No dynamic per-subsystem rating, sample confidence, or hard veto separation. |

## Ordinary and deferred requirements

| Rule | Status | Remaining gap |
|---|---|---|
| N1 compare cleaner main markets | Missing | The CLI evaluates 1X2 only. It does not compare double chance, DNB, handicaps, goals, BTTS, or team totals. |
| N2 explain line movement / closing price | Missing | No line-history data, movement explanation, or CLV calculation. |
| D1 Expresses | Deferred by foundation | Not implemented, as required until separately designed and approved. |
| D2 Small markets | Deferred by foundation | Not implemented, as required; no corners/fouls/shots/cards. |

## Current truthful scope

The repository is a **local 1X2 research prototype**, not an implementation of the full audit foundation. It contains arithmetic, a heuristic Elo illustration, manually entered sports facts, a hash-chained local journal, selected scoreline settlement diagnostics, a limited in-memory process ledger, and a Brier walk-forward utility. It has no live betting, automated data providers, calibrated production model, Supabase, complete Sephirot architecture, or monetary betting permission.

The 43 tests passing on Python 3.13 verify selected contracts of these existing components only. They do not test requirements marked missing or validate betting performance.

## Implementation sequence required before claiming audit coverage

1. Publish the final architecture and trace each audit rule to an owner, input/output, veto/recalculation authority, and test.
2. Build typed evidence, provenance, data-quality gates, unknown-mode state, scenario record, and conflict/recalculation flow.
3. Add main-market representations and settlement/math contracts; keep expressions and small markets deferred.
4. Add price freshness/recheck, non-averaging vetoes, and a decision record that ends in PASS unless every gate passes.
5. Add result/closing-price ingestion, post-match decision audit, Brier/CLV and stratified competence reporting.
6. Add degradation monitoring, contextual Sephirot ratings, paired model-version validation, and rollback gates.
7. Only then consider stake sizing; monetary permission stays closed until untouched-data validation and user review.

