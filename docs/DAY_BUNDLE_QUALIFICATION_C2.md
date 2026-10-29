# C2 — Day Bundle Qualification

Base: C1 PR #73, exact commit `08246f7af5c0bfed8c3be92e66f20cd7bb67f8c3`.
C1 tests and shared-provider-budget workflows completed successfully. This work
uses a separate branch and Draft PR above C1, with no merge or production work.

**Real-data qualification is blocked: no real archive, checkpointed SQLite
snapshot, saved-day calendar or W1 audit was supplied or found in this workspace.**
Only C1's explicitly synthetic demo SQLite files were found. They are not used as
C2 input. No claim about W1's contents or approval is made. The machine-readable
[missing-input report](evidence/c2/qualification-inputs-missing.json) contains zero
invented fixtures, null P/EV, false fit/execution permissions and a single next
blocker. It is an input-availability report, not a qualified football-day report.
The requested 2026-10-29 date does not assert that a saved real calendar exists.

## Entry point

```sh
python scripts/qualify_day_bundle.py \
  --calendar /path/to/original-calendar-packet.json \
  --archive /path/to/original-hash-named-sports-archive \
  --snapshot /path/to/checkpointed-source-snapshot.sqlite \
  --audit /path/to/W1-report.md \
  --day 2026-10-29 --timezone Europe/Kyiv --as-of 2026-10-29T10:00:00Z
```

All data inputs are explicit. There is no discovery fallback to examples, demo
SQLite, hosted storage, provider HTTP, credentials or a synthetic generator.
Omitting the inputs reproduces the checked-in missing-input report. CLI emits
JSON to stdout only; choose an output path outside the archive/snapshot. Private
real input/report files must remain outside Git. W1 is hashed as a referenced
file; a file or caller statement never grants review authority or fitting.

## Evidence and chronology

The existing sports archive scanner checks original filename/content hashes,
receipts, provider/query echo and sporting-only payloads. The original immutable
read-only SQLite adapter rejects WAL/SHM/journal sidecars, checks SQLite integrity,
foreign keys and journal hash-chain, and verifies unchanged bytes after reading.
Existing forward-plan/assignment/capture checks and the source-ledger packet/QC
reader are reused. An empty forward ledger may still be a valid source-only
snapshot; that does not manufacture roles or capture bindings.

The fixture map contains provider/canonical fixture ID, league/season, exact
provider team IDs, observed names, UTC kickoff instant, packet and receipt hashes,
receipt time and first *locally recorded* availability. Aliases are not guessed.
Conflicting teams/kickoff/season, query/fixture mismatches and revised FT results
are quarantined. A calendar observation is included in identity checks even if
its ID already exists in the archive. Missing real calendar cannot be replaced
with an inferred date-filtered historical sample.

A prematch feature packet must be NS and both received and locally available
strictly before its own kickoff. A receipt that says 10:00 but was imported at
13:00 cannot support a 12:00 prematch feature. An archive hash alone does not prove
when the operator first possessed that packet: availability stays null without a
verified original source-ledger binding. Neither local ledger timestamps nor
hashes are provider signatures or independent origin attestation.

FT results become labels only after a plausible regulation FT receipt (at least
90 minutes after kickoff), local availability and the frozen as-of cutoff. They
are never features of their own prematch row. Earlier history and statistics can
support another fixture only if already available before that target's kickoff;
future receipts/late local imports are excluded. Returned lineage has hashes and
IDs, not raw results smuggled into a model feature vector.

## Dataset roles

Per-fixture TRAIN/CALIBRATION/HOLDOUT reviews separate chronology usability,
structural coverage and actual qualification. Existing reserved CALIBRATION,
HOLDOUT or MONITOR rows cannot silently become TRAIN. CALIBRATION/HOLDOUT require
original prospectively reserved roles, reservation before seal and kickoff,
original unreconstructed prematch seals and forward capture bindings. HOLDOUT
also checks a frozen nonsynthetic calibrator's hash/schema/model/Policy and fit
chronology before the seal. No reserved HOLDOUT ID may appear in its fit IDs,
including other HOLDOUT fixtures.

