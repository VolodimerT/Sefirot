# SEFIROT 3.0 / C1 — DAILY PREMATCH SCANNER v0

Mission date: 2026-10-28. Engineering verification completed on 2026-10-29 UTC.
This is an isolated offline extension of CORE 2.4.2, not a production upgrade.

**Current result: PASS, zero candidates, stake=0. All value markets remain blocked.**
The scanner is runnable and reproducible. Independent source/quote attestation and
prospective calibration are still absent. The ranker has synthetic regression
coverage, but no real shortlist or positive-value qualification is demonstrated.

## Recovered checkpoint

- `main`: `d09a8af22f0dec8c84bc203d468b913b46fc2f94`.
- PR #56 actual HEAD: `50e91e7addee6f4c1140d496cfcad1f4aa62494c`, branch
  `feature/situation-integration-20261013`. Its body names an older candidate.
- `feature/stability-reset-20261005`: `6cfa1f126a2ab64730c32a9ed43003713b6d804a`,
  equal to the Render SHA supplied by the owner. Render runtime was not queried.
- Integration versus that SHA: diverged, ahead 11 / behind 4; merge base
  `b1b431effdda1c2632b8983eaf0bac504cf44c2a`. No automatic merge/cherry-pick.
- Merged #70 (`3461ef75…`) and #71 (`6ac583bf…`) are ancestors of #56 HEAD.
- #72 is not an ancestor, but all four affected files are **byte-identical**
  between #56 HEAD and `6cfa1f1…`: worker/gateway allowlists and both regression
  files. This verifies the Free Kicks fix without merging divergent histories.
- New branch: `feature/daily-prematch-scanner-c1-20261028`, parent exactly #56 HEAD.
  Draft PR targets the integration branch, not main or the deployed branch.

Machine evidence: [checkpoint.json](evidence/c1/checkpoint.json).
All 64 `src/` files (including seven MODEL_MODULES and Policy), all 40 existing
`reports/` files, server/SQL contracts, original receipts and seals are unchanged.
No journal migration or historical re-signing occurs. Scanner implementation has
its own SHA-256 in every report; the unchanged CORE build/model hashes identify
CORE rather than claiming to hash the new research module.

## Offline flow

1. Read a saved API-Football calendar packet and hash-named sports archive.
   Require an unfiltered UTC date query, matching request echo, result count,
   complete pagination, valid hashes and exact fixture identities. Scope is all
   **provider-available** fixtures for that date. Worldwide completeness and
   provider origin are explicitly not attested by local hashes.
2. Export each not-started fixture through existing `sports_archive.export_sports`.
   Keep its real history/personnel blockers and coverage. Packets first received
   after cutoff cannot enter sporting inputs; kickoff closes the prematch window.
   Finished/live/postponed fixtures cannot become candidates.
3. Optionally open an existing SQLite ledger read-only, in a read transaction.
   Verify hash-chain, select the latest exact canonical fixture seal at cutoff,
   match build/Policy, replay its original decision and reuse its stored recheck.
   No fresh lineup, seal, calibration, result or decision is manufactured.
4. Optionally normalize a saved The Odds API event with the existing
   `quotes_from_event` adapter. Exact teams/kickoff/event, complete partitions,
   period/settlement/line and timestamps are checked. Arbitrary pre-normalized
   quotes, probability overrides and tipster fields are rejected. There is no
   network fallback. Local payload hashes do not attest origin or availability.
5. Call existing pure `engine.decide` with zero bankroll; never call the recording
   `Service.decide`. Probability is exposed only after existing probability-trust,
   frozen calibration and nonsynthetic context HOLDOUT gates pass. Otherwise
   probability, fair odds and EV stay null. Unvalidated death-test branch
   probabilities and stress EV are also suppressed. Implied P is separate from
   model probability and can describe an accepted saved price without value.
6. Carry existing tactical/public-trap/death-test diagnostics. Missing popularity
   evidence is explicit. No proven alternative means `alternative_market=null`.
   Markets absent from the sealed pool are displayed as blocked, never added to
   the original model pool after seeing prices.
