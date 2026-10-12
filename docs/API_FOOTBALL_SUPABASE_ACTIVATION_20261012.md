# SEFIROT API-Football: production handoff (2026-10-12)

**Real status:** AUTH_UNVERIFIED / NO_NEW_KEY_INSTALLED / MONETARY_PERMISSION=false.
The user has provided an API-Football credential in a private ChatGPT message. **Never copy its value to repository content, issues, actions logs, SQL statements, public URLs, Edge Function source or status receipts.** Do not ask for it to be pasted into chat again.

## Verified owner infrastructure

- Existing Supabase project `sefirot-core`, project ref `kxqpwgwihtjmqlcxgfxp`, ACTIVE_HEALTHY.
- Existing Edge Function `sefirot-sports-gateway`, ACTIVE, version 11, `verify_jwt=false`, with a custom SHA256 runner-token authentication gate. Preserve this gate unchanged.
- Current gateway `apiKey()` invokes server-side private Postgres RPC `sefirot_api_football_secret`. Merely setting `API_FOOTBALL_KEY` under Edge Function Secrets **will not work with version 11**, because it does not read that environment variable.
- Existing Python `src/sefirot/football_gateway.py` supports the Supabase gateway using `SEFIROT_SPORTS_GATEWAY_URL` and `SEFIROT_SPORTS_GATEWAY_TOKEN`; it verifies provider host, receipt chronology and quota.
- Earlier 2026-10-06 suspension referred to then-current account state. It does **not** prove the new credential is suspended or active.
- Render workspace already has 25/25 services; trying to create an isolated free one returned `Hobby Tier is limited to 25 services`. No new service was created or modified.

## Secret-safe completion route

### Preferred: keep the version 11 gateway unchanged
Owner/admin uses Supabase Dashboard > `sefirot-core` > Database/Vault to identify and update the **existing credential backing the RPC `sefirot_api_football_secret`**. Never guess the secret name or create a second shadow secret without verifying the function's actual mapping. Changing the secret is an explicitly authorized owner operation and must happen in the encrypted/dashboard interface, not from assistant-generated SQL.

After updating, call **one** authenticated `POST /functions/v1/sefirot-sports-gateway` from the already authorized private SEFIROT runner, with JSON `{"endpoint":"status","params":{}}`. The existing runner-token header is required; keep its value private. Check subscription.active, daily request counters, quota headers, and redact account/user fields. No batch, no automatic retries.

### Alternative: new Edge Function Secrets workflow
Before using an Edge Function secret, *first* update gateway code's `apiKey()` to read a validated `Deno.env.get("API_FOOTBALL_KEY")`, falling back to the original DB RPC **only when absent**. Keep the original authorization allowlist/hash, egress host, quota validation and HTTP error classification. A present malformed value must fail closed rather than falling back.

Do not deploy this source change unless a properly permitted actor can read/test/deploy/verify the entire original function. The assistant attempted a narrow guarded deployment through the connected Supabase tool but the platform's safety enforcement blocked it. **No deployment occurred.** Owner can instead use Supabase Dashboard > Edge Functions > Secrets to store `API_FOOTBALL_KEY` after the gateway supports reading it. Do not place the key in source code.

## One-shot validation without the Supabase gateway
The reviewed draft PR #40 provides `python scripts/api_football_status_once.py --confirm-single-request` and eight isolated tests. Use it on an authorized networked runner after setting private `API_FOOTBALL_KEY`. Both push and PR exact-head CI completed 4/4 platforms. These CI runs use mocks and cannot establish live auth.

## Success criteria (not yet met)
1. User-provided credential stored in private secret channel, without logging or echoing it.
2. One live /status response with subscription active and recorded bounded quota counters, no HTTP 200 application-level error.
3. One explicitly approved prematch fixture request with correct receipt identity, coverage and season access checks, global budget fail-closed.
4. Independent bookmaker quote/market data and fresh chronological calibration remain independent work; no PASS→BET manual promotion.

**Important:** The connected Supabase tool set does not provide the dedicated dashboard secret elicitation/create-secret action, and a secure write attempt was blocked by platform enforcement. The user must perform the actual secret entry via the Supabase UI. No tool action may bypass that restriction.
