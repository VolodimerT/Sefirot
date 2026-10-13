# V4.3 original-row read-only risk audit

Base: exact PR #39 head `17a6c2a6b95cdb7350bb77b823db8e1691bf742c`.
Scope: explicit offline script and real SQLite integration tests. No production
deployment, main merge, provider calls, key changes or monetary approval.

## Run on a private original SQLite snapshot

```bash
python scripts/risk_ledger_audit.py --db /private/original.sqlite --as-of 2026-10-12T09:15:00+00:00
```

Uses the canonical `Repository(..., read_only=True)` and real `Service.context`
with each prediction's sealed historical Policy. A deferred read transaction
keeps all reads in one snapshot. The script does not create a missing database,
bootstrap tables, mutate originals, replay forecasts on changed code, or write
results/approvals. Output contains aggregates and a content digest; private
identifiers, payloads, bookmakers, paths and exception messages are omitted.

Checks immutable journal record bindings, SQL-column/payload identity and time,
seal -> decision -> placement < kickoff, kickoff < finish <= receipt, positive
stake and group shape. Actual Service reconstructs exposures at the requested
cutoff: a result received later cannot settle an earlier exposure. The legacy
risk day stays UTC. No Kyiv/bookmaker-day migration is inferred from reporting.

## Evidence boundaries

- `JOURNAL_INVALID`, `CHRONOLOGY_INVALID`, `RECORD_SHAPE_REJECTED` are failures.
- `INSUFFICIENT_SETTLEMENT_RECORDS` means no visible original bet/result pair.
  Zero records is not successful validation of bookmaker settlement.
- `INTERNAL_CHRONOLOGY_CHECKED` checks internal original rows, not authenticity
  of an external provider/bookmaker, empirical EV or authority to place bets.
- Source attestation stays `NOT_ESTABLISHED`; monetary permission is always
  false. Synthetic fixtures are explicitly counted, never labelled real.
- CLI exit 0 indicates a completed read, not closed V43-01 acceptance. Exit 2
  denotes rejected input or a failed integrity/chronology check.
- Restore an original snapshot through an authorized read route, verify its
  compressed checksum separately, and keep the private snapshot and receipt
  outside Git. This script does not contact a cloud service or assert that a
  caller-supplied database is the latest production version.

## Validation

Twelve adversarial tests use actual SQLite Repository and Service, without stub
repositories: full synthetic capture/decision/external execution/result;
missing/empty database; open exposure; delayed result; future capture cutoff;
malformed but content-bound result; negative stake; valid JSON/hash with
tampered SQL timestamp; corrupt journal; unchanged file bytes; redacted output.
These prove engineering behavior, not independent sporting calibration.

All `src/sefirot` files and historical reports remain byte-identical to #39.
Original `MODEL_MODULES`, Policy, seals and risk coefficients are unchanged.
Run `python test_sefirot.py` and `python scripts/verify_release.py`; require
four Ubuntu/Windows x Python 3.11/3.13 CI jobs on the exact published head.

V43-01 still requires original settlement-bearing records and independent
external receipt attestation. V43-02 risk-day choice, V43-03 fresh holdout,
verified quote profiles and the unexplained accounting balance remain separate
tasks; this diagnostic does not fabricate their missing inputs.
