# December Quest V6.3

The December calendar covers 1–31 December 2026 and kickoffs from 21:00 to 23:00 Europe/Kyiv. The site shows the latest automated forecasts, PASS evidence, prospective seals, and published scorecards. The site is read-only for the autonomous workflow.

## Daily operation

- 18:30 Kyiv · the existing calendar task checks upcoming official fixtures. It advances `checked_at` only when the source confirms the match and time.
- 19:00 Kyiv · Supabase job `dq-autonomous-dec2026-19kyiv` dispatches to `dq-autonomous-predictor-v63`. The entrypoint authenticates its caller via the existing Vault-backed RPC.
- 19:30 Kyiv · the existing monitor checks the forecast run and reports significant failures, coverage deterioration, and integrity violations.
- FT is reconciled against available Football-Data results. The automated scorecard uses the latest qualifying pre-kickoff snapshot, preserving all earlier snapshots.
- 3 December at 10:00 Kyiv · the one-time prospective QA verifies the Coventry–Ipswich full-time result and production scorecard.

A run before 19:00 belongs to the preceding operating day. The next 19:00 run opens a fresh cycle. The Edge worker retries a transient CSV error once. The database atomically commits forecasts, seals, run metrics and eligible settlements. If the source stays down, the run records an error and retains the PASS gate.

## Freeze scope

- Model `DQ-POISSON-0.3`, five domestic leagues, 68 modeled market outcomes per covered fixture, completed results strictly before the UTC cutoff date.
- The live database enforces verdict `пропуск`. The CSV can carry indicative odds. A verified quote timestamp, tactical, lineup and risk evidence are required before a future change could enable a stronger verdict.
- The application does not form autonomous accumulators or execute bets. The manual analysis gate checks duplicate fixtures and requires independence review for more than one leg.
- The live deployment smoke on 24 November processed 114 fixtures with 60 modeled, 98 seals and 114 PASS. Its rerun returned `RECENT_SUCCESS_IN_CYCLE` without adding rows. Coventry–Ipswich production snapshot 183 was stored 24 November at 21:42:26 Kyiv.
- The first scheduled V6.3 cycle and the first real FT remain separate production acceptance checks. Model and decision policy changes during December require separate authorization.

## Rollback

The earlier working Vercel deployment is `dpl_97FWj4zCKVPQWJ9xjh7wZkKPpzCC` in project `sefirot-december-quest-2026`. Use the project's Instant Rollback to that deployment if the V6.3 interface fails.

The prior backend remains `dq-autonomous-predictor-v2`. To roll back the scheduler, retarget the existing job while keeping its schedule and Vault headers:

```sql
select cron.alter_job(
  j.jobid,
  command := replace(j.command,
    '/functions/v1/dq-autonomous-predictor-v63',
    '/functions/v1/dq-autonomous-predictor-v2')
)
from cron.job j
where j.jobname='dq-autonomous-dec2026-19kyiv'
  and j.active and j.schedule='0 17 * * *'
  and substring(j.command from 'functions/v1/[a-zA-Z0-9_-]+')
      ='functions/v1/dq-autonomous-predictor-v63';
```

Verify the job target and public alias after rollback. Keep the additive migration in place so historical seals, validation and settlement data remain readable. Never print Vault values or the full cron command. Review this release using the source branch head and the deployment ID recorded by the release operator.
