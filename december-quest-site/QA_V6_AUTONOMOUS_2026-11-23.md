# SEFIROT December Quest V6.1 — Autonomous SHADOW Predictor
Date: 2026-11-23 (Kyiv)
Production: https://sefirot-december-quest-2026.vercel.app/#autopredict
Backend: Supabase project kxqpwgwihtjmqlcxgfxp, **isolated December Quest tables only**
Repository branch: feature/december-quest-web-v3-20261123

## Accepted production capabilities
- Football-Data.co.uk public CSV sources: 2026/27 + 2025/26 E0, SP1, I1, D1, F1 (10 files), plus public weekly fixture odds CSV (one file).
- Server-side deterministic score-based, shrinkage-adjusted Poisson model DQ-POISSON-0.2, strictly training on games before model cutoff and fixture kickoff.
- 114 December matches: 60 with computed P, 54 automatically PASS due to competitions outside the five supported leagues.
- Automatic model P for 1X2, double chance, totals, BTTS and team goals. No invented sportsbook odds. Any 1X2 quote from fixture CSV is labelled *conditional*, because original bookmaker publication time is unavailable.
- Model verdict hardcoded `пропуск`, risk D, unless a separate independent future approval mechanism is built. Real betting is disabled.
- Server-side append-only daily-versioned forecast snapshots, 60 v0.1 and 60 v0.2 (120 after two manual runs), independent from user-auth research seal table.
- Walk-forward backtest on strictly older training data with 1X2 multi-class Brier and Log Loss against prior-league-frequency baseline; 5 validation rows.
- Automated secondary-source postmatch settlement logic implemented; 0 settled before Dec. Settlement uses earliest server snapshot before kickoff, official confirmation remains separate.
- Native Supabase pg_cron + pg_net daily 17:00 UTC = 19:00 Kyiv in winter, task id=1 name `dq-autonomous-dec2026-19kyiv`, calls protected `dq-autonomous-predictor-v2` with Vault-protected dedicated token. The job HTTP invocation is time-bounded to end before 2027-01-01 00:00 Kyiv; afterwards it is inert (no network call).
- Authenticated server token never in the web client, service-role key only in Edge runtime. Unauthenticated POST 401; anon public table read-only; no writes into canonical SEFIROT or active Shadow.
- Android accessible `Автопрогнозы` tab, P values, markets, predicted expected goal rates (not measured xG), source age, evidence, and no-value PASS. Work through Market Radar for manual audit.

## Actual runs
- First manual Edge v0.1: success after fixing snapshot trigger, 11/11 CSV sources; 60 modeled, 54 unsupported; 60 immutable model snapshots.
- Second manual Edge v0.2: HTTP 200, status OK; 11/11 CSV files; 114 inspected; 60 modeled; 54 unsupported; 60 additional versioned snapshots. Settlements added 0 (future season).
- Five walk-forward tests on 2026/27 past games, average multi-class Brier versus prior-result league baseline:
  - Bundesliga n=66: 0.5896 versus 0.6313
  - EPL n=71: 0.6361 versus 0.6472
  - La Liga n=76: 0.5608 versus 0.6543
  - Ligue 1 n=72: 0.6157 versus 0.6361
  - Serie A n=74: 0.5402 versus 0.6388
- P1/H/P2 model example Coventry–Ipswich (Dec 1): 50.383% / 20.318% / 29.299%, clearly labelled forecast-only.
- Production Vercel deployment: dpl_H3EUBvBXt1TFRe6r9CEXgwM7KFjX, V6.1 production deployment, READY. All checked forecast JS/CSS/HTML served HTTP 200.
- Independent browser QA on staging V6 and V6.1: real results rendered from Supabase, filters per day/league, supported/unsupported matches, details (totals/BTTS), calibration 5 rows, no JS errors, no sportsbook actions. Direct live production read confirmed.
- Unauthenticated POST to v2: HTTP 401 {"ok":false,"error":"UNAUTHORIZED"}; no CSV fetch.
- Database audit: 114 latest forecasts; 60 version 0.2 model probabilities; no non-PASS verdicts; no bookmaker odds or verified-value entries; 5 backtest rows; 0 settlements; 1 user cloud-save row, not rewritten by job; cron active; no anon writes.

## What remains NOT ACCEPTED
- Daily pg_cron is configured and manual identical invocation worked, but first *scheduled* invocation has not occurred.
- Physical Android installation and true offline browser reload not yet accepted.
- Current weekly fixture CSV has no verified December quotes at creation; bookmaker quote timestamps cannot be established from its contents. Without source-verifiable odds, tactical fit, lineup checks, and independent calibration, **no bet is playable; every verdict PASS**.
- Five-league coverage excludes UEFA club competitions and Coppa Italia (54 of 114 matches). Provider gateway protected; it has not been opened, reconfigured, or had paid API budget consumed.
- Brier against historical league prior is promising but far too small to prove profitable betting; live prospective performance = N=0 before December.
- Forecast model presently uses completed goal scores, not verified external xG, player data or referee data.
- Secondary results provider settlement is not equivalent to official fixture-result verification.
- Positive conditional EV, if a third-party fixture CSV quote appears, is *not* a permitted betting suggestion.

## Manual operator checklist
1. Open the production link and select `Автопрогнозы`.
2. Confirm 60 probabilistic forecasts, 54 unsupported and the latest successful run timestamp.
3. Refresh after 19:00 Kyiv on the next scheduled date, check cron.job_run_details and auto_runs row. If data sources fail, retain PASS.
4. For a desired match, open Market Radar/AI Scout, independently verify odds/source timestamp, lineup, tactical fit and expected goals. Do not use fabricated P and do not place real stakes.
5. When December games finish, compare automatically settled scorecards to original server snapshots and official results before interpreting Brier.
6. At season end, stop/unschedule cron if desired; bounded network calls already prevent new scans after Dec 31.

**VERDICT**: autonomous data collection, forecasting, snapshots, and 19:00 schedule implemented and running; autonomous profitable bet recommendations NOT ACCEPTED, PASS until independent value gate can be satisfied.
