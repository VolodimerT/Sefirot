# SEFIROT December Quest V6.2 — Autonomous Predictor / 24 November 2026

## Production
- URL: https://sefirot-december-quest-2026.vercel.app/#autopredict
- Vercel production deployment: `dpl_97FWj4zCKVPQWJ9xjh7wZkKPpzCC`, READY.
- Isolated branch: `feature/december-quest-web-v3-20261123`. No merge to the SEFIROT mainline.

## Actual autonomous backend (not a UI-only simulation)
- Isolated Supabase Edge Function `dq-autonomous-predictor-v2` is active. POST requires the private token checked by the DB, while GET provides read-only health. Public publishable key cannot trigger a privileged run.
- Existing pg_cron job `dq-autonomous-dec2026-19kyiv` is enabled with `0 17 * * *` (19:00 Kyiv winter time). Cron reads its token from Supabase Vault and calls the function via pg_net.
- Inputs: 11 successful public football-data.co.uk CSV sources for current and past seasons; five supported domestic leagues (EPL, LaLiga, Serie A, Bundesliga and Ligue 1).
- Model: `DQ-POISSON-0.2`, historical full-time goals, weighted home/away strengths. These are **not xG**.
- Outputs: 1X2, totals, BTTS and individual totals. Forecast rows and append-only prospective snapshot rows reside in dedicated public read-only-to-clients tables; no bookmaker execution.
- Settlement function is present but has no completed prospective observations yet.

## Live evidence
- Manual authenticated *server-to-server* test of the existing worker using pg_net request ID 4 returned HTTP 200 and `run_status: OK`, `wagers_executed: 0`, no source errors.
- Latest run: 2026-11-24 15:01 UTC (17:01 Kyiv), 114 fixtures scanned, 60 MODEL_ONLY, 54 without model coverage, 11/11 sources fetched.
- Total 180 model snapshots, 0 prospective settlements, all 114 current verdicts `пропуск`.
- Independent SQL readback shows 0 malformed 1X2 probability totals (threshold 2 p.p.), 0 invalid pre-kickoff times, 0 same-day-or-future training data, and 0 non-PASS recommendations.
- Five league-level walk-forward results are available. EPL now `NO_EDGE`, 71 tests, model Brier 0.6380 versus baseline 0.6473 (small absolute gain, below internal threshold). The others are `PROMISING` but no live-market value has been demonstrated.

## V6.2 changes
- Added stricter `modelValid` gate to autonomous dashboard: reject bad probability totals, missing data, insufficient sample sizes, non-prospective timestamps, or invalid model statuses.
- Display fair theoretical odds `1/P` for 1X2 **separately from bookmaker quotes**. Never treat fair odds as an executable sportsbook offer.
- Corrected outdated V0.1 disclaimer to the V0.2 internal walk-forward context, explicitly `FT goals != xG` and all decisions PASS until independent odds, lineups and evidence gates.
- Added regression test `tests/v62_auto_quality.test.cjs` (11 assertions), checked 9 matrix scenarios through in-memory execution, passed JS parsing, PWA cache revision and mobile typography.
- Production browser smoke test: `#autopredict` renders 114/60/54 coverage, theoretical fair odds, visible strict PASS and no real bet actions.
- Original private cloud save table remains untouched: one record, last updated 2026-11-23 22:06 Kyiv.
- New **read-only failure monitor** `SEFIROT V6 — контроль автопрогнозов` runs at 19:30 Kyiv daily through 2026-12-31, sending notifications only if runner fails, forecasts go stale or integrity/quality changes materially.

## Remaining constraints and acceptance gates
1. **Daily pg_cron fire has not yet been observed after this QA**. Manual pg_net request succeeded; next natural scheduled run is 19:00 Kyiv.
2. No verified pre-match bookmaker price snapshots with original provider timestamp; no calculable trustworthy market EV or value.
3. No confirmed lineups, injuries or tactical match-up data in current fully autonomous pipeline.
4. No prospective FT outcomes settled; historical walk-forward is *not* proof of profitability. A comparative evaluation with actual prices, calibration and class gates remains necessary.
5. 54 of 114 fixtures are outside the five-league public result dataset; no model probabilities are fabricated.
6. PWA offline installation on user's physical Android is not yet independently acceptance-tested.
7. No automatic wagering/live betting/martingale, no paid API-Football calls, no changes to the canonical Sefirot production engine.

**Acceptance:** autonomous SHADOW probability forecaster — OPERATING; autonomous betting selector — NOT ACCEPTED; no proven value => PASS.
