# Calibration data recovery + gated real fitting — 2026-10-08

## Purpose
A runnable, source-backed continuation of the existing SEFIROT probability
calibration, not another artificial tuning pass over the viewed historical TEST.

Two standalone commands, both on the current `feature/calibration-fit-gate-20261008`
branch, derived from PR #17:
- `scripts/calibration_history_triage.py`: determines missing real history
  per team from one or more original `data-session/REPORT.json` files.
- `scripts/calibration_fit_gate.py`: opens the existing `research.sqlite`
  read-only, validates CALIBRATION records against the originally sealed,
  API-backed forward plan, actual prematch capture jobs, exact FT settlement
  source jobs, original WIN/PUSH/LOSS contract and Policy. It reports
  canonical bucket counts and **blocks fit** until sufficient credible data
  exists. With explicit `--fit`, it calls the EXISTING `Service.calibrate`
  to save its original immutable calibrator artifact, but **never**
  activates a model or modifies probability code.

### Discovered bottleneck
`src/sefirot/data_session.py` currently fetches history from just the
**current league+season** for an upcoming match. At the start of a season
that may be insufficient even with a healthy API, and the archived
17 CALIBRATION fixtures had 0 scored due to insufficient history.
The original API-Football account status was reported as
`PROVIDER_ACCOUNT_SUSPENDED` on October 6. The connected Supabase
project `sefirot-core` is online but has no public football-history
tables; its existing Edge gateway is not itself an accessible
independent results dataset. No API source has been silently replaced.

Use authentic earlier-season FT packets **only if available through
authorized access**, preserving the actual receipt time and matching
league/team IDs. Newly fetched results CANNOT be backdated to rescue an
already-started fixture; those missed forecasts remain missed.

### Recovery: show exactly what's missing
```bash
python scripts/calibration_history_triage.py \
  data/session-A/REPORT.json data/session-B/REPORT.json \
  --output data/history-gaps.json
```
If provider is suspended, the output says
`RECOVER_PROVIDER_ACCESS_FIRST`; it does not retry, rotate keys, scrape
around authorization, invent missing team matches or fetch live odds.
Use the ordinary API-Football account dashboard/support for legitimate
recovery.

### Gate and actual fitting
```bash
# No filesystem/network mutation except creation of fresh JSON output.
python scripts/calibration_fit_gate.py \
  --db data/research.sqlite --output data/calibration-fit-check.json

# Only on a *genuine* newly completed, adequately sized CALIBRATION cohort.
# Writes one immutable calibrator through existing Service.calibrate and an
# output JSON; does NOT activate a new model or pass any HOLDOUT:
python scripts/calibration_fit_gate.py --fit \
  --db data/research.sqlite --output data/calibration-fit-result.json
```
Use a new file name on each call. A missing database is rejected, never
created. Research source must be fully protected with real receipt-bound
original forward plan, original prematch capture, exact fixture ID, original
Policy and model, observed FT result, and unchanged raw/base vectors.
Any other CALIBRATION record lacking those proofs BLOCKS the entire fit,
rather than being silently omitted.

**Research preflight floor**: at least 60 distinct settled CALIBRATION
matches, at least 80% complete original fixture coverage, and at least one
exact populated 20-observation WIN-probability bin for **each observed
profile+contract**. The core `min_holdout=60` is *per context*, so this
preflight is **NOT** the Service.validate release condition or sufficient
proof for true HOLDOUT. If a family lacks a populated bucket,
`INSUFFICIENT_BIN` remains; do not fill with invented/nearby labels.
Never mix different base model versions or calibration profiles.

### Independent future evaluation
After a frozen calibrator exists:
1. Reserve entirely new future `HOLDOUT` fixtures BEFORE kickoff with
   that frozen artifact, not old training fixtures.
2. Run real original sports capture and original settlement from verified
   API packets, keeping ALL missed fixtures in the denominator.
3. Evaluate original `forward-scorecard`, then
   `scripts/calibration_quality_audit.py`.
4. Run canonical `Service.validate` against each matching context. A result
   must beat baseline under original Policy; no automatic release.
5. Do not merge these scripts into core or money gates while source status
   and prospective coverage are unknown.

### Technical scope and integrity
The new scripts do NOT modify `src/sefirot`, Policy, model hashes,
baseline coefficients, existing SQLite or deployment (except explicit --fit
creating a calibrator via original Service). They do not run any API request
and are safe offline. Source packet JSON digest is only a local content
checksum and does not independently attest bookmaker/provider authenticity.
Tests use synthetic **mocked** fixtures only; they prove fail-closed
software behavior, not forecast quality or actual 60-match coverage.