7. Rank only fully proven positive robust-EV rows, maximum two; reject shared
   teams, fixtures and league/day clusters. This is a conservative exclusion rule,
   **not statistical proof of cross-league independence**. Positive ranker tests
   use synthetic projection rows, not a newly validated model.

In v0, unconditional missing independent sporting/quote-origin evidence keeps
all actual scanner outputs PASS. There is no caller flag to attest this away.
No BET, LIVE, ladder, loss chasing, stake progression, scheduler or execution
path is introduced. Future attestation requires a separate reviewed integration.

## Running

From the repository root (Python >=3.11), use a **new** owned directory:

```sh
python scripts/daily_scanner_demo.py --output /tmp/sefirot-c1-demo-new
python scripts/daily_prematch_scanner.py \
  --calendar /tmp/sefirot-c1-demo-new/calendar.json \
  --archive /tmp/sefirot-c1-demo-new/scenario/archive \
  --database /tmp/sefirot-c1-demo-new/scenario/scenario.sqlite \
  --prices /tmp/sefirot-c1-demo-new/prices.json \
  --day 2030-01-01 --at 2030-01-01T09:02:00+00:00 \
  --profile LOWER --synthetic
```

Use the exact `as_of` in the generated report when replaying (the frozen fixture
owns its timestamps). `--markdown` selects text; normal CLI output is JSON.
The scanner writes only stdout. The synthetic demo exclusively creates its output
directory and delegates to the existing owned scenario. Never point it at an
existing personal ledger. Real saved inputs must not use `--synthetic`; they
remain labelled `SAVED_OFFLINE_NOT_EXTERNALLY_ATTESTED` and cannot gain permission.

Checked-in example: [DAILY_REPORT.json](../examples/daily_scanner_synthetic/DAILY_REPORT.json)
and [DAILY_REPORT.md](../examples/daily_scanner_synthetic/DAILY_REPORT.md).
Its 2030 date, names, history and prices are **synthetic frozen test data**, not a
forecast of an actual football day. It shows implied P where available, null
model P/EV, all seven main families, four small families, explicit PASS and zero
monetary permission. SQLite/demo artifacts are not published in Git.

## Markets

| Family | Engineering support | Current value status |
| --- | --- | --- |
| 1X2 | Existing sealed CORE contracts + saved complete provider partition | BLOCKED |
| DC | Existing sealed CORE contracts; no derived synthetic DC price | BLOCKED |
| DNB | Existing win/push/loss settlement; no naive `P*odds-1` shortcut | BLOCKED |
| Handicap | Existing supported integer/half lines; quarter lines rejected | BLOCKED |
| Totals | Existing exact line and regulation-period contracts | BLOCKED |
| BTTS / ОЗ | Existing sealed CORE contract and opposite outcomes | BLOCKED |
| Team totals / ИТ | Exact team, direction, line, regulation period | BLOCKED |
| Corners / shots | Research rows; no calibrated P/EV; no conversion from goals | BLOCKED |
| Fouls / yellow cards | Research rows; existing Referee Gate stays HOLD | BLOCKED |

The saved price adapter does not invent prices for unavailable families. An absent
family is a data gap, not a reason to shop a prettier accumulator.

## Initial C1 validation and limits (449cfbcc)

See [validation.json](evidence/c1/validation.json) and retained logs in
[evidence/c1](evidence/c1/). Counts distinguish passed/skipped/failed. The initial
sandbox failure is retained: loopback bind was forbidden and PGlite missing.
After installing the pinned test-only dependency and permitting local loopback,
the full Python 3.12.14 suite passed (1665 passed / 9 skipped / 1674 total at the
19-regression stage). Final source on Python 3.14.3: **1668 passed / 9 skipped / 1677 total**,
full release exit 0; demo integrity/replay true and 12-fixture / 84-row synthetic
backtest complete. The 22 C1 regressions pass with no skips.
No tests or assertions were removed to hide environment failures. Native optional
PostgreSQL skips do not certify native PostgreSQL; PGlite SQL tests run locally.

