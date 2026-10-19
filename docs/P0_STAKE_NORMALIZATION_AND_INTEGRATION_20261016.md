# P0: Stake normalization and unified candidate, 16 October 2026

Baseline: `b90933e1f0fa769cad31a73257e0cad3f24cf700`, existing draft
[PR #56](https://github.com/VolodimerT/Sefirot/pull/56). This is a research
candidate, not the production deployment. Issues #68/#69 remain open.

## Reproduced and repaired

Independent offline QA found five defects in `stake_mapper.py`:

1. Duplicate specifiers silently selected the last line, including whitespace
   aliases and mixed `&`/`|` separators. Duplicate or malformed specifiers now
   raise a fixed ValueError instead of selecting a price contract.
2. Small totals trusted `total=8.5` even when outcome text said 12.5. Both
   exact complete Over/Under outcomes must agree with the finite specifier.
3. Generic small-market templates ignored half/extra-time groups and period
   specifiers. Only the previously supported offline group/specifier shapes
   remain eligible for advisory mapping. Unknown scope is refused, not guessed
   from an undocumented provider enum. Shots count must also match its name.
4. Malformed outcome containers could cause AttributeError, losing the whole
   atlas. Consumed containers now fail with ValueError; the existing atlas
   error path retains the exact raw market as UNMAPPED_RAW. No broad catch added.
5. Normalized main/small/range rows lost market status and outcome active flags.
   `raw_market_status` and `raw_outcome_active` now preserve those observations
   (missing stays null). `availability=NOT_VERIFIED` explicitly avoids claiming
   tradability from an unconfirmed status enum, including active-looking values.

Ambiguous input can refuse a direct normalization report; the existing atlas
isolates markets and preserves every original raw item. Original snapshots and
hashes are never rewritten. Derived advisory report hashes change with the new
fields; no historical seal, fit or approval is migrated automatically. Every
successful report still has execution_enabled=false and monetary_permission=false.

New regression: `tests/test_stake_normalization_integrity.py`, nine methods,
including lossless atlas fallback. Baseline: 50 failed assertions and 18 errors
across subtests. Initial development helper shadowed the existing `scope` loop
variable; renamed before publication. Existing tests/assertions are unchanged.
Run full release in an isolated tracked-tree copy, then exact-head Actions;
current SHA/results are recorded in the external stage report, not guessed here.

## #68: BLOCKED_BY_STAKE_ACCESS

An ordinary unauthenticated GET of `https://docs-odds-data.stake.com/` returned
403 at 2026-10-16 19:00:17 UTC. No retry, account token, cookies or workaround.
The exact OpenAPI authentication header, response schema, market coverage,
limits and permission terms remain unconfirmed. An official adapter cannot be
honestly implemented against an unavailable specification. This repair applies
to the existing **STAKE_GRAPHQL_EXPERIMENTAL** offline adapter only; it does not
claim official API support or genuine verified Stake quotes.

Account `STAKE_API_TOKEN` (GraphQL x-access-token) and an official Sports Data
API key are separate identities. No substitution is allowed. Supabase Vault
names-only aggregate at 19:00:03 UTC found zero matching account-token names and
zero official-key candidate names. That does not inventory Render environment
values or prove that credentials exist nowhere. Values were not read.
The previously disclosed account token was not used; revocation is unconfirmed.

Owner access steps from Android:

1. Revoke the disclosed account token in Stake account settings. Do not paste
   a replacement token or screenshot into chat, GitHub, or the frontend.
2. Ask the official Sports Data contact reported in Issue #68,
   `developers@easygo.io`, for authorized prematch read-only access, accessible
   versioned OpenAPI, exact security scheme, permitted regions/use/storage,
   fixture and market identifiers, settlement/period/line definitions, timestamps,
   status enums, per-request/burst/daily limits and any cost. No message was sent.
3. Supply an approved official key through a protected secret channel only,
   separate from account credentials, after confirming the official contract.
4. Separately authorize one bounded genuine-fixture quotation test and its exact
   request budget. It must compare fixture ID, ordered teams, kickoff, observed
   timestamp, period, line, decimal odds and active market/outcome state; archive
   the original permitted response and hash. Missing proof means PASS.

Existing no-network fixtures/regressions are ready for the experimental path;
they are not a recorded authorized official API sample. No real quote test ran.
The Odds API remains its own provider, never a source of purported Stake quotes.

## #69: current budget and provenance

Supabase read at 19:00:05 UTC: enabled=false, reason=QUOTA_STOP, remaining_day=5,
reserve_day=5, no in-flight request, valid_until=2026-10-15 09:16:57 UTC (expired).
At 19:00:29 UTC the queue had DONE104/ERROR23 and PENDING0/RUNNING0. These are
historical queue counts, not evidence of 104 successful provider requests.
The new candidate already contains typed budget-denial handling, bounded queue
completion retry, attempt fencing and canonical original-packet verification.
Do not repeat those repairs or reset the protected quota.

Independent read-only review rechecked all five stored queries from the prior
authorized session: status, schedules 18+18, history 10+10. There are 56 unique
fixture IDs, but all five lack the original complete source_packet. Current
verify_evidence correctly returns ORIGINAL_PACKET_UNAVAILABLE. A digest of the
projection does not equal the original full payload hash. Never reconstruct or
re-sign these records as original provider responses. No fixtures/statistics
call was made; small-market statistics coverage is NOT_VERIFIED.

New collection requires separate approval: deploy the matched fenced candidate
and archive path first; then approve a fresh finite time/request window. Prepare
fixture/statistics calls only for exact known IDs, stop at the shared gate,
archive the full allowed packet and receipt before normalization, and audit
source -> archive -> normalization. A process failure without an archived packet
remains unknown, not permission to refetch. Existing rollout and collection
procedures are reused, not replaced.

## Unified installation boundaries

| Component | Current connected observation | Candidate action |
|---|---|---|
| CORE | PR #56 on b90933e1; main d09a8af2 remains 2.3 | Existing unified 2.4.2 candidate, no second integration branch |
| Render worker | Live 3461ef75, not this candidate | Requires separately approved matched rollout |
| Render Stake bridge | Live ef0cc286; health-only prototype | Does not establish quote access |
| Supabase RPC | Legacy claim/complete; new complete_probe absent | Reviewed incremental fenced migration, initially parked |
| Python | Render 3.14.3 | Candidate has exact 3.14.3 Linux release/native PostgreSQL CI, plus Ubuntu/Windows 3.11/3.13 |
| Ledger/mirror | Original SQLite integrity preserved; mirror absence was explained by canonical snapshot | No synthetic repopulation or mutation of original forecasts |
| Relay/worker | Matching fenced protocol exists in GitHub | Must be installed together; never enable old unfenced processing |
| Android panel | Existing authenticated read-only prototype and offline browser smoke | Not publicly deployed; physical Android/hosted session unverified |

Use `docs/P0_B_ROLLOUT_AND_ROLLBACK_20261015.md` and its reviewed migration and
park script. Do not apply the fresh-install SQL file over the populated schema.
Verify exact hashes/ACL/RLS/default grants and archive backup, keep claim paused,
install the matching relay/worker, test non-provider fenced completion, then ask
for separate activation. Rollback parks processing while preserving receipts,
attempts and data; it does not restore unfenced completion or reset budget.
No hosted operation, deploy or main merge was performed in this stage.

Ancestry independently proves existing PRs #53-55 and #62-67 are already in
#56. Their changes should not be copied or merged again. Other older branches
without ancestry proof are not automatically called duplicates; patch-level
equivalence requires a separate comparison before any disposition.

## Real quality, not engineering test counts

Immutable original SQLite: integrity_check=ok, SHA-256
`3ae7ad31957eebba32ef9d337a07cc335f79c95144112fb2502df42a48581ba2`.
Counts: 31 predictions, 27 decisions, 27 matches, 62 audit rows, two original
odds snapshots; zero results, bets, calibrators, validation runs and split
assignments. These storage facts do not certify prediction/source validity.

Brier Score, Log Loss, ECE, genuine quote coverage, independent HOLDOUT and model
advantage remain NOT_VERIFIED/null. Existing prospective protocol remains
DRAFT_NOT_REGISTERED. Original forecasts are not reconstructed. Small-market
models remain SHADOW. No fit, data split registration, PASS-to-BET promotion or
money execution occurred. Owner actions remain access/specification, a matched
rollout approval, then a separately approved bounded real-data collection window.
