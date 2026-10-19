# SEFIROT V4.2 — risk receipt chronology + explicit historical UTC day

Status: isolated draft integration patch, **not production**. Date: 2026-10-12.
Base: PR #37 head `c4d2495086acf5f125d7f7ba8d8294ce90bdf84c`.
Scope: `src/sefirot/risk.py` and 14 synthetic regression probes only.

## What the actual Service already enforces

- `Service.execution` requires placement at/after its original sealed decision and strictly before kickoff.
- `Service.result` requires `finished_at` strictly after kickoff and `received_at` not before finish.
- `Service.context` derives an optional `settled_at` from an original recorded result receipt; it does not accept arbitrary caller-provided settlement times during normal reads.
- Thus the earlier isolated risk acceptance of `settled_at < at` was **not** proof that the canonical Service allows an impossible result-to-execution sequence.

## Why this patch exists

`size_risk()` is reused by `engine.decide` and execution recheck. It previously accepted an internally malformed exposure row with a settled receipt timestamp before the placement timestamp, or a dated settlement receipt from the future. This patch explicitly rejects either rather than relying solely on upstream data provenance. It also rejects malformed non-null settlement timestamps. Valid `settled_at == at` is still permitted for compatibility; it is not automatically proof of bookmaker settlement.

No risk sizing coefficients, caps, bankroll state, Poisson/Davidson model, sealed probability, original archived decision or policy are changed. No live betting, martingale, odds gathering, paid API or auto-execution.

### Accounting day — deliberately unchanged

The legacy risk day is `time(at).date()`, and `time()` normalizes ISO timestamps to UTC. Therefore the risk day is **00:00–24:00 UTC**, not `Europe/Kyiv` or bookmaker-local time, even across daylight-saving changes. Two earlier failing probes demanding Kyiv-local day were **contract hypotheses**, not proven defects. New tests freeze the existing UTC semantics and show the local/UTC difference explicitly. Changing risk-day timezone requires a separately approved migration plan, fresh versioning and ledger reconciliation, and bookmaker daily statement evidence.

## Code-identity implications

`risk.py` is a CORE source file: the build-wide `code_hash` **changes**. The fitted-probability `model_code_hash` should be unchanged because `risk.py` is not in `MODEL_MODULES`. Historical seals are not rewritten or re-signed. Existing approved monetary execution must not reuse a build mismatch: it is already fail-closed by `Service.execution`. Do not promote/merge until 4-platform exact-head CI and historical replay/integrity are independently checked.

## Acceptance tests

`tests/test_risk_receipt_v42.py` covers:
- normal 0.5% cap and existing same-fixture block
- inversion `settled_at < placed_at`, future receipt, future placement, invalid timestamp
- unchanged same-day spent cap, allowed exact-time equality
- two Kyiv/UTC cross-midnight cases and explicit DST-offset case
- equivalent time-offset chronology
- real `Service.execution` predates-decision rejection and real `Service.result` predates-kickoff rejection using read-only synthetic stub repositories.

Synthetic validations are **engineering correctness**, not odds-provider origin, profitable model calibration, risk-day policy approval or proof of execution feasibility.

## Remaining follow-ups (do not promote from this patch)

1. Full original-row read-only `Repository` + `Service` tests with the true event log and input schemas; artificial repository stubs in this PR cover two Service gates, not complete settlement provenance.
2. Define the operator's accounting day (UTC vs bookmaker statement vs Kyiv). Do not conflate daily audit/reporting day with risk day automatically. Add immutable timezone identifier and no-downgrade migration procedure only after explicit owner choice.
3. Store a hash-attested risk-day report `effective_UTC_date / open_same_match / spent_today / locked_groups / mismatched_source` without changing bets or snapshot history.
4. Reconcile +54.83 UAH unexplained 2026-10-09 bookkeeping difference against original receipts.
5. Continue real-data / forward-holdout / verified-quote gates from issue #33. This change creates no new value or money permission.