## P0 / P1 and next checkpoint

**P0:** independent sports source origin; complete/usable team history and lineup
proof; frozen nonsynthetic calibration and independent prospective context
HOLDOUT; independently confirmed fresh quote origin/settlement/availability.
Until each relevant gate passes: P=null where unvalidated, EV=null, PASS/stake=0.
The current implementation intentionally cannot produce a real value shortlist.

**P1:** worldwide/provider coverage attestation beyond a single saved date query;
prospective multi-fixture/league-day ranking audit and explicit dependence
assessment; independently calibrated small-market models and referee provenance;
native PostgreSQL verification in a dedicated test service where required.

Next checkpoint: review this exact Draft PR/tree and its exact-head CI; supply
an immutable, authorized **offline** day bundle with first-availability timestamps,
source provenance, already validated calibration/HOLDOUT artifacts and separate
quote evidence. Re-run without changing original seals, Policy or journal.
Source/quote attestation design is a separate code review; no budget activation,
provider call, production write, deployment or merge is authorized by this report.

## Follow-up: whole-day retention and archive failures, 29 October

The initial C1 checkpoint above is commit `449cfbcc5391bd196dc5d68cad3ee5dc4c8be66e`.
Its 10/10 CI jobs passed on their first attempts; all five unit matrix jobs logged
22 C1 regressions and 1668 passed / 9 skipped / 1677 total. Separate native
PostgreSQL sync/probe/budget jobs also passed. The initial evidence is retained.

Further owned regressions reproduce lost day coverage: a valid calendar was
labelled rejected and all its fixtures erased when the archive was missing,
corrupt or lacked the exact calendar packet. A per-fixture OSError also aborted
the entire day. A malformed top-level price container lacked an explicit gate.

The follow-up separates calendar and archive status. A structurally valid
calendar remains visible in full even when archive QC fails. Every fixture
receives PASS and the archive blocker; the model ledger is not opened for rejected
global inputs. A per-fixture I/O error blocks that fixture and preserves the rest
of the report. Invalid calendar evidence still rejects the calendar itself.
`fixture_counts` records calendar/reported/prematch/excluded counts. Unknown
calendar count and unknown future-packet exclusions are null, not invented zero.

Eight additional regressions cover three-fixture retention (including a postponed
fixture), missing/corrupt/wrong archive, isolated I/O failure, malformed prices,
empty provider day and genuinely changed future result scores. The latter changes
historical goals in a later receipt and proves that the earlier sporting inputs
and market rows remain identical. These tests never alter original fixtures.
Red/green and final release evidence: [day-coverage](evidence/c1/day-coverage/).

Reproduce the checked-in **synthetic three-fixture** day without a ledger:

```sh
python scripts/daily_prematch_scanner.py \
  --calendar examples/daily_scanner_synthetic/MULTI_DAY_CALENDAR.json \
  --archive examples/daily_scanner_synthetic/day-coverage-archive \
  --day 2030-01-01 --at 2030-01-01T09:00:00+00:00 --profile LOWER --synthetic
```

The output equals [MULTI_DAY_REPORT.json](../examples/daily_scanner_synthetic/MULTI_DAY_REPORT.json).
The [missing-archive report](../examples/daily_scanner_synthetic/MULTI_DAY_ARCHIVE_MISSING.json)
retains the same three fixtures with explicit PASS, rejected archive, unknown
excluded-future count and zero monetary permission. No P0 proof gate is relaxed.
The original single-fixture report is regenerated for the new scanner digest;
its calendar, original ledger and source fixtures remain unchanged.

Final follow-up local release on Python **3.14.3**: **1676 passed / 9 skipped /
1685 total**, exit 0; integrity/replay true, all 30 scanner regressions passed.
Source hashes and retained pre-fix failures: [validation.json](evidence/c1/day-coverage/validation.json).
Exact new-head CI must be checked after publication; earlier green CI belongs
to `449cfbcc`, not automatically to this follow-up.
