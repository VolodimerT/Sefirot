# SEFIROT chat integration — 10 October 2026

## Implemented

- Original SEFIROT CORE **2.4.2** running in existing free Frankfurt Render service (former strict-double-v2 research runner). Auto deploy off. Startup test verifies original synthetic full cycle/replay/integrity.
- Private REST API and Streamable HTTP MCP gateway, authenticated with a dedicated Render bearer token (never in public Git).
- Private Supabase Edge Function sefirot-chat-store, custom header authentication (hashed token in deployed function), only allowlisted RPCs, JWT disabled only because custom credential authentication is implemented.
- Supabase private schema add-ons: **chat_bridge_snapshots**, **chat_bridge_jobs**, with limited SECURITY DEFINER service_role-only RPCs and no anon/authenticated access. Original 22 canonical cloud tables are unchanged.
- Original Python SQLite research ledger is restored from checked gzip+SHA-256 snapshot on *every* request, and checkpointed with optimistic compare-and-swap after canonical capture/decide/result. A failed checkpoint refuses the response. The initial blank SQLite ledger is persisted at revision 1.
- ChatGPT conversation integration uses existing authenticated Supabase tool: insert private job row, poll for status/result. Render background worker reads via auth Edge function, invokes original Python Service and posts result back. It NEVER places wagers.

## Verified real end-to-end calls

- status job 672da987-ad21-4ac1-8683-69ee8bedea0e: DONE, model 2.4.2, durable storage true, revision 1, ledger integrity true, stored predictions 0.
- demo job fc280451-796f-4e74-9341-fd9a2356e7a0: DONE, synthetic true, replay_matches true, ledger_integrity true. Demo uses temporary synthetic ledger and does not contaminate real history.
- Render startup emitted SEFIROT_CORE_STARTUP_SMOKE_OK, SEFIROT_DURABLE_STORE_VERIFIED revision=1 and SEFIROT_CHAT_JOB_WORKER_STARTED. Deployment dep-db4luvui0phs73d6dt4g LIVE.

## Using from future ChatGPT turns

The connected Supabase tool is a temporary practical transport for research analysis without requiring new plugin installation. Using mcp__Supabase__execute_sql, enqueue only safe research action in sefirot.chat_bridge_jobs (kind: status/demo/capture/decide/result/report; request JSON with original input contract). Query returned id/status/response. Example read-only enqueue:

INSERT INTO sefirot.chat_bridge_jobs (id,kind,request) VALUES (gen_random_uuid(),'status','{}'::jsonb) RETURNING id;

Then SELECT status, response, error FROM sefirot.chat_bridge_jobs WHERE id = <returned UUID>;

Do not confuse that read-only command with a prediction. Valid prospective betting research requires **first** price-blind capture with full verified sports and timestamps **before kickoff**, then separate decide with a bookmaker quote and independent recheck. User screenshots received after kickoff cannot be retroactively sealed.

## Remaining limitations

- The connected API-Football account previously reported PROVIDER_ACCOUNT_SUSPENDED. Reauthorization or authorized alternative historical data source is needed for automatic source-backed future fixture research. Never guess sports histories or backdate timestamps.
- No independent real HOLDOUT of DC_DYNAMIC_V1 / SOS_LITE_V1; shadow only. No certified betting edge. No automated sportsbook execution.
- Free Render may sleep; when queue jobs are pending, the service may need a Render wake/deploy or available inbound call. The worker polls only while running. A full 4-platform CI check for latest branch is still running; verify before promoting code.
- Remote MCP is deployed but not registered as a first-party ChatGPT plugin. The functional *connected Supabase queue* is the verified chat-to-engine path.
- Research queue processing is at-least-once after worker crash, so use original model idempotency and audit duplicate decision IDs; no automatically allowed money exposure.