A positive chronology check is **not** dataset admission. Missing feature sources,
unknown definitions/availability and absent external provenance remain explicit.
`qualified=false` and `model_fit_allowed=false` always: this module neither assigns
splits nor fits a model, calibrates, registers a cohort, seals or rewrites a
prediction. Existing model probability and EV requirements are not relaxed; this
qualification report exposes neither P nor EV at all.

## Coverage and missing sources

The report includes the saved-day fixture ID set, full archive fixture map,
coverage by league and all eleven C1 market families, role counts and concrete
missing-source descriptions. It checks for first-available FT history, exact
historical fixture/team statistics, documented xG, confirmed prematch lineup and
injury FACTs bound to an original capture, and a separate exact bookmaker/event/
line/settlement/quote-receipt source. Quotes are a separate evidence gap, never a
TRAIN feature requirement or a sports-model input. A visible xG metric still does
not attest its provider's definition. No direct injuries/odds access is invented.

FOULS requires direct committed/suffered foul counts and its own validated count
model. It does not borrow YC or require referee approval. Referee Gate applies
only to Yellow Cards. Other small markets retain their separate count-model gaps.

## Europe/Kyiv day contract

`research/day_calendar.py` is shared by C1 scanner and C2 qualification. Supported
zones are exactly UTC and Europe/Kyiv. A Kyiv calendar must have an explicit
Europe/Kyiv date query/echo; a UTC date packet cannot be relabelled Kyiv. Stored
kickoff/receipt bytes are never rewritten. The selected day is the half-open
interval between consecutive local midnights, converted to UTC; it can span two
UTC dates. Winter/summer offsets and 23/25-hour DST days are tested. C1 CLI accepts
`--timezone Europe/Kyiv`; UTC remains its default for compatibility. The qualifier
defaults to the explicitly reported Europe/Kyiv zone.

## Validation and preservation

New contract tests use owned synthetic fixtures solely as tests; they are never
published as C2 real data. Coverage includes Kyiv midnight and DST boundaries,
late imports, own-result leakage, role reservation/fit overlap, original calendar
identity conflicts, query mismatches, unchanged DB/archive bytes and WAL rejection.
All C1 fixtures, saved reports and historical seals remain intact. The scanner
implementation changes its own digest; old saved C1 reports keep their original
build provenance instead of being regenerated or re-signed.

Final local release evidence and source hashes are under [evidence/c2](evidence/c2/).
Local optional-native skips are not passed tests. Full exact-head CI is tracked
in the new Draft PR; earlier C1 CI is not attributed to C2.

## One next blocker

**Provide the real saved-day calendar + original receipt archive + checkpointed
SQLite snapshot (and W1 reference).** Then rerun this exact implementation against
those unchanged inputs and review its per-record reasons. Until those inputs
exist, real per-league/market counts cannot be asserted and no actual TRAIN,
CALIBRATION or independent HOLDOUT dataset is qualified. No production export,
API quota spend, deployment, hosted write, automation or money is authorized.

Final local Python 3.14.3 release: **1699 passed / 9 skipped / 1708 total**,
exit 0; integrity/replay true. All 23 new C2 contracts pass; all 30 C1 regressions
remain green. Node gateway/cockpit/session: 41/11/12, exit 0. These are engineering
tests, not a qualification of absent real data. Source/artifact hashes:
[validation.json](evidence/c2/validation.json).

Unknown day coverage is not an empty day: when the calendar is absent/rejected,
`day_fixture_count` and market `saved_day_fixtures` are null. Zero qualified rows
means no admitted dataset, not evidence that zero matches took place. The explicit
`qualification_status` is `INPUTS_MISSING_OR_REJECTED` for this workspace report.
