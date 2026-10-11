# SEFIROT: FootyStats trial and multi-provider gate (research only)

Date: 2026-10-11. Base: feature/fixture-query-contract-20261010 (PR #24).
No live sporting API credentials obtained, no subscription changed, no CORE or money-gate edits.

## Provider decision

**FootyStats** offers public \`key=example\` samples for English Premier League 2018/19
season 1625, or other demonstrator season IDs described on the official pages.
The \`league-matches\` endpoint reports fixture identity, regulation goal counts,
FT corners, and other statistics, with \`max_time\` query support; a \`match\`
endpoint has lineups and odds comparison. Its Hobby offer is GBP 29.99/month
for up to 50 chosen leagues and 1,800 calls/hour. Free plan/test key does **not**
prove full historical coverage in user's intended leagues.

**Sportmonks** free plan covers Danish Superliga and Scottish Premiership.
Paid Starter starts at EUR 29/month for five leagues. Do not assume that xG,
historical archives, odds, or predictions are entitled just because there are
public examples: options/add-ons vary and may produce 403. Check subscription.

**football-data.org** free offers 12 competitions at 10 calls/minute and
delayed results. ML Pack Light is EUR 29/month; corners requires separate
stats add-on. Not a substitute for a comprehensive detailed corner dataset.

**API-Football (existing)** documented supplier result 2026-10-06:
PROVIDER_ACCOUNT_SUSPENDED. This trial does not bypass the suspension and does
not claim current provider health. Existing configured Render/CORE remain intact.

Official sources:
- https://footystats.org/api
- https://footystats.org/api/documentations/match-schedule-and-stats
- https://footystats.org/api/documentations/match-details
- https://footystats.org/api/documentations/setup-the-api
- https://www.sportmonks.com/football-api/
- https://www.football-data.org/pricing

## Actual level of verification

Public FootyStats documentation and test endpoint URL are available on the web.
There is no authenticated real-user data retrieval, saved complete HTTP sample,
external first-received timestamp, credential, or full-league audit for this PR.
The tests use **synthetic** rows. No tested claim of real model accuracy or ROI.

## Offline research probe

Fetch a public sample independently in a browser, save complete JSON locally,
keep the collection timestamp from the actual request and protect the file.
The \`example\` key is public for designated demo seasons; do not use a real key
in command-line arguments, GitHub files or logs.

Example test URL (browser only, demo):
https://api.football-data-api.com/league-matches?key=example&season_id=1625

Then, in the project checkout:

\`\`\`sh
python scripts/footystats_probe.py --input /private/footystats-1625.json --season-id 1625 --received-at 2026-10-11T06:00:00+00:00 --output /private/footystats-report.json
python -m unittest discover -s tests -p test_footystats_probe.py
\`\`\`

Replace received-at with the **actual first-observed capture timestamp**; the
above time is a syntax example, not a statement that data was collected then.

- \`success\`, match IDs, competition selector, score/corner validity, basic
  pagination and chronology are checked.
- The adapter never interprets historical kickoff as publication or
  received-at time. It records the actual collection timestamp on all rows.
- Complete result counters require explicit valid two-sided goal/corner values.
  Missing corner values remain null rather than invented 0.
- All bookmaker odds, pre-match potential and trend fields are deliberately
  **excluded** from candidate output until temporally verified.
- Successful parsing is merely \`KEEP_SHADOW\`: model fit=false, holdout=false,
  money=false, not a certified provider statement.
- The full raw JSON is not copied to the resulting report; only up to three
  non-sensitive observation summaries. Preserve original private raw receipts
  securely and separately; local response SHA does not authenticate provider.

## Acceptance gate before real deployment

1. Obtain explicit source subscription/license and check model-training rights,
   data retention, redistribution and detailed competition coverage.
2. Independently verify complete page counts, season/league/team crosswalk
   against API-Football and original sports archive; reconcile cancellations
   and neutral-venue matches. Never equate team names with IDs.
3. Make an opt-in transport client with secret stored in private environment.
   Bound page size, request budget, throttling, JSON size, and test 401/403/429;
   require original server-side receipt with observed_at and source identity.
4. Bind first-known data times to original archive/ledger, make independent
   point-in-time snapshots **before** each future kickoff.
5. Pre-register TRAIN/CALIBRATION/HOLDOUT fixture IDs, league/profile/season,
   exclude all previous viewed TEST, and measure coverage, Brier and log loss
   on identical fixtures. A historical page fetched today cannot be used to
   falsify old time-of-availability.
6. For bookmaker EV/CLV, import separate correctly timestamped exact-market
   quotes; FootyStats match-odds field alone is not an auditable Stake quote.
7. Review cost vs matched-league effective completeness. Do not buy a plan,
   alter deployed services, merge main, or enable wagers automatically.

Current decision: **PROTOTYPE_READY, SOURCE_NOT_CERTIFIED, KEEP_SHADOW**.

## Optional one-request public demo smoke

Run only when internet access is available. This uses the published public `example` key for EPL 2018/19, requests only the first page, and writes a new local summary; it does **not** obtain a subscription or certify live data. No retry or paid call is performed.

```sh
python scripts/footystats_public_demo.py --execute-public-demo-request --output /private/footystats-demo-smoke.json
python -m unittest discover -s tests -p 'test_footystats*py'
```

The actual demo HTTP request has **not** been executed in the current development session because direct external networking is unavailable. Automated CI tests mock the HTTP response and must not be described as real API data collection.
