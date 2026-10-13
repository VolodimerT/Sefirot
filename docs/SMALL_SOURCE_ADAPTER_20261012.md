# B1 continuation: saved API-Football FT archive adapter

Base: exact draft #37 `c4d2495086acf5f125d7f7ba8d8294ce90bdf84c`.
This is a stacked offline mini-PR; #35 is its ancestor. No merge of #25, #27,
#28, #32 or cloud code. `src/sefirot` remains unchanged. Existing source packet
validators in `sports_archive.py` and `small_market.py` are reused, as is #37's
`audit_dataset`. #25's corner dataset/holdout contracts were reviewed; the
corner model is neither rewritten nor activated.

## Problem and observable change

#37 accepts normalized rows and caller raw SHA references, but cannot check
whether those references match saved packet bytes. The new explicitly invoked
offline path is:

`saved fixture/statistic packet bytes + expected calendar -> exact raw/row bindings -> observation-v2 -> existing league QC`.

It does not create a probability, a forecast, a result job or a betting signal.
No real licensed full-league raw statistic archive was supplied for this turn.
The reviewed Library artifacts contain task/evidence packs, financial ledgers,
model checks and historical source material; they are not admitted full-league
FT statistic receipts. No private material is copied into public Git.

## Inputs and joins

| Input | Required contract |
|---|---|
| Expected manifest | Existing `small-league-manifest-v1`; API_FOOTBALL_V3, explicit league/season/roster/fixtures/venue, license reference |
| Schedule file | UTF-8 serialized original SEFIROT `{data,receipt}` packet; exact `/fixtures` query `league` + `season`, matching response echo, complete single page |
| Statistics files | Serialized `{data,receipt}` packets; `/fixtures/statistics` query with only `fixture`; matching echo, full unfiltered response |
| Source SHA | Manifest `source_sha256` must equal SHA-256 of actual **saved schedule file bytes**, including whitespace |
| Source times | Saved provider receipt chronology valid; FT schedule receipt precedes every statistic request; no packet later than local import |

The raw schedule must match every expected fixture, team ID, kickoff, season
and status. Missing/foreign fixtures, team filters and explicit Cup rows fail.
Venue and competition type remain **operator manifest assertions**; fixture
venue ID alone does not prove neutral/home venue or league classification.
No independent schedule service is contacted. Matching a caller calendar to a
caller packet therefore **does not certify full-league coverage**.

Bounded UTF-8/strict JSON rejects duplicate keys, nonfinite and overflowing
numbers. Existing packet validators check receipt/provider/query/payload hash,
result count, pagination and duplicate teams/types. Archives are limited to
64 MB, each packet to 4 MB, statistic packets to 10,000. Unknown IDs/statuses,
half requests, type/team filters, one-sided responses and SOT > SHOTS fail.
Empty statistic responses survive as explicit null observations.

## Supported extraction

| Metric | Provider label | Period |
|---|---|---|
| CORNERS | Corner Kicks | FT |
| SHOTS | Total Shots | FT |
| SOT | Shots on Goal | FT |
| YELLOW_CARDS | Yellow Cards | FT |
| RED_CARDS | Red Cards | FT |

Labels reuse the original source mapping. These strings identify provider raw
measurements; they are **not verified bookmaker settlement definitions**.
The official [API-Football guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)
describes per-team fixture statistics and warns of null values. Its
[release note](https://www.api-football.com/news/post/api-football-new-release-available)
introduces a separate half parameter. This importer rejects half parameters;
1H/2H remain null and are never inferred by dividing FT counts.

FOULS_COMMITTED remains null: a raw `Fouls` label is insufficient to certify
direction/definition in this v2 contract. SECOND_YELLOW/BOOKING_POINTS and
referee priors also remain null. Fouls never supply referee/card evidence.
Goals 1:1 and cards 4:3 stay different raw metrics; no score conversion occurs.
No player props, events, first scorer, combined quote, odds or Builder model.

## Time, duplicates and corrections

The CLI takes **current UTC time after reading the files** as local import time;
there is no backdating flag. `available_at` and normalized `received_at` are
local import time. `published_at` is the caller's provider receipt time, with
true upstream publication explicitly unknown. The Python replay function takes
an explicit import clock for reproducibility; this caller argument does not
attest acquisition time. An evaluation cutoff before import is rejected.

Every supplied statistic snapshot has raw SHA, schedule/statistic JSON pointers,
first caller-observed time and emitted flag in the binding report. Repeated
packets do not multiply fixtures. Equivalent serializations are ordered by raw
SHA for determinism. Conflicting payloads at one receipt time fail closed.
For retrospective import, the latest supplied snapshot is emitted once as
revision 0; earlier snapshots remain in provenance. They are **not converted
to a fictional historical normalized revision chain**. A later missing value
erases earlier counts; no forward-fill. This importer does not append revisions
to an existing normalized ledger and never rewrites older import reports.

## Run

```bash
python scripts/small_source_import.py \
  --manifest private/expected_manifest.json \
  --schedule private/whole_league_packet.json \
  --statistics private/fixture_statistics_packet.json \
  --output private/new_import_bundle.json
python -m unittest discover -s tests -p 'test_small_source_adapter.py' -v
python scripts/verify_release.py
```

Repeat `--statistics` for multiple local files. Output is exclusively created;
existing bundles cannot be overwritten. The one bundle contains normalized
batch, mechanical binding report and unchanged #37 coverage QC. CLI errors
never echo provider messages or raw JSON. If schedule metadata exists but no
statistics are supplied, the assigned denominator is retained and counts are
missing. Do not commit actual source archives or private import bundles.

## Readiness and limits

`saved_packet_bytes_bound=true` means mechanical extraction is reproducible
against supplied files. `original_http_bytes_bound=false`, `source_attested=false`,
`license_verified=false`, `manifest_completeness_attested=false`. #37's generic
coverage blockers remain deliberately conservative; the separate binding
section is not an admission token or independent source witness.

Actual admitted TRAIN/CALIBRATION/HOLDOUT = 0; coverage verified/P/EV/proper
scores null, fit/money/holdout eligibility false. Worker integration, deployed
runtime, Project instructions and provider access were not changed or retested.
Historical queue counts from #37 are not represented as fresh measurements.

Next single action: independently verify one permitted full-league schedule and
matching saved post-FT statistic archive, then run this explicit offline import
and inspect the metric/period coverage. Without that archive, retain the exact
missing-input report; do not request suspended/paid APIs or claim model gain.
