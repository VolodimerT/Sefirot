# P0-A / Issue #68: Stake access and PREMATCH boundaries

Base: unified draft #56, `d192d8318e603a383f87f781838d2e7553b2a68d`.
This stage does not enable provider access, monetary admission or deployment.

## Independently observed evidence

- 15 October 2026: an unauthenticated GET of the official documentation
  `https://docs-odds-data.stake.com/` returned HTTP 403 in this environment.
  This is a documentation-access failure, not a rejected authenticated odds call.
  No retries, alternate IPs, cookies, browser impersonation or paid calls were used.
- Supabase metadata read at 14:37:32 UTC found no secret names matching
  `stake|odds` in `vault.secrets`. No secret values were selected. This does not
  establish whether an independent Render environment contains a credential.
- Latest existing worker status is dated 13 October 08:33:21 UTC and says
  `STAKE_API_TOKEN=MISSING_OR_INVALID`. It is historical, not a current token test.
- Current managed execution environment has no configured secret bindings or
  outbound identities. Render tools expose no names-only environment inventory;
  no value-bearing environment endpoint was read to fill that gap.
- Current implementation uses `stake.com/_api/graphql` and the separate
  `STAKE_API_TOKEN` namespace. It remains `STAKE_GRAPHQL_EXPERIMENTAL`.
  There is no verified official Odds Data adapter or provisioned credential
  demonstrated by these observations.

Status: **BLOCKED_BY_STAKE_AUTH_OR_TERMS / NOT_VERIFIED**. Neither official
authorization, terms nor an actual Stake quote is established. Do not interpret
the documentation HTTP 403 as proof that the user's account is blocked.

## Confirmed defects repaired

Owned synthetic counterexamples failed on the base: eight tests produced
17 assertion failures, including subtests. The legacy provider accepted a
different returned fixture ID, mixed fixture IDs across chunks, accepted live
events with unchanged scheduled kickoff, accepted receipts outside the seal/
capture time interval and copied arbitrary receipt fields except `credential`.

- Group discovery and every market chunk now bind to one returned fixture ID.
  Both snapshot entrypoints and the lossless atlas pass the selected event ID.
- Both CLI and standalone snapshot runners use the same PREMATCH flow, requesting
  upcoming events. The seal/cutoff is checked before discovery, group lookup and
  every chunk, then after completion. Snapshot time is recorded after I/O.
- Existing receipts are preserved, including group discovery. New snapshots
  validate provider/host/endpoint/operation/HTTP/hash/flags and
  `seal <= request_start <= response_received <= snapshot < kickoff`.
- Receipt output uses a fixed field allowlist; arbitrary auth/account fields
  are discarded without mutating the supplied receipt. Original archived
  snapshots, seals and decisions are not re-signed or rewritten.
- A changed fixture, cutoff failure or 401/403/404/429/5xx stops retrieval.
  No automatic retry or financial permission is added. The normalizer still
  reports settlement as unverified and does not promote research prices.

These are boundary fixes for an existing experimental adapter. They do not
verify the provider's current GraphQL contract, official API access, quote
freshness at the provider, settlement rules or model profitability.

## Official access route for the owner (Android)

Issue #68 identifies `https://docs-odds-data.stake.com/` as the official Sports
Data API documentation and reports `developers@easygo.io` as its contact.
The host `odds-data.stake.com`, `/sports`, `/fixtures/{fixture}`, `/odds/{fixture}`
and security scheme named `apiKey` are reported there, but this stage could not
retrieve the OpenAPI document. Header placement, market contract and permission
must be verified from the actual specification; do not guess them in code.

Suggested message, prepared locally and **not sent**:

> I would like authorized, read-only access to Stake Sports Data API for personal
> pre-match analytics. Please confirm eligibility, permitted regions and use,
> price/subscription and request limits. Please provide the current OpenAPI
> specification, exact API-key security scheme, provisioning instructions,
> fixture identifiers and pagination, supported markets and settlement rules,
> odds timestamps/status semantics and access to one permitted sample fixture
> with its odds. Can this key be scoped to reads only? Please confirm that a
> website session/account token is not required or interchangeable.

Use Stake's verified support/developer channel to confirm the contact before
sharing any account information. Store a newly authorized key through the
protected Vault/environment setup under its own official-provider name; never
paste it into chat, Git, screenshots or frontend settings. Provisioning,
spending and a real diagnostic request each require the owner's separate scope.

Once the specification and access are supplied: implement the documented
`STAKE_OFFICIAL_ODDS_DATA` adapter under a distinct credential namespace; verify
catalogue and a single sealed fixture's odds separately. The Odds API remains
its own provider and cannot be relabelled as a Stake quote. No fallback is
activated by this document. Until a real timestamped fixture/market/line/period/
rule receipt is independently verified, quote readiness is NOT_VERIFIED and
the operating decision remains **RESEARCH_ONLY / PASS / stake=0**.
