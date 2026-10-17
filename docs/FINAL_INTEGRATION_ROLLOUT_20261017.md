# CORE 2.4.2 final integration candidate: installation and rollback

Prepared for existing draft PR56; **not permission to deploy**. Select the exact
final GitHub SHA from this stage's release manifest/report after all CI jobs
pass. The manifest outside the source tree records commit/tree and all file
hashes, avoiding a self-referential SHA inside its own commit. Never deploy a
moving branch tip without comparing it to that exact verified SHA.

## Observed production baseline

- Render worker service `srv-db2f000ae00c73a42sn0`: live
  `3461ef75dccbb3c394f3add0d5fcb7624a9a43c7`, configured branch
  `feature/stability-reset-20261005`, start
  `python scripts/strict_double_20261006_v2.py`, autoDeploy=no. This configured
  source is a legacy scanner, not the canonical MCP entrypoint.
- Stake bridge `srv-db1nv9id0e5s738laq00`: live
  `ef0cc286c996cc3d892d05fb42af9170eb442ed8`; its health/token-presence endpoint
  does not fetch or verify a quote.
- Supabase `sefirot-core` / `kxqpwgwihtjmqlcxgfxp`: probe fence and park installed
  on 16 October, history versions `20261016214403` and `20261016214407`.
  Relay `sefirot-chat-store` v3 is installed with existing own-token enrollment
  and verify_jwt=false; candidate template is unchanged in this stage.
- Snapshot revision59 checksum
  `59844ba9e9110abec9cdb2a4e1a956aaae63ab78b48b38c33017c394cdc58a07`.
  Queue DONE104/ERROR23, no active jobs; row digest
  `216fc9abe40d048d0d938005b027f6c34abe0401dfaafded2bb170cb0cec3868`.
  Budget disabled, QUOTA_STOP, remaining5/reserve5, expired validity, no in-flight.
  Situation baseline is absent. Recheck this baseline immediately before rollout.

These are observations, not a claim that the final candidate runs in production.
No current provider quota or Stake odds access was tested.

## Installation order after separate owner authorization

1. Confirm permission covers the final exact SHA, the one situation delta and
   the existing Render service configuration. Keep queue and budget parked,
   providers and money disabled. Drain/stop producers and prevent the legacy
   scanner from starting during the transition. No new paid service is needed.
2. Retain verified private backups of the existing original checkpoint, job rows,
   function definitions/ACLs, relay/config and previous deployment metadata.
   Do not export credentials into release files. Read baseline counters, digests,
   RPC body hashes and ACLs; abort on unexpected drift. Use the reviewed hashes
   in `schema/probe_rollout_manifest.json` and `schema/situation_rollout_manifest.json`.
3. Apply **only**
   `supabase/migrations/20261016220709_situation_populated_parked_baseline.sql`
   when its guards match the installed parked probe baseline. The same exact
   file is exercised by local PostgreSQL WASM and native PostgreSQL CI.
   The canonical fresh-install `schema/supabase_chat_situation.sql` is unsafe
   on this populated database: it excludes legacy stake_snapshot and replaces
   transport functions. Do not apply it as an upgrade.
4. Verify the new receipt table, append-only trigger and three situation RPCs.
   Canonical bodies match the situation manifest. Only source-read EXEC is
   granted to service_role; situation enqueue/complete remain denied. Existing
   claim/probe remain denied, wrapper/private delegate unchanged, budget off.
   Preserve the documented NOLOGIN/NOINHERIT sefirot_ingest schema-USAGE
   binding without giving it queue/receipt/RPC access. Original rows/snapshot/
   budget and old kinds must be unchanged except adding
   `situation` to the accepted kind list. On any guard failure, investigate;
   do not relax guards or repair access silently.
5. Retain relay v3 after verifying its deployed source against the candidate
   template with the existing enrolled hash binding. Do not deploy the empty
   auth template or add a test credential. A redeploy is unnecessary when the
   source already matches. Missing positive authenticated testing remains an
   explicit acceptance item, not an excuse to reveal a secret.
6. On [the existing Render service](https://dashboard.render.com/web/srv-db2f000ae00c73a42sn0),
   configure the candidate branch `feature/situation-integration-20261013`,
   **the final exact release SHA**, Start `python scripts/chat_mcp.py`, retain
   Build `pip install . flask`, Python3.14.3, autoDeploy=no, health `/health`.
   Merge only the non-secret flags `SEFIROT_BRIDGE_MODE=mcp` and
   `SEFIROT_BRIDGE_READ_ONLY=1`; preserve all existing credentials and store
   bindings. MODE alone does not turn the old scanner into a bridge.
   The current connector cannot change branch/startCommand or pin a commit;
   use Dashboard or a properly authorized management capability. Do not redeploy
   the old configuration and do not rewrite the old Git branch to work around it.
7. Confirm live SHA, startup smoke marker, original durable revision59 and
   `SEFIROT_CHAT_JOB_WORKER_DISABLED read_only`. The startup demo is explicitly
   synthetic and is not a real prediction. Use an existing authorized client to
   read status/report; verify mutators refuse and the original hashes/counters
   remain unchanged. `/health` alone does not prove correct source, private-store
   authentication or checkpoint identity. No enqueue/claim or sporting fetch is
   needed for this parked runtime check.

Hosted migration history has different timestamps from the reviewed source
filenames because the previous authorized MCP apply generated those versions.
Compare names, source/body hashes and actual installed objects. Do not blindly
`supabase db push` the whole directory, reset history or mark migrations applied.
The authorized operator records the new actual history version and checksums.

## Park and rollback

Keep READ_ONLY=1 and the existing probe park. If startup fails, stop the failed
runtime, preserve sanitized logs and original archives, and leave SQL/receipts/
fences installed. Existing `supabase/review_only/20261015161311_park_probe_queue.sql`
may be used only when its own quiescence checks pass; it does not grant any
situation access. The new delta is idempotent only for its exact parked schema;
reapply never resumes mutators. No DROP, un-fenced completion, attempt reset,
first empty checkpoint or quota refill is part of rollback. An older scanner
may ignore READ_ONLY and make independent calls, so automatic legacy redeploy
is not a safe rollback. Investigate other independent consumers separately.

After read-only acceptance, a real collection window, queue resume, official
Stake provisioning/diagnostic, model calibration, main merge and money gates
still require their own evidence and authorization. Until then:
**RESEARCH_ONLY / PASS / stake=0**, small markets **SHADOW**.
