# SEFIROT 4.4 — independent QA and prospective readiness (17 November 2026)

## Scope and recovered Work evidence

Base is PR #82 at `62eddbc94f293f929cfe15300687881e27949187`.
PR #82 has no published review comments or attached five-case Work list. The
remote branch visible at the start of this pass was still that exact commit.
The five failures therefore cannot be claimed reproduced by name. Existing
PR #82 regressions already cover Git replace, object verification, nested
executable packages, rescheduled fixtures, negative Asian lines and express
correlation status; these were kept. No CORE code or historical seal changed.

## Reproduced defects and changes

An active SQLite rollback transaction creates a `-journal` sidecar. Historical
replay previously checked only `-wal` and `-shm`, so it accepted this live
ledger. A regression reproduced the acceptance before the fix. Replay now
checks all three SQLite sidecars at entry, after copy and after child replay,
and compares file identity/metadata to reject an identical-byte path swap.
It still uses an isolated read-only copy and verifies the original and copy
SHA-256. This is a fail-closed offline snapshot requirement, not a live DB
backup facility.
Isolated synthetic journals generated from the pinned PR #78, #79, #80 and
#81 builds each replayed as `MATCH`; each original SQLite SHA-256 was unchanged.
No production ledger was provided or touched.

The day qualification report previously counted a populated
`expected_goals` field as qualified xG, although the saved original does not
define its unit or methodology. It now reports the field as observed while
keeping `feature_coverage.xg=false`. Historical statistics are selected only
when the source match kickoff precedes the statistic receipt, and both receipt
and first local availability precede the scan cutoff and the target kickoff.
These four times are included in each source reference. The existing fixture
revision and old-seal blockers remain in force.

## Read-only source audit

The `sefirot-core` original archive has 552 `expected_goals` entries, 528
populated, covering 259 source fixtures. Ten team/fixture pairs repeat and two
have changed values. First imports span 18 October to 7 November. The original
responses contain no explicit xG unit/definition, so the field is not yet a
validated model feature.

For the 29 fixtures in the saved **UTC** 30 October calendar, a receipt-only
join gives 14 home teams, 13 away teams and 12 fixtures with both sides' prior
xG. With the actual scan cutoff `2026-10-29T20:04:00Z`, first local import and
each target kickoff enforced, the counts are 8, 5 and **3/29**. These are
coverage counts, not valid model probabilities. No xG was allowed into a
historical seal by this audit.

At the time of the read-only query, 118 saved `NS` fixture IDs were scheduled
within seven days, including 10 EPL IDs. The newest saved `/fixtures` receipt
for those was 7 November. `NS` in a saved packet is not proof of current match
status. No sports API call or production write was made.

The existing saved 30 October UTC bundle was scanned again offline: 28
original packets, 29 fixtures, 203 main-market `PASS` cards, zero network
requests. The report hash remained
`ed04968de2be88dfba9aef794d1e1228ea573c2e7b4a58d84afdf2b898d1d79f`,
identical to PR #82. This pass does not create a historical forecast.

## First real prospective seal

Use the existing forward planner on an isolated research ledger for one future
fixture, after a newly authorized gateway collection. Require: current `NS`
identity and kickoff; original fixture and team-history packets with receipts,
hashes and first-local-availability before seal time; confirmed provider
definitions for any xG feature; model/profile coverage and independent fit;
and a frozen source set. Reserve prospective role before the seal and verify
the seal timestamp is before kickoff. Read result only after FT and retain the
original seal unchanged. Current archive freshness, xG semantics, feature
coverage and independent calibration are insufficient for this admission.
No retrospective reconstruction, price, EV or BET is justified.

## Verification

Focused tests: 57 passed. Full `scripts/verify_release.py`: 1737 tests,
1728 passed, 9 skipped, exit 0 on local Python 3.12.14. GitHub CI includes
Python 3.14.3 and must be checked on the pushed exact HEAD. Production, paid
APIs, monetary execution and main were untouched.
