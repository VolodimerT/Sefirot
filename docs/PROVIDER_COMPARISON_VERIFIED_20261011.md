# SEFIROT provider verification — 2026-10-11

Status: **RESEARCH_ONLY / NO_PROVIDER_PROMOTION**. No paid subscription, private API credential, original CORE, canonical ledger, production server or `main` changed. This comparison is not a training-data admission or a verified real betting forecast.

## Direct public trial: FootyStats

Public official documentation: https://footystats.org/api/documentations/match-schedule-and-stats and https://footystats.org/api/documentations/setup-the-api

Read publicly documented demo `GET https://api.football-data-api.com/league-matches?key=example&season_id=1625` via a public web extraction tool on 2026-10-11. The returned page was parsed from JSON (the tool escaped underscores for text presentation; escaped characters restored for parsing). **These are retrospective 2018/19 observations downloaded now, NOT historical contemporaneous forecast receipts.**

| Observed fact | Result |
|---|---|
| HTTP/application response success | Provider JSON `success=true`; transport's original HTTP status not independently retained |
| `pager.current_page` / `pager.max_page` | 1 / 1 |
| `pager.total_results` | 380 |
| Actual rows and unique fixture IDs | 380 / 380 |
| Competition IDs | only 1625 |
| Season label / statuses | 2018/19; 380 complete |
| Distinct team IDs | 20 |
| Earliest/latest scheduled kickoff | 2018-08-10 / 2019-05-12 UTC |
| Numeric regulation goals, both sides | 380 / 380 |
| Numeric FT corners, both sides | 380 / 380 |
| Numeric FT xG values, both sides | 380 / 380; retrospective computed values, unavailable-at-kickoff unproven |
| Numeric shots and possession, both sides | 380 / 380 |
| Numeric first/second-half corner values, both sides | 380 / 380 |
| Numeric 1X2 odds fields | 380 / 380, but sportsbook and original quote timestamp not authenticated |
| Positive `odds_corners_over_85` | 173 / 380; 207 zero placeholders |
| Positive `odds_corners_over_105` | 342 / 380; 38 zero placeholders |
| Score total and corner total inconsistencies | 0 / 380 |
| External provider receipt / original publication times | NOT VERIFIED |
| Independent crosswalk with SEFIROT API-Football match IDs | NOT DONE |
| Real new prospective HOLDOUT | 0 |

The 380 retrospective results cannot become a new independent HOLDOUT, and downloaded `pre_match_*` fields cannot be trusted as authentically first-known before kickoff. Zero-priced corner markets should be treated as MISSING, not free odds. Verified raw data license permits models but prohibits raw redistribution; do not commit the downloaded data: https://footystats.org/api/documentations/terms-of-use-and-legal

Provider plan: Hobby GBP 29.99/month, 50 selected leagues, 1,800 calls/hour per https://footystats.org/api . The public example key is limited to designated demo EPL 2018/19. Specific selected-league completeness and current-season access still untested.

## Five-provider check: different verification levels

