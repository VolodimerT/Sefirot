# Independent adversarial architecture review — CORE 1.0 research

Checked against every Foundation F1–F8 and P1–P16. This is a self-review from a separate pass, not an external third-party audit. Synthetic unit tests do not establish betting advantage.

| Rule | State | Concrete evidence / outstanding risk |
|---|---|---|
| F1 | Implemented structurally | `system._distribution` uses historical scores, never odds; seal is built before quotes. No market fitting. Historical goal estimates remain unvalidated. |
| F2 | Fail closed | Final verdict PASS, zero stake, immutable veto list even for positive EV. Genuine BET authorization unavailable until empirical release gate. |
| F3 | Partial | Timestamped prematch snapshot, sealed prediction and noneditable SQLite row; no trusted external time authority or independently curated untouched fixtures. |
| F4 | Partial | `governance.competence` exposes UNKNOWN/WORKING/WEAK/FROZEN and system blocks weak/frozen. No automated rolling incident investigation or recovery certification. |
| F5 | Partial | Input and decision digests, linked audit events and reasons. Hashes on writable local disk are not externally tamper-proof; probability seal hash must be independently archived. |
| F6 | Implemented gate | Novelty + undersampled teams switch UNKNOWN and PASS. Automatic coach/rotation/style recognition needs sourced feeds. |
| F7 | Implemented gate | Typed facts, inference and assumption; listed critical assumption vetoed. Completeness relies on accurate input marking. |
| F8 | Implemented gate | Vetoes cannot be averaged with ratings; limiting factor recorded. Trust estimates are heuristic. |
| P1–P3 | Partial | Team/history prefilter; scenario captured before pricing; probability from goals and score distribution, intervals explicitly UNCALIBRATED. Scenario is entered by analyst and does not alter model numerically. |
| P4–P6 | Partial | Conflicts require new snapshot; scenario counterexample death test; source timestamps and critical assumptions. Source trust/corroboration are manually supplied. |
| P7 | Partial | Recheck flag and timestamp and prematch quote gate; lineup/news source verification and freshness interval not independently enforced. |
| P8–P10 | Partial | SQLite Brier by league/model/market, simple cause classifier and competence zones; baseline sampling, causal diagnosis and isolated new validation remain unfinished. |
| P11–P12 | Closed | Stake always zero, exposure requires review. No stake-sizing formula or automatic correlation estimation; deliberately no betting permission. |
| P13–P16 | Partial | Sample-aware competence and paired score review (never self-release), append-only predictions; override protocol, robust drift significance, rollback automation and validated sephira ratings still missing. |
| N1–N2 | Partial | 1X2, DC, DNB, simple handicap, totals, BTTS, team totals evaluated main-first; signed price movement indicator and CLV. No bookmaker-specific settlement rules, complete full-line validation or causal price movement attribution. |
| D1–D2 | Deferred | Express, live and small markets rejected; doubling is absent. |

## Critical unresolved findings

1. Goals heuristic has no proven calibration or coverage, and the 11-goal tail is folded at 10. Under extreme score conditions, total/handicap estimates can be distorted.
2. The decision input and audit chain reside under one writable filesystem; an administrator could rewrite both. Use externally timestamped checksums before trusting unseen holdout evidence.
3. User-provided flags (`calibration_validated`, `price_groups_complete`, `tactical_fit`, `recheck`) are assertions, not independently verified claims. The certified release veto remains hard coded to prevent a false BET.
4. Market score simulation assumes independent Poisson goals. Correlated goals, injuries, lineups, tactics and league context lack quantitative treatment. All published EV is illustrative.
5. SQLite captures historical closing odds, but does not acquire data automatically. Missing odds do not justify a bet.
6. There is no approved methodology for uncertainty intervals, stake sizing, deployment gate, or acceptable performance threshold in the audit foundation. Their final design remains an open decision; none is silently invented.
7. Unsupported quarter Asian lines, bookmaker-specific grading, pushes on voids, postponements and score corrections require dedicated rules and tests before practical use.

## Reproduction

`python test_sefirot.py`; `python SEFIROT_CORE.py examples/full_case.json --db data/research.sqlite`. Synthetic demo expected PASS and zero stake. No live or automatic wager route exists.
