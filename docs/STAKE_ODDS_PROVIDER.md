# Stake sportsbook research bridge

Status: **experimental / read-only / research-only**.

The bridge reads the current Stake web sportsbook GraphQL contract only after
SEFIROT has already sealed a sports-only prediction. It never places wagers and
cannot grant monetary admission.

## Live contract verified 2026-10-05

The old draft field `sportsEvents` is no longer present. The current working
two-stage flow is:

1. `SportTournamentFixtureList` via `slugSport(...).tournamentList(...).fixtureList(...)`
2. exact home/away/kickoff matching
3. `FixtureIndexGroups` for the selected fixture slug
4. `FixtureGroupMarkets` in bounded group chunks

The request uses the same Apollo headers expected by the web client plus the
`x-access-token` credential. A live Render smoke test authenticated the token,
returned 200 soccer events and found the current UEFA Nations League fixtures.
For Cyprus-Latvia the exact fixture returned 14 market groups and 292 raw
markets.

Observed groups include:

- main / goals / AsianLines / goalscorers
- 1st2ndhalfmarkets
- CardsCorners
- specials / MinuteMarkets
- Total / winner / Handicap / Both Teams to Score / threeway / 1UP2UP

Observed small-market examples include match shot thresholds, full-time total
corners, first-half total corners and team corner ranges.

## Credential

Keep the secret only in runtime environment:

```text
STAKE_API_TOKEN=...
```

Do not store it in Git, receipts, logs, line IDs or reports. A token that has
been pasted into chat should be rotated before long-term production use.

## Run from SEFIROT

A real prematch prediction must already exist in the ledger.

```powershell
py -3 sefirot.py --db data/sefirot.sqlite stake-snapshot PREDICTION_ID --output data/stake.json
```

The standalone runner is also available:

```powershell
py -3 scripts/stake_snapshot.py --db data/sefirot.sqlite PREDICTION_ID --output data/stake.json
```

Both flows create:

- the raw Stake snapshot
- a normalized research file at `<output>.normalized.json` unless another path is supplied

Fixture matching remains exact. No fuzzy aliases or silent home/away swaps.

## Normalization

`src/sefirot/stake_mapper.py` maps only market shapes that were explicitly
verified or are mechanically unambiguous.

Current canonical big-market support:

- 1X2
- Double Chance
- Draw No Bet
- Both Teams to Score
- Asian Total on integer/half-goal lines supported by CORE
- Asian Handicap on integer/half-goal lines supported by CORE

Quarter lines are preserved in raw data but rejected from the CORE main-market
mapping because current settlement code supports only integer/half lines.

Current descriptive small-market support:

- match total shots expressed as `N+ shots`
- full-time total corners
- first-half total corners
- full-time total cards when that exact template is exposed
- first-half total cards when that exact template is exposed
- team corner ranges as categorical research data

The small-market mapper does **not** convert these prices into model
probabilities or EV. It only joins price semantics to a clearly labelled raw
Stake market.

## Safety / provenance

Normalized Stake output keeps:

```json
{
  "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
  "freshness": "RECEIPT_TIME_ONLY",
  "settlement_rules": "UNVERIFIED_PROVIDER_WEB_CONTRACT",
  "monetary_permission": false,
  "execution_enabled": false
}
```

Stake does not expose a provider-side market timestamp through the current
query, so the receipt time is not claimed to be the quote creation time.
Settlement rules also remain an unverified web contract. For that reason Stake
prices are a research price screen, not yet an execution-certified quote.

Builder / Same Game Multi prices remain bookmaker-specific joint prices. Never
reconstruct them by multiplying singles.

## Tests

The dedicated Stake provider and mapper suite covers:

- token/header isolation
- current Apollo operation names
- exact fixture matching
- two-stage group/market parsing
- main-market normalization
- quarter-line rejection
- shots/corners small-market normalization
- fail-closed safety flags

The suite passed 8/8 on Render on 2026-10-05.
