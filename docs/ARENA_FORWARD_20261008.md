# SEFIROT ARENA v0.1 — locked-cohort forward audit (research only)

**Scope:** New standalone `scripts/arena_forward.py` and tests. Branch based on PR #12; no changes to `src/sefirot`, models, Policy, current CLI/work queue, ledger, stored predictions, bankroll, provider credentials, or API. Research only; no live, no execution, no express construction.

## Why this is the next experiment

Eight isolated reviews are useful only if they demonstrably reduce **avoidable false positives** without discarding more genuinely good selections. More reviewers do not change the underlying probability model. The first measurable contrast is **naive max-EV selection (EV >= 2% when quotes exist)** versus **ARENA research_focus (EV >= 2%, original blocks passed, no critic BLOCK)** on exactly the same **predeclared** fixtures and quotes. This is **NOT** a comparison against the real `Service.decide` baseline, which needs its own original decision receipts to be added later.

Do not count seven markets of one fixture as seven bets. Each arm has at most one hypothetical 1-unit single per fixture, PASS=0. No assumption about liquidity, slippage, bookmaker acceptance, commission, bankroll limits, or correlated legs. These are diagnostics, not trade recommendations.

## Workflow: two times, separate inputs

1. **Before ALL kickoffs**, prepare `fixtures.json` with a full, non-duplicated prospective registry, for example:

   ```json
   [
     {"match_id":"fixture-101","prediction_id":"<original immutable prediction ID>","kickoff":"2026-10-10T18:00:00+03:00"}
   ]
   ```

   Freeze the registry using the actual timestamp (never backdate):

   ```sh
   python scripts/arena_forward.py freeze fixtures.json --created-at 2026-10-09T19:00:00+03:00 --output arena_plan.json
   ```

2. On each fixture, run `scripts/arena_shadow.py` **before kickoff** on its *original sealed* prediction and post-seal quotes, preserving the full `arena_report` JSON from that moment. Do not send the result into the arena. The forward evaluator does not run any model or agent; it consumes frozen reports.
3. **After** receiving regulation-90 FT results, create `records.json` as a list of records:

   ```json
   [{
     "match_id":"fixture-101",
     "prediction":{ "...":"complete original SEALED prediction, with id" },
     "quotes":[ { "...":"original prematch quotes" } ],
     "arena":{ "...":"complete original ARENA report, with hash" },
     "result":{"match_id":"fixture-101","home_goals":2,"away_goals":1,"status":"FINISHED","source":"source receipt name","received_at":"2026-10-10T20:20:00+03:00"}
   }]
   ```

   Missing result: `"result": null`; missing capture: omit the corresponding record entirely. Either remains visible in the denominator.

   ```sh
   python scripts/arena_forward.py score arena_plan.json records.json --output arena_forward_scorecard.json
   ```

   Existing output files are never overwritten. There is no database write or external API access.

## Fail-closed invariants

- The plan's match IDs, prediction IDs and kickoff are frozen; unexpected or duplicate game records are rejected.
- `created_at` must precede each declared kickoff. Its timestamp and SHA hashes are **self-attested**, not independently certified: authentic time proof requires the existing signed/sealed durable ledger or a public immutable commit *made at the time*.
- Original prediction ID and hash, prematch status, chronology, Policy fingerprint, 1–7 market pool, exact 90-minute quote rules and quote-after-seal gate are rechecked.
- All market probabilities and EV are recomputed from the original prediction/quotes, not blindly trusted from the arena report. Missing prices or stale quotes cannot become selections. The frozen max-EV ranking and admissible focus are reproduced against all 8 critic statuses.
- Result is not accepted if it comes from a different match, lacks source and `FINISHED` status, arrives before/at kickoff, or has non-integer goals.
- Both arms must stay hypothetical: stake=0, monetary_permission=false, execution_enabled=false, verdict=ПРОПУСК.

## Metrics and interpretation

`planned`, `captured`, `settled`, `missing_capture`, `missing_results`, and `coverage=settled/planned` include all fixtures; `naive` and `arena` each include selected, settled/unsettled selections, WIN/PUSH/LOSS counts, total theoretical flat 1-unit profit and ROI/settled selection. `paired_unit_profit_delta` compares per-fixture profits (including PASS=0) only for fixtures with results.

A paired *date-clustered* exploratory bootstrap 95% interval appears only for at least **30 settled fixtures across at least 8 distinct UTC dates**; otherwise it is `null`. It is **not** a preregistered proof of superiority, and multiple screening designs increase selection bias. Even a positive 95% interval here is not an independently validated real-money edge.

If any planned fixture is missing, `synthetic=true` and evidence grade remains untrusted. The report always says `INCONCLUSIVE_NO_PROSPECTIVE_HOLDOUT` and `edge_certified=false`. It never upgrades SEFIROT's model, Money Gate, bankroll or main decisions.

## Experiment milestones before real utility claims

- Obtain unmodified prospective data from an accessible sports provider; preserve bookmaker line receipts, original `Service.decide` cards, genuine executed quotes and closes where available. Do not silently replace missing fixtures or retrofit a `created_at` timestamp.
- Pair original SEFIROT baseline with ARENA screens on all games; compare coverage, hypothetical per-match returns and rejection error modes, grouped by league, profile, market and week.
- Measure missed value too: compare the profitable **and** unprofitable opportunities vetoed by critics. Include fees/price availability in a separate execution analysis.
- Only then consider extending the GPT debate/roles or calibration. 100 GPT calls for the same prediction do not create independent evidence and can increase costs and correlated hallucinations.

Validation: `python -m unittest discover -s tests -p test_arena_forward.py -v`; tests use synthetic stubs locally and must be validated by GitHub CI against the actual repo before claiming integration complete.
