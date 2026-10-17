# Recovery of the existing API-Football queue consumer

This stage is explicitly authorized by the owner on 17 October, including
deployment of the existing Render service after configuration verification.
It does not authorize a budget renewal, mass scan, Stake access or main merge.

## Confirmed failure

Job `c38eb7dd-822f-4f94-8fba-cc6b0ec44009` was PENDING/attempts=0. It contains
one `status` query. The installed park revoked service_role EXECUTE on both
`sefirot_chat_claim()` and the fenced `sefirot_probe_complete(...)`. This is a
deliberate safety fence, not a provider-authentication failure. Render's live
3461ef75 worker uses the older unfenced completion, so simply restoring GRANT
would let a request run before its completion is rejected by the new SQL.

The configured `strict_double_20261006_v2.py` already supports an MCP selector
in the deployment branch; historical startup/queue logs verify that path was
used. That selector was missing from the unified tree. Restore the small
launcher before any scanner imports, and use the existing authenticated
chat_mcp/chat_queue/collector/relay; do not create a replacement service.

## Implemented behavior

- `SEFIROT_BRIDGE_MODE=mcp` selects the canonical bridge before legacy scanner
  imports. Existing Render branch/start/build commands remain usable.
- `SEFIROT_BRIDGE_READ_ONLY=1` keeps HTTP/MCP CORE mutations forbidden.
  The separate explicit `SEFIROT_CHAT_JOB_WORKER_MODE=sports_probe` starts only
  the sports research consumer. The consumer calls the existing collector,
  never CORE capture/decide/result or ledger checkpoint. Other kinds are
  rejected with a fixed validation error; inspect pending kinds before resume.
- Only integer attempt1 can fetch. Attempts2/3 complete as review-required
  without provider I/O. An uncertain claim is not retried. Only identical
  fenced completion has one bounded transport retry (no provider repeat).
- One local consumer/process_one at a time; SQL SKIP LOCKED handles leases
  across processes. All provider calls require the existing shared-budget
  gateway. Gateway and relay HTTP timeouts remain15/20seconds; no direct key
  fallback, automatic budget renewal, provider retry or batch scan.
- SIGTERM/SIGINT stops claims and interrupts idle waits, drains the active
  operation for at most25seconds. If Render kills an uncertain attempt, reclaim
  never re-fetches it. Failed result delivery still requires human review.
- Authenticated `GET /status` reports local worker liveness/poll/completion/
  fixed-error status. It performs no provider/SQL request; provider quota stays
  NOT_VERIFIED there. Public `/health` reports sports worker running, read-only
  CORE and Render's commit. A stopped worker returns503. `/v1/status` remains
  canonical ledger status. None is an automatic provider `/status` call.
- The source baseline is c39d2d2 plus these recovery changes. Integrate the
  existing deployment branch6ac583bf as a second Git parent without force.
  Preserve its two inert budget-operator source/document files unchanged;
  do not invoke or apply that old operator migration. All64src/model/Policy
  bytes remain the tested unified baseline.

## Ordered deployment

1. Run new queue/HTTP/resume counterexamples, full isolated release and exact
   GitHub CI, including native PostgreSQL probe and shared-budget concurrency.
2. Confirm Render service `srv-db2f000ae00c73a42sn0`, workspace
   `tea-d85icff7f7vs73ao7shg`, branch `feature/stability-reset-20261005`, start
   `python scripts/strict_double_20261006_v2.py`, build `pip install . flask`,
   autoDeploy=no, one instance. Fresh-compare branch tip and verified SHA.
3. Fast-forward that existing branch to the tested integration commit only.
   Merge only the three non-secret mode flags above into existing environment
   configuration (`replace=false`); retain all credentials untouched.
4. Trigger one normal deploy, record ID, wait for live at the exact SHA. Check
   `/health` worker_mode=sports_probe, running=true, core_read_only=true and
   commit match; startup must verify existing store revision59. Check `/status`
   rejects unauthenticated requests. Do not pull a secret to perform a smoke.
5. Keep SQL parked until the old instance has retired (Render drain60seconds
   plus default shutdown30seconds, verify current documentation/logs). Compare
   old snapshot/finished-row fingerprints and budget before resuming.
6. Apply only `20261017114454_resume_probe_worker.sql`: verify exact existing
   claim/fence/wrapper bodies/ACLs, private schema, no in-flight budget attempt,
   no RUNNING or unsupported/retried PENDING jobs. Grant only existing claim and
   probe completion to service_role. No function body, row, snapshot or budget
   is rewritten. Transaction/drift failure must leave the queue parked.
7. Observe the existing job, its query result and provider reservation history.
   DONE means the worker stored its response; inspect each query's status.
   An expired/closed budget must remain a gateway denial, not a claimed real
   provider `/status` success. No re-enqueue, attempts reset or window renewal.

## Budget and rollback

At11:41UTC, remaining_day15/reserve5, enabled=true/reasonREADY, but valid_until
10:54:27UTC **already expired**. Effective provider access is closed. This
stage will not extend the window. A fresh real provider status/quota needs a
separately approved bounded window; stale saved quota is not current quota.

If verification fails: keep/revoke claim+probe EXECUTE using the existing park
file after its own safety preconditions hold. Stop the sports consumer or
select canonical mode with CORE read-only, preserving all secrets and original
responses. Do not automatically redeploy the old unfenced worker, reset job
attempts, reconstruct missing receipts or refill the budget.

Tests and live evidence are recorded outside Git with exact final commit,
Render deploy ID, job status and hashes. Synthetic tests do not establish
provider subscription/remaining quota, calibrated predictions or profitability.
RESEARCH_ONLY / PASS / stake=0.
