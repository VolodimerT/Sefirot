# SEFIROT — daily report autosave, private append-only v1

Daily autosave is a *finalization operation*, not a model forecast, bet recommendation or ChatGPT background watcher.

## Paths and commands

Existing reported single-day ticket audit input can be audited AND saved with a single command:

    python scripts/daily_autosave.py --ticket-input path/to/tickets.json

For daily chat reports, create a JSON file with these exact fields (the example is synthetic):

    {
      "schema": "sefirot-daily-report-v1",
      "day": "2030-02-01",
      "timezone": "Europe/Kyiv",
      "origin": "CHAT_DAILY",
      "status": "REPORTED_UNVERIFIED",
      "source_refs": [],
      "report": "Synthetic daily recap. CORE SEFIROT_NOT_EXECUTED. PASS."
    }

Then run:

    python scripts/daily_autosave.py --report path/to/final-day-report.json
    python scripts/daily_autosave.py --verify

Option --store /private/path overrides the default ~/.sefirot/private-daily-reports. The existing sefirot ticket-audit command remains unchanged, with no silent write. Use the dedicated script for any report requiring automatic archiving as part of the command.

When finalization succeeds it prints saved=true, sha256, dated private path, new_version and versions_for_day. An error exits nonzero with DAILY_AUTOSAVE_FAILED; NEVER tell the user a report was saved unless this succeeds.

## Guarantees and limits

- One Kyiv calendar day per audit. Canonical UTF-8 JSON is saved at <store>/<YYYY-MM-DD>/<sha256>.json using a flushed temporary file and atomic rename.
- OS advisory file lock prevents concurrent writes and releases if the process crashes.
- Same report replay is idempotent: new_version=false. Corrections produce new content-addressed versions and preserve originals.
- latest.json is an atomic convenience pointer; all older snapshots remain. --verify recomputes each stored SHA256 and confirms the latest pointer. If a crash interrupted pointer creation, recover from the dated archive and repair explicitly.
- Status is always REPORTED_UNVERIFIED: preserved screenshots, coupon outcomes and model performance are NOT certified. This tool cannot authorize wagers or certify CORE BET.
- Public GitHub is NOT a backup destination for private reports, bank balances or receipt images; it stores only code, tests and public handoff instructions.
- Storage is LOCAL to the machine running the script. This does NOT enable automatic copying from mobile ChatGPT conversations, remote Supabase, GitHub or any cloud. A private, authenticated chat report adapter is needed for hands-free saving from ChatGPT. Until an acknowledged private write happens, say NOT_SAVED.
- No merging main, deployment, paid API, security token, external provider request or modification to original CORE in this PR.

Daily audit source separation, bankroll reconciliation and point-in-time CORE identity follow Issue #33.
