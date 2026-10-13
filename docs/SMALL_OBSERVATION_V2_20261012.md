# P0 small-market source contracts — 12 October 2026

A two-team archive cannot establish complete league coverage. The old
`small_market_readiness.preview` has no assigned fixture denominator or revision
history. This isolated continuation of draft #35 adds an offline normalized
observation contract and deterministic QC CLI; it does not replace the original
CORE or claim source-backed calibration.

## Delivered interfaces

- `schema/small_observation_v2.json`: strict JSON Schema for batch, assigned
  league manifest, normalized match observations and referee priors.
- `research/small_observation_v2.py`: semantic validator, exact identity joins,
  information-cutoff revision selection, duplicate/quarantine handling,
  nullable counts and per metric/period/team completeness report.
- `scripts/small_market_qc.py`: offline JSON import and exclusive report output.
  Duplicate JSON keys and nonfinite numbers fail closed. No input yields a
  missing-data matrix with **null denominators**, rather than a synthetic league.
- `validate_market`: exact CORNERS/SHOTS/SOT/FOULS_COMMITTED/YELLOW_CARDS/
  RED_CARDS/SECOND_YELLOW/BOOKING_POINTS and FT/1H/2H; total, team total,
  handicap and CORNER double chance. Asian integer, half and quarter line
  identities are explicit. This validates syntax only: no settlement execution,
  quarter-line payoff, quote authentication, joint probability or wager advice.

Observation v2 requires provider/competition/season, fixture/home/away/venue,
aware kickoff, source published/received/available timestamps, raw SHA reference,
revision and parent normalized record hash, source kind/license reference,
provider metric-definition IDs, and explicit home/away nullable counts for each
period. REFEREE priors require competition, sample size, YC/game, YC/foul,
availability before kickoff and raw SHA reference. No caller `verified` field
is accepted. Provider-specific bench/coach/second-yellow or booking-point rules
must be encoded in definition/rules IDs; they are not silently interchangeable.
Player props, corner ranges, event order and first scorer are unsupported.

## Temporal and integrity semantics

Only LEAGUE manifests are accepted. FT regulation fixtures known in the input
manifest and kicked off before the information cutoff form the **candidate**
denominator. VOID/PST/ABD/AET/PEN/NS/LIVE are separately counted and excluded.
The manifest's status is an input observation, not independent FT verification.
Foreign competitions, seasons, provider IDs or swapped teams cannot join.
Replayed fixtures need new source IDs and a revised external assigned manifest.
Identical duplicate rows do not increase sample size; conflicting same revisions
quarantine the fixture. Corrections require contiguous parent-hash linkage and
nondecreasing clocks; latest available revision supplies all counts. Missing
counts are never filled from an older revision. Post-cutoff revisions cannot
quarantine earlier valid snapshots. Reordering does not change selected values,
although batch hash and row-index diagnostics retain input order.

SOT <= SHOTS and half counts <= FT are checked for both sides. Where all three
periods exist, FT must equal 1H+2H. Negative/bool/fractional counts fail. Contradictory
raw identity/counts cause packet-level RED QC; varying metric definitions cause
metric-local RED. Missing counts/periods remain explicit. Nullable definitions
cannot establish a comparable measurement.

`observed_coverage` measures count completeness of the supplied archive only.
The assigned schedule, pagination/license references and raw SHA values are
**caller supplied**. Hashes bind normalized bytes but do not bind observations
to original provider payloads or prove completeness/license. Consequently:

- `verified_coverage=null`, `source_attested=false` on every result;
- no GREEN source QC; structural QC is AMBER/RED;
- `status=INSUFFICIENT_REAL_DATA`, P/EV/proper-score metrics null;
- admitted TRAIN/CALIBRATION/HOLDOUT all zero; fit/money false.

This is not a data adapter, certified archive, historical prematch feature set,
trained count model, betting decision or prospective HOLDOUT. Authentic raw
sample/coverage remains blocked until independent source adapters bind actual
licensed immutable receipts. Results first imported now are labels/history;
never backdate their prematch availability. Current LIVE/odds feeds are not read.

## Run

```bash
python scripts/small_market_qc.py --as-of 2030-02-03T12:00:00+00:00 \
  --input private/normalized_batch.json --output private/new_coverage.json
python scripts/small_market_qc.py --as-of 2030-02-03T12:00:00+00:00
python -m unittest discover -s tests -p 'test_small_observation_v2.py' -v
python scripts/verify_release.py
```

The public `reports/DATA_READINESS_BY_LEAGUE_AND_MARKET.json` is the **no archive
supplied** inventory, with zero admitted records and no invented league IDs.
It does not assert that no real data exists anywhere in the private project.
Do not commit real imported archives/reports containing personal source receipts.

## Integration and next single action

Base: #35 exact `9024889b1269ca846dfa1adfcaf5339990c14023` (tree
`820e803885322802c4979d1eedd7a89a7a86bdbd`). #22 is its ancestor at
`9b88d130e69e3be5ee69723469913b36c28bb3e8`. #32 and #36 share #22;
#25 and #26 branch earlier at `053ad5a07c4732c5062ac6a445fc1d61b1c2a119`.
No cross-stack merge is needed for this PR. Original `src/sefirot`, Policy,
MODEL_MODULES, old reports/seals and deployed services stay byte-for-byte intact.
Existing descriptive small_market.py, readiness preview and corners shadow
are intentionally not changed or activated. The new QC runs only when explicitly
invoked; it is not connected to the worker/gateway or every ChatGPT answer.

Next: choose one already authorized licensed offline full-league archive;
implement and test a provider-specific extractor binding actual raw rows,
source identity, schedule/pagination and corrections to v2. If none is supplied,
retain missing inputs and do not request suspended/paid APIs. Only after this
can independent market models and chronological calibration use eligible data.
