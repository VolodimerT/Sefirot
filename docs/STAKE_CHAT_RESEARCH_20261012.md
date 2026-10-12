# SEFIROT Stake Research — Chat Queue Transport (2026-10-12)

Status: **deployed research route with authentication and provider availability checks; NOT betting execution.**

## Implementation
- Source: `scripts/chat_stake.py`, called through `scripts/chat_gateway.py` and `scripts/chat_queue.py`.
- Transport: existing restricted `sefirot.chat_bridge_jobs` (Supabase) → authenticated existing Render worker → original Python SEFIROT CORE 2.4.2 → immutable Supabase research response.
- New job kind: `stake_snapshot` with request `{"prediction_id":"<original sealed prediction id>"}`.
- Strict gate: valid, real, previously saved, price-blind forecast; verified immutable SQLite journal; kickoff in future. Reject before any request to Stake if invalid.
- Exact home/away/kickoff match against Stake event catalogue; no fuzzy names or team swaps. Uses existing experimental `SportTournamentFixtureList` → `FixtureIndexGroups` → `FixtureGroupMarkets` adapter.
- Safe normalized output: 1X2/DC/DNB/totals/BTTS/handicap and supported cards/corners/shots research markets, max 120 main + 120 small quote rows per response; raw counts and hashes to detect truncation. Receipts have `RECEIPT_TIME_ONLY`, bookmaker settlement rules UNVERIFIED, `monetary_permission=false`, `execution_enabled=false`. Never create bookmaker wagers.
- No new secrets in code, database, response or docs. The provider token stays only in `STAKE_API_TOKEN` runtime env and is not revealed. `status` reports `stake_credential_status`: `CONFIGURED` vs `MISSING_OR_INVALID` without returning the value.

## User interaction

1. Submit original verified sports-only `capture` and wait for `DONE`; use returned prediction ID. If CORE returns PASS after `decide`, do not bypass.
2. Submit one `stake_snapshot` per pre-kickoff fixture. Consult the verified result only after `DONE`. `ERROR` is a legitimate fail-closed result (missing token, forbidden access, mismatched names or time).
3. Compare the provider's quoted *identical market* with Parik24; do not multiply same-match Builder singles to fabricate bookmaker joint odds.
4. Record quote received time and source. Separate screenshots from actual Stake API responses.

## Operational blockers

- A working Render/Supabase job bridge alone is **not** proof Stake has a valid token or HTTP access; check credential status, then a real snapshot receipt.
- Historic code was smoke-tested on 2026-10-05 but Stake returned HTTP 403 later; do not present that old smoke result as a current successful provider call.
- Existing immutable market registry can reject capture of overlapping contract keys; do not erase records or retroactively change sealed predictions. An isolated, truly price-blind research market pool may be used to get a seal for research, not to claim monetary edge.
- Token provisioning/rotation must be done by the authorized account owner; do not invent, publish or bypass credentials.
- The provider is experimental and `research-only`; independent calibration/holdout remains unavailable.

## QA

Tests added: `tests/test_chat_stake.py` (invalid ID, synthetic seal, expired gate before network, sanitized successful snapshot). Build and engine startup smoke on Render succeeded, but do not claim the full Python suite passed unless a matching CI result exists.

This addition does **not** alter seven CORE model modules, BASELINE_V1, STRICT Policy, previous journal/receipts or automatic monetary authorization.
## Verified operational checkpoint — 2026-10-12 13:18 UTC

- Existing Render service deployed the queue integration and then the credential-status diagnostic, deployment LIVE. Canonical startup smoke/replay and durable journal integrity passed.
- Two actual, non-synthetic prematch research predictions were sealed for Coventry–Newcastle and Levante–Sevilla through the existing private ledger, without changing existing entries. A pre-existing immutable market registry conflict was avoided with a fixed isolated research market contract; this is not model approval.
- Private Supabase status confirmed `stake_credential_status=MISSING_OR_INVALID`; the connected Supabase Vault metadata listed **no Stake-named secret**.
- Research snapshot jobs returned ERROR, not any market quotes. **No live Stake odds were recovered**, and no wager was executed.
- **Remaining owner action:** configure a valid authorized `STAKE_API_TOKEN` in Render's protected Environment setting for the existing SEFIROT service, then deploy/restart and repeat the sealed, pre-kickoff `stake_snapshot`. Never paste the token into the GitHub repository or public chat.
- Distinguish code/data pipeline readiness from real provider authentication. No real positive EV or bookmaker approval can be claimed based on code deployment alone.
