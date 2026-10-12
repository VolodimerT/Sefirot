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