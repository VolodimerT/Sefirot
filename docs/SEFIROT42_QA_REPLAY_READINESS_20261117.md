# SEFIROT 4.2: QA, historical replay and prematch readiness

## Confirmed fixes

- A `PST` fixture previously had only the generic `PREMATCH_ONLY` blocker.
  The offline scanner now records `FIXTURE_POSTPONED`, unknown new kickoff and
  requirement for a new plan. No old seal is relabelled to the new schedule.
- The Odds API values `2.25` and `2.2500000001` previously formed separate
  quarter-line partitions, each incorrectly marked `INCOMPLETE_LINE`.
  Values within the existing quarter-grid tolerance now use one canonical
  line. The complete pair is correctly `UNSUPPORTED_QUARTER_LINE` for CORE;
  the neighboring supported 2.5 partition is retained.

Both defects were reproduced by failing regressions before the fixes.

## Replay of old decisions

`Service.replay` correctly refuses to execute a seal made with a different
`code_hash`. An earlier 4.1 rehearsal of PR #79 accidentally imported
`research` from the current working directory. The test was repeated with
each historical process running from its own archived source root.

The offline `scripts/replay_historical.py` selects a pinned local Git commit
from the seal's exact `code_hash`, verifies version 2.4.2, and runs that
commit's `Service.replay` against a temporary copy of a checkpointed SQLite
ledger. It checks the journal hash chain and SHA-256 of both original and
copy; it cannot fetch source code or modify the source ledger. Unknown builds
and uncheckpointed WAL files fail closed. Pins are reviewed commits PR #78
`72f8018e0719f05ec8aa74398e1a582a82d6d06d`, PR #79
`84dce563fc8a444118276cdaa0f332e6a8e79b8c`, and PR #80
`dbf32996c07ec9c1f1fca7fe1243ab4eaf033c86`.

Independent synthetic journal rehearsals from those exact source trees each
returned `MATCH` with original and copy unchanged. Recorded build hashes:

| Build | `code_hash` |
| --- | --- |
| PR #78 | `81a6ff3f4f0eafab6ac4f487ccaf0f76cca1422e7a8bed6a53096a0a7c84a0f5` |
| PR #79 | `535cc07b10d7fd3d9fc62ce504acb08931de145b9cf3e263c04e8dd109fbcb02` |
| PR #80 | `542694a63cc878e58a5483ffb48c0af99f1a340c4a8a4dbd3195ffbbb3a169bb` |

This is compatibility evidence on isolated synthetic journals. A production
journal has not been exported or replayed in this work.

## Saved real prematch day

The offline pass for 30 October 2026 used the same 28 saved league-scoped
`/fixtures` packets and frozen cutoff `2026-10-29T20:04:00+00:00` as PR #80.
The latest receipt was `2026-10-29T20:03:22.554Z`, earlier than the first
kickoff `2026-10-30T00:30:00Z`. The 29 unique fixtures and all 203 main-market
cards remain `PASS`; network requests, journal writes and actual quotes are
zero. No global calendar completeness or provider authentication is claimed.

The old report hash was
`dff9374b89095ae13b08e1bcdd2a72987fa9a253205806f76502ad064188c601`.
The new report hash is
`054e4f6334e538fe8445620856da7d08ae47e21f428688ac17a2f7158f2fec91`.
An exhaustive JSON comparison found exactly three changed paths:
`/code_hash` (the odds adapter source changed), `/scanner_sha256` (the
postponement diagnostic changed), and `/report_hash` (which binds both).
All fixture and market values are identical.

Read-only Supabase inventory on 17 November: 485 archived sports packets,
313 `/fixtures/statistics`, 164 `/fixtures`, 5 `/fixtures/lineups`, 3
`/status`; canonical predictions, decisions and bookmaker snapshots are all
zero. The observed statistics include shots, corners and fouls. **Correction
from the 4.3 independent QA:** the earlier query missed the snake_case
`expected_goals` statistic. It contains 528 populated values in the archived
fixture-statistics packets; all were received after their source fixture's
kickoff. See `SEFIROT43_INDEPENDENT_QA_20261117.md` for the lineage check.
There are no archived injuries endpoint packets or trusted bookmaker quotes.
Statistics received after kickoff cannot be used as prematch features for
that fixture.

The existing `forward.create_plan`/`capture_plan` is the only seal creation
path. It requires an explicit league/profile map, a future `NS` fixture,
original archived receipt and sufficient history; kickoff changes require a
new plan. The saved day fails the existing evidence gates on all 29 matches:
insufficient pre-kickoff history, missing team/lineup/injury/tactical evidence,
and unattested sporting origin. No historical seal was reconstructed and no
new real seal was created. New data must be captured prospectively through
the protected source gateway and then reviewed before an isolated research
plan is created. This work did not open a paid API window.

TRAIN, CALIBRATION and HOLDOUT remain unqualified. No Brier, Log Loss, ECE,
positive EV or express edge can be claimed. Small markets remain SHADOW;
yellow cards retain the Referee Gate. Expresses remain `PASS` without a
validated joint probability, actual combined price and settlement rules.
