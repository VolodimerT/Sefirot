# SEFIROT Scenario / Vector Audit v1 — 09.10.2026

**Status: READ-ONLY RESEARCH / POST-DECISION QA.**  
Branch: `feature/vector-first-audit-20261009`.

This layer implements lessons from the 08.10 review without changing
`src/sefirot`, BASELINE_V1, STRICT, Policy values, model probabilities,
canonical decisions, SQLite, provider access, Stake execution or money gates.

It is deliberately separate from CORE because the reviewed matches are
already-known outcomes and therefore cannot be used to tune or certify the
forecast model.

## Five rules now encoded

1. **CORE VECTOR FIRST**  
   Every research case is reduced to a structural vector before price/result
   interpretation: GOALS, SIDE, GOALS_WITH_SIDE_GUARD, GOALS_WITH_TIMING,
   OPEN_ACTIVITY_MIXED or an explicit MIXED family set.

2. **SIMPLE MARKET BENCHMARK**  
   The audit identifies the structurally simplest constituent leg(s) of the
   same hypothesis. This is only a comparison baseline; it does not claim that
   the simpler leg has better EV and does not choose by post-match result.

3. **MODEL / MARKET DIVERGENCE REVIEW**  
   Optional 1X2 model probabilities are compared with no-vig probabilities
   derived from supplied 1X2 odds. Existing Policy bands are reused:
   `Policy.divergence=0.10` -> `REVIEW_REQUIRED`;
   `Policy.extreme_divergence=0.20` -> `HARD_RESEARCH_STOP`.
   This is a research diagnostic only: `canonical_effect=NONE`.

4. **ARCHIVED LIVE QUALITY ANTI-PATTERN**  
   LIVE remains disabled in SEFIROT. The script only accepts a historical
   snapshot under `ARCHIVED_LIVE_REVIEW` for post-hoc QA. Possession,
   total shots and corners are treated as volume, not sufficient evidence.
   Quality confirmation requires at least two available quality metrics and
   at least two positive ones among shots on target, xG, big chances and
   shots in box. Output explicitly sets
   `live_runtime_enabled=false` and `usable_for_live_selection=false`.

5. **RESULT != EDGE**  
   Settlement labels never certify ex-ante edge or forecast superiority.
   Examples:
   - PLAY + WIN -> `PLAY_WIN_OUTCOME_ONLY`
   - PASS + WIN -> `PASS_WIN_FALSE_NEGATIVE_OUTCOME_ONLY`
   - PLAY + LOSS/PUSH/VOID -> `PLAY_NONWIN_OUTCOME_ONLY`
   In every case: `edge_conclusion=NOT_INFERABLE_FROM_SINGLE_SETTLEMENT`.

## Input contract

Minimal post-match example:

```json
{
  "schema": "scenario-vector-case-v1",
  "case_id": "synthetic-example",
  "phase": "POSTMATCH_REVIEW",
  "decision": "PLAY",
  "outcome": "WIN",
  "legs": [
    {"id": "total", "family": "GOALS", "market": "TOTAL_OVER_2.5", "outcome": "WIN"},
    {"id": "btts", "family": "GOALS", "market": "BTTS_YES", "outcome": "WIN"},
    {"id": "side", "family": "SIDE", "market": "DOUBLE_CHANCE_X2", "outcome": "WIN"}
  ],
  "model_1x2": {"HOME": 0.40, "DRAW": 0.27, "AWAY": 0.33},
  "market_1x2_odds": {"HOME": 2.45, "DRAW": 3.35, "AWAY": 2.85}
}
```

Allowed phases:
- `PREMATCH_REVIEW`
- `POSTMATCH_REVIEW`
- `ARCHIVED_LIVE_REVIEW`

Allowed families:
`GOALS`, `SIDE`, `CORNERS`, `TIMING`, `CARDS`, `SHOTS`, `OTHER`.

Manual case files are explicitly marked
`MANUAL_RESEARCH_CASE_NOT_PROVIDER_ATTESTED`. Do not use them as canonical
ledger evidence.

## Archived live QA example

```json
{
  "schema": "scenario-vector-case-v1",
  "case_id": "synthetic-live-review",
  "phase": "ARCHIVED_LIVE_REVIEW",
  "decision": "PLAY",
  "outcome": "LOSS",
  "legs": [
    {"id": "dc", "family": "SIDE", "market": "DOUBLE_CHANCE_1X", "outcome": "LOSS"}
  ],
  "archived_live_snapshot": {
    "focus_side": "HOME",
    "possession_home": 62,
    "possession_away": 38,
    "shots_home": 10,
    "shots_away": 5,
    "corners_home": 6,
    "corners_away": 5,
    "shots_on_target_home": 3,
    "shots_on_target_away": 3
  }
}
```

That snapshot returns `NO_QUALITY_CONFIRMATION`: volume dominance alone is
not enough.

## Command

```bash
python scripts/scenario_vector_audit.py data/vector-case.json \
  --output data/vector-audit.json

python -m unittest discover -s tests -p test_scenario_vector_audit.py -v
```

The output path is create-only. No overwrite.

## Safety / interpretation

- No API request.
- No bookmaker betslip or execution.
- No LIVE runtime.
- No model fit/refit.
- No probability modification.
- No canonical decision modification.
- No monetary permission.
- `stake=0`.
- Program tests validate software behavior only, not profitability.
- Already-viewed results must not be recycled as fresh HOLDOUT.
- Personal receipts, tickets, keys and private ledgers must not be committed.

This tool is for diagnosing **why a thesis was structurally right or wrong**
and whether a simpler market expressed the same vector with fewer conditions.
It does not turn winning tickets into proof of edge.
