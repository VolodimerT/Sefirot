# SEFIROT — Multi-season FT collection for prospective calibration

Date: 2026-10-08. Status: optional research-collection improvement,
**not** a calibrated model, new independent HOLDOUT, or money approval.

## Corrected bottleneck

The existing `data-session` obtained completed FT history only for the
upcoming fixture's `league + current season`. Early in the season a team can
have fewer than the required eight policy-eligible historical matches even
though correctly observed matches exist in earlier seasons.

An explicit and bounded research option is now available:

```bash
python sefirot.py data-session --date NEXT_FUTURE_DAY \
  --directory data/session-next-new \
  --league-profile 9=MEN --source-reliability 0.95 \
  --history-seasons-back 1 --max-requests 12 --quota-reserve 5 --text
```

- `--history-seasons-back 0` **is the default**, preserving existing
  behavior and budget. `1` adds the immediately preceding league season;
  `2` adds two earlier seasons.
- The query list is **fully declared before history collection or
  original match sealing**. History requests order by explicit league ID,
  then descending season (current first).
- All history remains subject to the existing
  `policy.history_days`, trusted API-Football receipt, real received
  timestamp, league ID/season and completed `FT` filtering.
  **Older data is not assigned a fictitious old receipt timestamp.**
- The original request budget (`--max-requests`, max 50),
  `--quota-reserve`, rate limits, suspension/403 handling and matching
  league-season tests remain active. A missing earlier-season entitlement
  is recorded as `SEASON_ACCESS_DENIED`, not worked around. No retry.
- Old season rows are joined to current team only through exact provider
  **team IDs** and same league, never guessed team names. No cross-league
  pooling. API-Football paging or partial results fail closed.
- The output `REPORT.json` records `history_seasons_back`,
  `predeclared_history_queries`, actual `history_queries` status and
  original fixture coverage in the denominator. Each received fixture is
  de-duplicated by provider ID in the sports archive.
- The user must choose a new session directory, future event date,
  explicit competition profile and source reliability. Multiple sessions
  on the same fixture do not increase calibration sample size.

## Before / after

Scenario: an upcoming game has 0 completed team matches in the currently
reported league season, but the preceding season contains eight legitimate,
pre-match observed completed fixtures for each team:

- Default: `INSUFFICIENT_HISTORY`, no forecast is sealed.
- Explicit `--history-seasons-back 1`, if those authentic packets are
  obtained within existing time/plan/policy gates: those previous-season
  fixtures contribute to eligible history and research forecasts can
  be sealed **before** kickoff.

This example is a fixture-mocked **software regression**, not evidence
that the actual provider currently grants older seasons or that the
accuracy of real predictions improved.

## Calibration continuation

Original `src/sefirot/probability.py`, the 7 `MODEL_MODULES`,
`Service.calibrate`, `Service.validate`, original `Policy` and
real-money gates are **unchanged**.

1. Restore access through the account owner to the approved sports provider.
2. Collect prospective CALIBRATION fixtures and FT history using the
   exact new season-selection mode when necessary.
3. Settle through original API source receipts, run
   `scripts/calibration_history_triage.py` and
   `scripts/calibration_fit_gate.py` without `--fit`.
4. Only after source-backed fit gates pass, an operator can explicitly
   run `calibration_fit_gate.py --fit` on the **existing** research ledger.
5. Freeze the artifact, choose a **new** unseen HOLDOUT (not any historical
   already-reviewed TEST), score it and run original `Service.validate`
   with context-specific minimums. Keep no execution by default.

Changing `src/sefirot/data_session.py` and `cli.py` changes exact build
code_hash (different from the model-only hash). Previously frozen forward
plans require their original build; **do not re-sign or relabel them**.
Therefore this feature is a separate DRAFT PR, not automatically promoted
into main.

### Tests

```bash
python -m unittest discover -s tests -p test_data_session.py -v
python -m unittest discover -s tests
```

New regressions cover prior season restored history, default unchanged,
insufficient max_requests, provider returning the wrong season, and invalid
mode values. No real API connection, betting, model fit or main branch merge.
