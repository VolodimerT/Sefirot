# Research-only API-Football budget operator

The protected Supabase gateway can make API-Football calls **only** after the shared PostgreSQL budget issues a reservation. A `PAUSED` state intentionally blocks every upstream call. This is separate from the provider's subscription and not a broken API key.

## Deployment

Apply `supabase/migrations/20261015_research_api_budget_operator.sql` as a database migration. The migration is **inert**: it does not unpause the quota, change credentials or send any HTTP requests. The function is in a private schema, SECURITY INVOKER, restricted to `postgres`, and is not exposed to `anon`, `authenticated`, or `service_role`.

## Enable a single bounded window

After explicitly verifying today's authorized maximum and available provider subscription quota, execute in **Supabase SQL Editor**, as the `postgres` administrator:

```sql
SELECT sefirot_budget_private.arm_research_budget(5, 12);
```

The function permits **at most 5** provider attempts (counting other calls recorded today), **at most 1/minute**, and keeps the existing **5-request untouched reserve**. The permit automatically becomes unusable after **12 minutes**: the budget reservation procedure fails closed with `STALE_BUDGET`. The `enabled` column is not automatically toggled back to false; *effective access is denied* after expiry.

The first query should be `status`, checking whether the actual upstream subscription is active and remaining quota exceeds the reserve. Unknown quota headers or upstream failures cause the circuit to close; they are not proof of quota availability.

No wagers, bookmaker API access or monetary permission are enabled by this function.

## Verify the diagnostic

The chat queue worker must be running. Enqueue a bounded read-only `sports_probe` using its normal authenticated queue; when the budget is not armed, an actual probe response must report `SHARED_BUDGET_PAUSED` or another explicit fixed denial reason, **not** `PROVIDER_TRANSPORT_OR_AUTH_UNAVAILABLE`.

To inspect effective quota manually in SQL Editor:

```sql
SELECT enabled, reason, remaining_day, reserve_day, minute_limit, valid_until
FROM sefirot_budget_private.sports_budget;
```

Never add the real API-Football key, runner token, or Supabase service-role key to GitHub issues or CI logs.
