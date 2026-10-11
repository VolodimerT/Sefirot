# SEFIROT — AI handoff / recovery protocol v1.0

**After a frozen chat, missing reply or tool error:** trust GitHub branches, PR exact-head checks and original receipts — not chat memory.

## Stable boundaries

- Roadmap: https://github.com/VolodimerT/Sefirot/issues/33
- Base Chat Bridge: PR #22, branch feature/chat-sefirot-bridge-20261010.
- Situation bridge is an independent draft PR #32, NOT merged into #22 or main.
- Daily autosave is a separate draft branch based on PR #22; do not imply deployed integration.
- Original CORE, Policy, historical seals, model hashes, ledger, PASS/BET decisions and money permissions are untouched.
- No LIVE wagers, dogon, paid API, credentials bypass, bookmaker execution or automatic merge to main.
- No fabricated CORE execution. Unverified data must say SEFIROT_NOT_EXECUTED or REPORTED_UNVERIFIED.

## Every development session

1. Read issue #33, open draft PR heads, exact head SHA and branch ancestry. Main is not development head.
2. Read this file and docs/DAILY_AUTOSAVE.md. Select ONE scope, inspect source and tests.
3. Commit only to a feature branch. Verify remote state after any timeout BEFORE retrying a write.
4. Read back changed files and commit. Run tests and inspect 4-job CI for the exact SHA.
5. Report accomplished changes, blockers and a single next action; never claim unverified CI or real-model edge.

## Every final daily betting report (Europe/Kyiv)

1. Finish exactly one day report: separate CORE BET/PASS from research, Parik24 tickets from Stake/Yaryi proposals, PENDING/VOID/CASHOUT and unreconciled balances.
2. Call the private daily autosave finalizer in docs/DAILY_AUTOSAVE.md. Verify returned saved=true, SHA256 and path. If no tool/backend is connected to the chat, state NOT_SAVED.
3. Never send personal tickets, balances, screenshots, secrets or private provider receipts to the PUBLIC repository.
4. Corrections create additional immutable versions; keep old versions. Auditing remains one final daily audit, not multiple contradictory summaries.

## Checkpoint format for PR comment or new chat

    date_kyiv: YYYY-MM-DD
    issue: #33
    task: <one concrete task>
    base_branch: <exact>
    head_branch: <exact>
    head_sha: <verified 40 hex or UNKNOWN>
    draft_pr: <number or NONE>
    tests: <actual command + result / NOT_RUN>
    ci_exact_head: <runs + status / NOT_VERIFIED>
    core_identity_changed: false | UNKNOWN
    real_source_status: <checked evidence / UNKNOWN>
    daily_report_archive: <private acknowledged sha256 / NOT_SAVED>
    blockers: <facts only>
    next_action: <one explicit action>

Recovery: read branch and remote diff FIRST; a handoff note is navigation, not evidence of a passing test, sports-data validity or model profitability.
