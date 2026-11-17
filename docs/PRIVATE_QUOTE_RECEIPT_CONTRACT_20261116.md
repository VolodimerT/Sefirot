# Private bookmaker receipt boundary (research contract)

`compare_grid` accepts a local adapter receipt only to detect accidental
changes to quotes. A client can recalculate this hash. The comparison now
rejects client-supplied trust claims and reports
`quote_origin_status=NOT_ATTESTED_BY_PRIVATE_SERVER`. It never turns a local
hash into validated value or BET admission.

No server-side quote receipt store currently exists in the checked Supabase
`sefirot` schema (only `odds_snapshots` and `closing_odds`). A future trusted
receipt requires a separate, reviewed migration and server ingestion path:

1. The private server, not Android or a browser, requests the bookmaker feed
   with provider-authorized credentials and archives original response bytes
   before parsing. Record immutable server-issued UUID, tenant/owner ID,
   provider, provider event ID, exact fixture identity, bookmaker, market,
   line, period, settlement-rule version, observed/received UTC timestamps,
   raw response SHA-256 and normalized quote SHA-256. Store source packet and
   receipt in private storage with append-only audit and retention rules.
2. Server-side normalization checks source fixture/teams/kickoff, market
   activity, line, period, odds and observed time. A missing, stale or
   ambiguous field produces `NOT_VERIFIED`; no price is invented.
3. The future authenticated read route accepts only the server receipt ID,
   resolves it from private storage under the caller's owner scope, then
   recomputes both hashes from stored bytes. It never accepts a caller's
   `trusted=true`, caller-provided source packet, or self-issued receipt ID as
   evidence. Separate ingestion and read roles; deny public and cross-tenant
   access. Do not expose service-role credentials to mobile clients.
4. Bind a displayed quote to the sealed prediction and market-grid hash.
   Provider authenticity also requires the actual authorized server request
   and provider documentation; a database row by itself proves only custody.

The server trust route, its migration, RLS/authorization tests and provider
access are **not implemented or deployed** in this PR. The read-only research
projection has no public HTTP endpoint. Until independent review of those
pieces, `quote_origin_status` remains `NOT_ATTESTED_BY_PRIVATE_SERVER`, and
Sport Quality / Bet Value stay separate with `PASS / stake=0`.
