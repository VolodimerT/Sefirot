# API-Football Enrichment V1 — SEFIROT source expansion (2026-10-12)

## Why
The authenticated sports gateway previously exposed only `status`, `leagues`, `teams`, `fixtures`, `fixtures/lineups`, `fixtures/statistics`, `injuries`. The official [API-Football guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide) describes additional football contexts, league-season coverage flags, a non-array `teams/statistics` response, fixture events/players and pagination. Supporting a query does **not** certify the plan permits it, that data is complete, or that the model has predictive calibration.

This separate stacked draft on PR #38 expands the existing sports-only provider, HTTP gateway client, and server allowlist to:
- `standings` — league/season (rank, home-away tables);
- `teams/statistics` — league/season/team; accepts the legitimate **object** response; optional date cutoff (current observed snapshot, not retrospective attestation);
- `fixtures/headtohead` — pair of different numeric team IDs, bounded `last`;
- `fixtures/events`, `fixtures/players` — completed-match data only for the V1 planner;
- `coachs`, `players/squads` and four top-player tables — research metadata, not certified future lineups.

Existing lineups/injuries/fixtures/statistics remain supported. Every newly exposed endpoint enforces required selectors and rejects foreign paths, invalid IDs, unknown parameters, data shape mismatches, HTTP provider errors and incomplete pagination. No odds, provider predictions, raw live polling, transfers or unbounded player pagination is enabled. This **is not the full commercial API catalogue**.

## Quota-safe and coverage-aware plan
`scripts/football_enrichment_plan.py` takes three already saved provider `{data,receipt}` packets: one matching fixture packet, the matching `/leagues` season+coverage packet and an authentic `/status` packet, plus exact fixture ID. It validates source payload hashes, timestamps, season, fixture uniqueness and subscription. Missing coverage flags stay false, not invented.

**Plan only**, no HTTP/network: at most 8 permitted calls per fixture (default 6), at least 5 daily units held in reserve, minimum with observed minute quota. If quota is exhausted it returns `NO_ADMISSIBLE_REQUESTS`, not guessed figures. All prioritized endpoints are frozen BEFORE fetching or viewing odds. The use of the saved `/status` packet does not provide cross-worker atomic quota reservation; concurrent collectors must have a single centralized budget before the plan can be executed automatically. Plan outputs have `execution_enabled=false`, `monetary_permission=false`.

PREMATCH: standings, two team season snapshots, same-league last-five H2H, fixture injuries, coaches, and lineups only within 65 minutes of kickoff when league coverage says lineups should exist. FT: fixture events, team counts, player counts. LIVE, ET, penalties, postponed, stale identity and partial pages do not join prematch predictions or the training corpus. History derived from current-day observations **cannot** be backdated to older kickoff dates.

Usage, no network:
```bash
python scripts/football_enrichment_plan.py \
  --fixture-packet private/fixture.json \
  --league-packet private/leagues.json \
  --status-packet private/status.json \
  --fixture-id 123456 \
  --max-calls 6 --reserve 5 \
  --output private/fixture-enrichment-plan.json
```
For a plan's approved entry, the existing single-call `python sefirot.py football-fetch --endpoint standings --param league=39 --param season=2026 --output private/standings.json` retrieves one packet. Do not run repeatedly without fresh quota receipts and centralized budget. There is no batch mode or automatic network executor in this draft.

## Integration and evaluation gates
- New source observations are **research-only** and do not alter or silently enhance `BASELINE_V1` or archived signed prematch CORE predictions.
- A provider response is not an independent source signature; publication time may precede collection but is not independently proved.
- To integrate team/player injury data into the canonical scenario/evidence model requires a separate typed adapter with source freshness/correction chronology; historical season summaries must not leak later outcomes into old fixtures.
- Predeclare market/sample coverage: complete league TRAIN, chronological CALIBRATION, unseen HOLDOUT. Verify Brier/logloss and bookmaker-specific EV and CLV before any promotion; odds come from an independent bookmaker feed.
- Existing gateway v12 in Supabase contains privately deployed runner authentication hashes **not present in Git** (repo `DEPLOYED_AUTH=[]`). Never deploy the Git file literally to Supabase: it would revoke authorized tokens. Any separately authorized production upgrade must surgically preserve the currently deployed hashes, vault RPC, and rate controls; run live `/status` and one permitted sports query and verify receipts. The draft itself does **not** deploy.
- `model_code_hash` / Policy unchanged; source `code_hash` will change when these files are merged/activated. Do not try to run old signed predictions under a new build.

## Offline validation
New Python unit tests in `tests/test_football_enrichment_v1.py`; new offline Node tests in `scripts/test_sports_gateway.mjs`, guarded by `tests/test_server_gateway.py`. Full 4-platform Python/Node CI and replay/integrity must be verified on exact PR head. CI is simulated, no live API requests; no claim of verified plan quota or improved forecasting accuracy.
