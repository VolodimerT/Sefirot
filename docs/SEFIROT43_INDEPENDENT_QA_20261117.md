# SEFIROT 4.3: independent QA and data readiness

Base: draft PR #81, commit `45889c4a5648a7a3f1f88c1cc75f9145ea8a7587`.
No independent Work attachment or review comment was available in the local
workspace or PR #81, so each reported defect was checked against source code
and an isolated regression. No production change or provider request was made.

## Confirmed code corrections

- Historical replay previously used `git archive` under inherited Git
  environment and repository replacement refs. A `git replace` could select
  a different tree for a pinned commit; a nested package could be included
  without contributing to the top-level `code_hash`. The router now ignores
  replacement refs and inherited Git object/config overrides, verifies the
  content hash of the commit, each tree and each blob, and permits only flat
  `.py` files under `src/sefirot`. Corrupt objects and nested modules fail
  closed. It also pins the PR #81 build.
- The day qualification report previously selected the *earliest* fixture
  observation as its current kickoff, then could evaluate newer observations
  against that old time. It now displays the latest recorded kickoff and
  quarantines all prematch features and labels if identity or schedule
  changed. The scanner's exact fixture/kickoff seal matching was separately
  tested: a moved NS fixture cannot reuse the old seal.
- An express with identified shared factors previously reported death-test
  status `RAW_INDEPENDENCE_DIAGNOSTIC_ONLY`. It now reports
  `BLOCKED_CORRELATION_UNMODELLED`; the raw product remains explicitly a
  hypothetical diagnostic, not a validated joint probability or quoted EV.
- Negative quarter handicaps `-0.25`, `-0.75`, `-1.25` and near-grid
  `-0.2500000001` settle with the expected half outcomes. A value outside
  the existing grid tolerance is rejected. Opposite provider sides around
  `-0.25/+0.25` remain one unsupported research partition while a supported
  neighboring line is preserved. No further math change was warranted.

The exact-build replay rehearsal succeeded for isolated synthetic journals
from PR #78, #79, #80 and #81: `MATCH`, original and copy SHA-256 unchanged.
No production ledger was supplied or replayed.

## Correction: API-Football expected_goals

Read-only SQL on `sefirot-core` on 17 November found `expected_goals` in
original `/fixtures/statistics` packets from `API_FOOTBALL_V3`. The previous
4.2 audit searched for `Expected Goals` with a space and missed the actual
snake_case field; the earlier claim that xG was absent was incorrect.

| Lineage measure | Observed |
| --- | ---: |
| Statistic entries / populated values | 552 / 528 |
| Packets containing the statistic | 276 |
| Unique source fixtures with populated values | 259 |
| Unique team-fixture pairs | 518 |
| Repeated pairs / pairs with revised values | 10 / 2 |
| Numeric range of populated strings | 0.08–6.74 |
| Values received before source fixture kickoff | 0 |
| Values received after last saved source kickoff | 528 |

The response has a numeric string under `type=expected_goals`; it does not
include an explicit unit or calculation definition. It appears to be a
per-team match statistic, but that semantic claim and provider licence terms
must be confirmed from authoritative documentation before model use. These
are postmatch observations for their *own* fixtures. They may become
historical features for a later target only if their archived receipt and
first local availability precede that target's kickoff, fixture/team identity
and revisions pass QC, and licence and model validation permit use.

For the 29 fixtures in the saved 30 October calendar, a simple read-only
time-and-team join finds 14 with at least one prior home-team xG source, 13
with at least one prior away-team source, and only 12 with both. The largest
observed prior sample is nine matches for a team. This join checks receipt
time, not independent provider authenticity, first local availability,
opponent adjustment or model calibration. It does not produce probability
seals or justify EV.

## Repeated offline day and remaining blockers

The same 28 saved league-scoped calendar packets still produce 29 fixtures,
203 main-market `PASS` cards, zero quotes, zero API requests and zero ledger
writes. PR #81 report hash
`054e4f6334e538fe8445620856da7d08ae47e21f428688ac17a2f7158f2fec91`
changes to
`ed04968de2be88dfba9aef794d1e1228ea573c2e7b4a58d84afdf2b898d1d79f`.
An exhaustive comparison found only `/code_hash` (the express source changed)
and `/report_hash` changed; every fixture and market value is identical.
The earlier 4.1 control hash was
`dff9374b89095ae13b08e1bcdd2a72987fa9a253205806f76502ad064188c601`.

The existing forward planner is the only path to new prospective seals. A
new real run needs future `NS` fixtures, explicit league/profile mapping,
complete original pre-kickoff sports packets with local first-availability,
reliable historical team features, source identity and a clean dedicated
research ledger. The saved 30 October day is historical and its missing
seals cannot be reconstructed. Separately, price comparison needs exact
fresh bookmaker event/market/line/period/rules and trusted server receipts.
The 17 November Supabase inventory still has zero canonical predictions,
decisions and bookmaker snapshots. No new paid collection window was opened.

TRAIN/CALIBRATION/HOLDOUT, Brier, Log Loss, ECE and independent express value
remain unverified. Small markets stay SHADOW; yellow cards retain the
Referee Gate. PREMATCH / RESEARCH_ONLY / PASS / stake=0 remains mandatory.
