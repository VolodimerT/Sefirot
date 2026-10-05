# Stake sportsbook research bridge

Status: **experimental / read-only / research-only**.

The bridge exists to inspect Stake sportsbook prices after SEFIROT has already
sealed a sports-only prediction. It must not be used to place bets, bypass
SEFIROT admission, or claim verified execution prices.

## Why it is isolated

Stake's official public API documentation supports authentication with an
`x-access-token` header, but its public stable API does not currently document
the sportsbook event schema used by the web client. The sportsbook reader here
therefore treats the GraphQL shape as unstable and fails closed on any change.

No Stake credential is stored in Git, reports, receipts, error messages, or
line identifiers.

## Credential

Set only as an environment variable or in the existing local `.env`:

```text
STAKE_API_TOKEN=...
```

The token supplied in chat or another transient channel should be rotated
before long-term use.

## Run

A real prematch SEFIROT prediction must already exist in the ledger:

```powershell
py -3 scripts/stake_snapshot.py --db data/sefirot.sqlite PREDICTION_ID --output data/stake-snapshot.json
```

Optional:

```powershell
py -3 scripts/stake_snapshot.py --db data/sefirot.sqlite PREDICTION_ID --sport football --first 50 --output data/stake-snapshot.json
```

The command requires an exact home team, away team and kickoff match. It does
not fuzzy-match aliases or silently swap competitors.

## Output contract

The result deliberately preserves raw Stake market names and outcomes:

```json
{
  "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
  "status": "RESEARCH_ONLY",
  "normalization": "RAW_STAKE_NAMES_ONLY",
  "provider_market_timestamp": null,
  "freshness": "RECEIPT_TIME_ONLY",
  "markets": [],
  "monetary_permission": false,
  "execution_enabled": false
}
```

This is intentional. Until Stake exposes stable market identifiers, settlement
rules and provider-side market timestamps, SEFIROT must not guess that a raw
label corresponds to a regulated 90-minute contract.

## Next integration step

Use real saved snapshots to build an explicit mapping table for the markets we
actually need:

- 1X2 and double chance
- DNB / Asian handicap
- Asian totals
- BTTS
- team totals
- corners
- shots / shots on target when the Stake feed exposes them

Each mapping needs fixtures, exact outcome semantics, settlement rules and
regression tests. Only after that should Stake snapshots be converted to the
same quote contract used by `compare-grid`.

Builder prices remain bookmaker-specific and should be stored as their own
joint quote rather than reconstructed by multiplying single-market prices.
