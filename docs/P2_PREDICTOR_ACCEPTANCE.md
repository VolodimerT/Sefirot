# December Quest predictor concurrency acceptance

The staging migration adds one lease per model and Kyiv operating cycle. Claim occurs before calendar access, provider calls and normalization. Other invocations receive HTTP 202 RUN_IN_PROGRESS with Retry-After. On a recent successful cycle the original skip rule applies. A detected failure releases the matching token. A crash or a lost claim reply leaves a recoverable lease for at most ten minutes, the existing maximum age of a commit. A later invocation can take over. The database does not schedule that invocation. A caller requiring completion must revisit a 202 and retry a transient 503 while a valid prematch window remains.

Only short SQL transactions hold locks. Claim uses the existing advisory key without waiting. Finish takes that key before deleting the lease, checks its owner, start and expiry, and calls the original batch persistence function in the same transaction. SQL lock waits are bounded at five seconds. Release deletes only the supplied token. A lost commit response is safe to retry. Achieving exactly one external request across a crash after transmission is impossible without cooperation from the source. A takeover can refetch an uncommitted batch. Paper, SHADOW and the user journal are outside this lease.

## Reproduce on Linux

Use Node 24, Deno 2.5.6 and Python 3.11 or later. The optional native benchmark packages live in a temporary directory. The harness creates and removes its own PostgreSQL cluster, binds its database to loopback port 18473, and starts a temporary HTTP adapter and CSV source. It accepts no external database URL. Run the revisions consecutively on the same machine.

```bash
git worktree add --detach /tmp/dq-p2-base e2762b78eea6aecfc48410dc3061e60c77fc1d72
cd december-quest-site/autonomous
npm ci --ignore-scripts
npm test
npm run test:acceptance
npm run test:edge
deps=$(mktemp -d)
npm install --ignore-scripts --no-audit --prefix "$deps" embedded-postgres@19.0.0-beta.20 pg@8.23.1
NODE_PATH="$deps/node_modules" node test/cycle-load.mjs /tmp/dq-p2-base/december-quest-site/autonomous --baseline
NODE_PATH="$deps/node_modules" node test/cycle-load.mjs
```

The barrier starts 2, 5, 10 or 20 independent processes with a common clock. The source delays each response by 400 ms for the contention test. CSV counts are incoming HTTP requests at the server. REST counts include state or claim, calendar, pending snapshots when settling, and commit. Authentication is covered separately by the Deno HTTP suite. Timings include transport, SQL, parsing, normalization, modeling, validation and persistence from worker release until response. Aggregate RSS samples sum the Linux RSS of live workers every 25 ms, including shared pages per process. The separate process high-water measurement covers a worker's lifetime. Neither includes the database or adapter. REST handler time sums concurrent request durations and includes receiving/decoding the body and waiting for SQL.

The full-cycle test seeds 26 teams and two seasons, runs the predictor, advances the database clock, supplies FT scores and settles the actual saved snapshots. Cross-revision SHA-256 includes all seal content except database-generated row IDs. Within a run every saved column, including IDs, is checked before and after settlement. At 301 fixtures the runner must reject the batch before requesting CSV. The current 300 limit also matches the pending-snapshots SQL guard. Raising only one side can silently leave settlements pending. A higher limit needs pagination, an Edge memory budget and independent timing evidence.

## Policy evidence

| Published v21.2 rule | Evidence and boundary |
|---|---|
| Prematch only | Kickoff and source-cutoff regressions, SQL write guards and historical walk-forward chronology. |
| EV and independent probability | Unknown probability or unverified price blocks an actionable EV. Net EV includes the tip price. |
| Two or three independent express legs | Manual seal validation accepts 2/3 and rejects 1/4 in express mode, same-event legs and unreviewed independence. |
| Big markets first | Market priority is published guidance. The manual seal validator does not require evidence of a ranking. |
| Small markets only with stronger evidence | A read-only manual-validator probe accepted a two-leg example containing fouls without comparative evidence on both base and candidate. |
| Fouls and cards | Distinct market labels. Card restrictions operate on the card market. |
| Referee gate | Missing referee, rates, low-card check, rules or cleaner-market review blocks a card seal. Positive net EV is required. |
| Death-test | Card readiness records a counterargument. The manual seal validator accepted the same synthetic express without a recorded death-test on both revisions. |
| Data integrity | Immutable SQL snapshots, stale-token rejection and replay at a fixed cutoff. |
| PASS | A reasoned PASS is valid; Paper returns zero eligible legs and zero stake when the full gate is unverified. |

These checks support compatibility with existing behavior. The two manual examples prevent a full v21.2 enforcement sign-off. They were evaluated in memory. Independent acceptance should decide how the manual and automatic contracts are intended to relate.

## Staged rollout and rollback

Before any approved switch, drain older December Quest workers, stage single-flight.sql after persist.sql, and switch all December Quest workers together. A legacy worker still calls the original RPC and does not participate in the new lease. Monitor 202, retries, expiry, saved forecasts and pending FT rows in staging. This draft does not deploy the function, schedule a retry or apply a hosted migration.

Before merge, close the draft to discard it. After a staged installation, drain P2 workers, restore the #87 runner and preserve the original persistence tables and RPCs. The additive lease schema can remain idle. If removal is desired after draining, use the following isolated rollback transaction. No forecast, seal, settlement or user-journal table is included.

```sql
begin;
drop function public.dq_finish_predictor_run(uuid,jsonb,jsonb,jsonb,jsonb);
drop function public.dq_release_predictor_run(uuid);
drop function public.dq_claim_predictor_run(text);
drop table public.dq_predictor_leases;
commit;
```