| Provider | Verified public terms / accessible sample | Authentication limitation | SEFIROT recommendation |
|---|---|---|---|
| **FootyStats** | One complete public EPL 2018/19 season verified with 380 rows, goals/corners/xG/shots | Private leagues/current season need own API key + entitlement | Strong first source to TEST; do not pay yet |
| **Sportmonks** | Official Free covers Denmark Superliga/Scotland Premiership; Starter EUR 29 monthly / 5 leagues. Selected advanced xG EUR 29 monthly, odds/predictions from EUR 15 monthly, history >3 seasons priced separately | Requires own free personal token; no authenticated call tested | Secondary test for lineups/events/deeper detail once token available |
| **APIfootball** (`apifootball.com`, not API-Football) | Free 180 calls/hour/endpoint, England Championship + France Ligue 2, documented results, stats and odds; European USD 21/month 60+ leagues | Free signup personal `APIkey` required; no authenticated call tested | Excellent free alternative for prospective capture if selected leagues match |
| **football-data.org** | Public competitions list accessible; official Free: 12 competitions / 10 requests per minute / delayed scores. ML Pack Light EUR 29/mo / 10 seasons; Stats add-on EUR 15/mo for corners etc, added to regular plan | Registered token needed for match fixtures in free plan; public catalog is not authorized season dataset | Inexpensive goal-model historical benchmark, limited corners unless add-on |
| **The Odds API** (official `the-odds-api.com`) | Free 500 credits/month all sports / most sportsbooks; USD 30/mo for 20k credits and historical data | Personal key required for quotes. Published bookmaker catalog does not list **Stake** | Supplement market consensus, not a replacement for Stake exact-market receipts |
| **Existing API-Football (API-Sports)** | Free 100 requests/day; Pro USD 19/month 7500 requests/day | Last documented real provider status 2026-10-06 `PROVIDER_ACCOUNT_SUSPENDED`; **not re-probed** in this task | Preserve current source and safe recovery path; don't bypass suspension |

Official sources:
- FootyStats: https://footystats.org/api ; https://footystats.org/api/documentations/terms-of-use-and-legal
- Sportmonks pricing: https://www.sportmonks.com/football-api/plans-pricing/ ; free: https://www.sportmonks.com/football-api/free-plan/
- APIfootball: https://www.apifootball.com/ ; docs: https://apifootball.com/documentation/
- football-data.org: https://www.football-data.org/pricing ; docs https://www.football-data.org/documentation/api
- Official The Odds API: https://the-odds-api.com/ ; sportsbook list: https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
- Official **impersonator warning**: https://the-odds-api.com/impersonation-warning.html . Never confuse with `theoddsapi.com` (no hyphens), which the official provider says is not affiliated.
- API-Football pricing: https://www.api-football.com/pricing

Sportmonks landing page describes full professional data included in each plan, while its detailed current pricing table separately lists optional odds, xG and historical-data bundles. **Price all necessary add-ons based on written entitlement**, not a headline. Paid trial may require card and automatically charge unless canceled.

## Technical verification

Draft PR #27: `feature/footystats-provider-probe-20261011`, base `feature/fixture-query-contract-20261010` (#24). Its public-demo runner has a single opt-in request; automated tests **mock** transport, not external provider behavior. Final previous head `db51ad882032d4d30381af8909b7c6d10c60cd5e` passed 817 tests on each of four Windows/Ubuntu Python 3.11/3.13 CI jobs, see https://github.com/VolodimerT/Sefirot/actions/runs/38113466823 . After this documentation commit, inspect fresh CI before considering branch tested.

Web extraction can confirm content but does **not** substitute for a trusted immutable first-observed external transport receipt. No credentials were requested or changed. No provider subscription was created, paid or used.

## Next action / stop gate

1. Don't pay until at least 5 selected target leagues show >=95% goal and corner field completeness (an engineering target, not a provider guarantee), valid team/fixture-ID mapping and season coverage; track status `UNKNOWN` until tested.
2. Obtain free APIfootball account and Sportmonks free token **with user's authorization** (not done in this task), then use bounded one-call smoke for each using user-approved credentials stored privately. Official The Odds API similarly requires free user key.
3. Register new prematch fixture list and collect future snapshots, original quote receipts and post-match results for independent evaluation. Imported old goals/corners may be descriptive historical **labels** but cannot be treated as old snapshots of prematch features.
4. Validate license/retention, revisions, timezone and provider rates. Keep `training_allowed=false` until explicit external provenance/identity gate, and all candidate models in `KEEP_SHADOW`.
5. Never automatically merge main, deploy, grant monetary permission or suggest a certified betting edge from this demo.

Current decision: **FootyStats data shape verified for one historical league season; four other providers checked against official product docs and public catalog only.**
