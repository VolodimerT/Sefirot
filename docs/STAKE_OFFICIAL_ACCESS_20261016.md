# Issue #68: confirmed official contract and remaining access blocker

Status: **BLOCKED_BY_STAKE_ACCESS**. This is an access/contract finding, not a
successful Stake quote test. No authenticated/provider request was made.

On 16 October 2026 at 22:05:24 UTC the ordinary public documentation and its
published OpenAPI returned HTTP 200. The historical documentation 403 is no
longer the current observation. No alternate route, cookie or protection bypass
was used. Source: [official Sports Data OpenAPI](https://docs-odds-data.stake.com/dist.yaml/dist.yaml),
version 1.0.0, 39,012 bytes, SHA256
`1d6030339551c43045aaaf5b67dc7563552548a3594853d43e0664242fb9f45b`.

- Server: `https://odds-data.stake.com`.
- Global security: `apiKey`; scheme type `apiKey`, placement `header`, exact name
  **`X-API-KEY`**. The distinct proposed credential namespace is
  `STAKE_SPORTS_DATA_API_KEY`; no binding was created or read.
- Documented fixture odds operation: **GET `/fixtures/{fixture}`**, operationId
  `GetFixture`, path parameter described as a **fixture slug**, response
  `ResFixture` containing `fixture: FixtureOdds`.
- `/odds/{fixture}` appears in introductory prose but is absent from `paths`.
  Do not implement that guessed operation.
- `FixtureOdds.date` means kickoff in epoch milliseconds. The discovery schema
  `FixtureInformation.updatedAt` describes a fixture update, not a price update.
  The odds response does not provide a documented authoritative quote timestamp,
  ordered home/away fields, stable market/outcome IDs, structured period/line
  conventions or settlement/void rules. Names/specifiers and `voidFactor` do not
  fill those gaps without an authoritative mapping.
- Market status and outcome `active` exist, but do not prove timing, identity or
  settlement. A raw response cannot yet be promoted to a verified CORE quote.
- Provisioning, permitted jurisdictions/use, cost, rate limits, retention and
  redistribution rights are not specified. The specification's software license
  does not establish the owner's right to access or redistribute sports data.

The separately retrieved [account/affiliate public API](https://docs.stake.com/dist.yaml/dist.yaml)
v1.1.0 uses `x-access-token` and contains no sports/fixtures/odds operations.
Its SHA256 is `8e96387988eadc9d71953d5239f6ca25784fc44e939a4e97ac1a7e719b8ae1e9`.
Existing `stake_provider.py` remains **STAKE_GRAPHQL_EXPERIMENTAL**, calling
`stake.com/_api/graphql` with `STAKE_API_TOKEN`. Neither this account token nor
the experimental GraphQL contract is evidence of official Sports Data rights.

Names-only Supabase Vault metadata at 22:06:19 UTC found no name containing
`stake`; no value/decrypted-secret column was selected. Managed environment
bindings are empty. Render has no names-only inventory operation in the current
connector, so current credential presence there is **NOT_VERIFIED**, not proven
absent. A legacy token-presence health response is not an odds access test.

## One Android action

Open email on Android and send the following access request to
**developers@easygo.io**, the contact in the official OpenAPI. This message has
only been prepared; the engineering agent did not send it.

Subject: Authorized read-only Sports Data API access for SEFIROT research

> I request authorized read-only Stake Sports Data API access for personal
> pre-match football research, with no automated bet placement. Please confirm
> eligibility, jurisdictions, permitted use, price and request limits, and the
> protected provisioning process for the documented X-API-KEY. Please provide
> the current versioned fixture/odds contract, exact ID/slug and home/away
> mapping, authoritative quote timestamps, market/outcome IDs, period/line and
> settlement/void rules. Please confirm response retention/internal research
> display permissions and access to one permitted diagnostic fixture. An account
> token will not be treated as this API key. Please provide secure provisioning
> instructions; do not send a key in unprotected email.

Do not attach a token, key or account screenshot. After official access and cost
are confirmed, one genuine diagnostic request still needs the owner's separate
authorization. Only that verified fixture/market/line/period/rules/timestamp
receipt can establish **STAKE_READY**. Until then quote readiness is
**NOT_VERIFIED**, other bookmakers keep their own source identity, and the
operating decision remains **RESEARCH_ONLY / PASS / stake=0**.
