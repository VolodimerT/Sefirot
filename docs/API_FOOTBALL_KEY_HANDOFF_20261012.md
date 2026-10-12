# SEFIROT — API-Football credential handoff, 2026-10-12

The user supplied a credential privately in a chat. **Never record its bytes in Git, GitHub Issues/PRs, ChatGPT Library artifact content, build logs, stdout, HTTP URLs, test snapshots, or public docs.** This document contains no credential.

## What the project already had
- `API_FOOTBALL_KEY` is read at runtime from an environment variable or a local untracked `.env` file by `src/sefirot/credentials.py`.
- Direct sports-only provider: `GET https://v3.football.api-sports.io/status` using `x-apisports-key` request **header**; no odds.
- The previous 2026-10-06 server-side observation was `PROVIDER_ACCOUNT_SUSPENDED`; that does not establish the present status of a newly provided credential.
- The full `api-health` command may additionally check an odds provider; do not use it for the initial single-request authentication test.

## Safe one-shot verification
For an authorized runtime that has egress to API-Sports, set `API_FOOTBALL_KEY` via a **server-side secret/environment variable**, never hardcode it and never add it to the repository. Then run manually:

```sh
python scripts/api_football_status_once.py --confirm-single-request
```

The script requires the explicit flag and makes at most **one** GET `/status` request (no retries). It emits a whitelisted minimal status envelope only: active/inactive, request counters and fixed diagnostics. It never prints a credential, raw provider response, account identifier, or original HTTP error text. A key being syntactically configured **does not prove it works**.

Do not enable background cron, provider collection, premium plan, API-key rotation, or batch fixtures. A response `SUBSCRIPTION_ACTIVE` establishes provider account reachability only, **not** coverage of a given season, complete league archive, bookmaker prices, real-data integrity, reliable predictions, or monetary admission. A non-active or failed response is `PASS`/STOP for data acquisition.

### Additional gates before activating a collector
1. Verify original plan, `requests_limit_day`, live `requests_current` and rate-limit headers, quota policy and valid subscription with the provider dashboard. Do not attempt account-ban circumvention.
2. Require one named service/runner as the sole credential owner. The connected Render workspace has numerous historical `sefirot-*` scan services; **do not install the secret into one without operator selection** because a restart may cause uncontrolled requests.
3. Enforce shared cross-process budget, bounded egress endpoint allowlist, request preflight and circuit breaker for 403/suspension/429/quota; prevent retry storms. Do not auto-retry.
4. After a successful `/status` and user approval, retrieve **one bounded fixture** from an explicitly permitted current competition. Store only sanitized provenance/hash receipt, not secret or personal account details.
5. Keep provider fixtures separate from independently verified bookmaker prices and forward calibration. Missing observations => `PASS`; no invented probabilities or quote availability.

## Honest execution boundary for this handoff
This environment's shell egress has DNS unavailable. The connected GitHub action has no secrets-write interface, and existing Render services do not present a single controlled canonical collector. Therefore **no authenticated live request was executed** and **no new key was installed**; validation is pending execution from an authorized networked runtime. Offline CI validates the one-shot probe structure, not the credential's actual access.
