# Shared API-Football budget candidate — issue #29

Different sessions previously enforced separate local request budgets. This
candidate routes every authenticated sports-gateway provider attempt through
one PostgreSQL reservation before provider I/O. CORE, Policy, seals and the
private Vault secret/RPC are unchanged. No production migration, deploy,
provider request, or fit is performed by this change.

## Guarantees and limits

- One fixed project-wide budget row, independent of runner token or Edge isolate.
  `SELECT ... FOR UPDATE` serializes reservation and completion transactions.
- Each permitted attempt immediately spends one daily token and gets an internal
  UUID. The daily reserve is retained. Unknown outcomes never refund a token.
- At most one provider call is outstanding. Other callers receive fixed HTTP 429
  `SHARED_BUDGET_STOP`; no waiting, retry, or automatic half-open probe occurs.
- Rolling 60-second attempts and minimum spacing constrain the configured minute
  cap. Spacing also starts after completion, avoiding delayed-arrival bursts.
- Provider errors, HTTP failure (including 403/429), invalid packets, timeout,
  inactive status, absent/invalid quota or failed completion stop subsequent calls.
  Completion failure leaves an outstanding reservation. After 30 seconds it
  latches the circuit instead of releasing capacity to another caller.
- Late success cannot reopen an already latched circuit. A repeated or wrong
  permit cannot change counters. Provider observations only LOWER the shared
  daily remainder and minute cap. Inconsistent counters stop collection. A success cannot silently renew the operator's approval.
- UTC rollover, expired approval, missing approval and approval more than 15
  minutes ahead fail closed. New day never restores an assumed Pro allowance.
- No provider key, token, account identity, fixture ID, raw error or request params
  are stored in the budget tables or passed to these RPCs.

This covers runners using THIS gateway and database. Legacy direct-provider
runners, dashboard requests and other projects cannot be reserved atomically by
this database. They must be stopped or routed through the gateway before any
claim of account-wide protection. This PR does not modify Render startup jobs.

## Deployment and recovery procedure (not executed)

1. Stop collection and all direct-provider boot/deploy fetches. Confirm no
   provider requests are still running. Export existing gateway source/auth
   configuration privately for rollback; do not copy secrets into Git.
2. Apply `server/migrations/20261012_shared_sports_budget.sql` once. It creates a
   dedicated private schema, RLS-enabled tables and two service-role-only,
   SECURITY INVOKER RPCs with empty search_path. It starts **PAUSED**. The existing
   `sefirot_api_football_secret()` and Vault UUID/name/value are not altered.
3. Deploy the candidate gateway preserving existing private auth hashes. Missing
   RPC or paused state prevents provider I/O. Test only denied paths first.
4. A trusted operator may arm one explicitly authorized `/status` probe with a
   conservative budget of **one spendable attempt**, a retained daily reserve,
   minute_limit=1, correct UTC day and valid_until no more than 15 minutes ahead.
   Wait at least 60 seconds after stopping other consumers. This is a manual
   recovery authorization, not evidence that subscription or quota is active.
   The status request still counts as one provider attempt and requires normal
   runner authentication; the migration itself never calls it.
5. Before a bounded cohort, independently verify the new original status receipt:
   active subscription, observed day AND minute counters and permission to use
   that season/league. Do not infer limits from plan name. Under a row lock, with
   no in_flight permit and no old provider request outstanding, set remaining_day
   no higher than the observed remainder; minute_limit no higher than the
   observed provider limit (candidate cap 300); reserve_day at least 1; explicit
   UTC day and expiry. Set minute_ready_at at least 60 seconds after the last
   external request. Preserve attempts/last_started_at during same-day recovery.
   Do not reset failed attempts based only on elapsed lease time.
6. Run only the preregistered bounded collection. New expiry/quota/day/restriction
   needs explicit operator review. No collector startup or service restart arms
   or renews this budget. No monetary admission follows from a permitted request.

Re-arm writes are deliberately not exposed as browser/user RPCs. They are a
privileged operational action based on independently verified evidence. The
15-minute approval is a collection authorization window, not a subscription
freshness proof. A successful single fixture is not a full-league manifest.

Rollback: first disable the budget and stop callers, preserving outstanding
attempts for reconciliation. Restoring the previous gateway would remove this
protection: keep collection stopped until another equivalent guard exists.
Keep the private audit tables rather than dropping them. No rollback script
silently resumes unguarded API calls.

## Verification

`node scripts/test_sports_gateway.mjs` runs the actual gateway handler against
25 offline contract groups: old auth/redaction/transport cases plus reservation
refusals, malformed RPCs, uncertain outcomes, observed quota and failed finish.
`python scripts/verify_release.py` covers the existing Python aggregate and
synthetic replay/integrity; generated historical report bytes are restored.

`python scripts/test_shared_sports_budget.py` requires explicit
SEFIROT_TEST_POSTGRES_URL, localhost and database name `sefirot_budget_test`.
It applies the ACTUAL SQL in this isolated database, checks denied role access,
16 simultaneous processes reserving the last spendable token, duplicate/wrong
completion, lower-only counter update, failure/zero quota, stale lease with
late success, UTC expiry, spacing/rolling minute window and recovery cooldown.
It never contacts API-Football. It destroys only its named local test schema.
The separate `shared-provider-budget` CI job uses PostgreSQL 16; the existing
four OS/Python jobs remain required. Real deployed DB and operational routing
of all runners are still unverified.

References: [Supabase database functions](https://supabase.com/docs/guides/database/functions),
[issue #29](https://github.com/VolodimerT/Sefirot/issues/29).
