# P0-B / Issue #69: bounded research and uncertain retry

Observed 15 October 2026 at 14:46:31 UTC, by read-only connected SQL:
five provider attempts today, all SUCCESS and finished. Budget disabled,
reason QUOTA_STOP, remaining_day=reserve_day=5, minute_limit=1, no in-flight
permit and no active queue job. Seven completed sports_probe jobs have
attempts=1: two earlier probes failed inside their result without provider
reservation; DONE at queue level alone does not prove API success.

The five admitted requests were status, league 3 fixtures, league 848 fixtures,
team 80 last 10 and team 52 last 10. Existing receipts contain HTTP 200,
timestamps and quota headers. Four fixture projections contain 56 unique
fixture IDs. They are bounded samples, not full-league calibration data.
The last observed provider daily remainder was 7496 at 09:13 UTC, not a
current quota. The private guard's remaining_day=5 means reserved allowance,
not remaining subscription capacity. No budget activation/provider request
was made in this stage.

## Confirmed retry defect and candidate fix

The deployed claim function selects PENDING jobs or RUNNING leases older than
three minutes, at most three attempts. The previous Python worker always
executed a sports_probe again after reclaim. A crash after provider success
but before durable completion could therefore spend quota twice. A synthetic
lost-completion/reclaim counterexample reproduced this; four new tests had
nine assertion failures including subtests on the previous implementation.

The worker now requires an integer first-attempt lease for sports_probe.
Unknown/invalid leases produce PROVIDER_FETCH_LEASE_REQUIRED. Attempts 2/3
produce PROVIDER_FETCH_RETRY_REQUIRES_REVIEW and acknowledge failure without
calling the provider. The first attempt retains the original result/receipt
unchanged. Other job types and the existing situation lease protocol remain
unchanged. Read-only mode still claims no jobs. These changes are candidate
code only, not a deployment or hosted SQL modification.

This is a conservative refusal to refetch an uncertain operation. It does not
recover a receipt lost before completion and does not claim exactly-once
provider execution. Automatic step resume needs a separately reviewed durable
step/result protocol, lease ownership at completion and deployment. A reclaimed
job must not be copied into a fresh job merely to bypass this refusal.

## Existing protections reused

- Database reserve happens under a row lock before I/O; an unfinished permit
  stops subsequent admission. Finish clamps observed quota downward and never
  refunds an uncertain attempt. Daily reserve, UTC day, expiry and minute spacing
  remain enforced by the existing shared guard. No guard is weakened here.
- Unified probe already requires the shared gateway, saves a bounded sanitized
  canonical source packet with hash and stops the batch at the first error.
  The live operational branch's morning projections lack these original packets;
  do not reconstruct or certify originals from compact rows.
- The transport accepts only the existing allowlisted SHARED_BUDGET_* error
  envelope and keeps HTTP auth/access/rate failures distinct from provider data.
  The stored terminal state QUOTA_STOP and a later reserve denial PAUSED are
  different observations: reserve currently reports PAUSED whenever disabled.
  Display stored budget reason separately; do not relabel PAUSED as a fresh
  provider quota/auth failure or claim QUOTA_STOP is already an SDK enum.

PR #71's bounded administrator procedure exists on the separate operational
branch. A names/permissions-only SQL read at 14:57:20 UTC confirms the hosted
private arm_research_budget(integer,integer) function exists, is SECURITY
INVOKER, has an empty search_path and grants EXECUTE only to postgres. It was
not invoked. The reviewed PR #71 procedure counts all recorded attempts toward
a five-attempt UTC daily ceiling: today's five successful calls exhaust that
operator allowance. Do not reset attempt history or raise the cap to continue.
Its inclusion/deployment is not inferred from the unified candidate.
Before another separately authorized window: review the exact hosted procedure,
check for foreign jobs and unfinished permits, verify worker/supported runtime,
bind a small request plan, first status then one request per minute, never reset
an unresolved permit, stop on the first error/unknown quota, close the window and
verify attempts and archived original receipts. Do not call reserve/finish as
a diagnostic test. No activation or migration is authorized by this document.

State: engineering guard fixed and tested; operational replay/archive recovery
remains PARTIAL until the reviewed code/protocol is deployed and an explicitly
authorized bounded session proves it. API access was successful in the recorded
morning session; current internal admission is closed. PASS/stake=0.
