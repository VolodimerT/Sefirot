# SEFIROT V3.3 — situation P0–P1

Scope: audit `SEFIROT_TASK_AUDIT_V3_3_LIVE_PREMATCH_SPEED_ODDS2_2026-10-11.md`
and its two identical next-task files, read in full on 2026-10-11.
Base is exact PR #22 `9b88d130e69e3be5ee69723469913b36c28bb3e8`.
Three PR #30 files at `b7266fd60fdcce39b8aa0ab044fdd0292675f260`
were reused, then hardened. No ARENA/PR #24/27/28 merge, main merge or deployment.

## Evidence and actual integration

PR #30 CI run [38124368104](https://github.com/VolodimerT/Sefirot/actions/runs/38124368104):
757 tests in each of four Ubuntu/Windows × Python 3.11/3.13 jobs, zero skips,
replay/integrity true. Checkout was GitHub merge-ref `3dc9be698c00c3c217f310214738aacf497f3ec7`;
its tree `ccbce7ace399a3e2de2ab96735a4015a1bee6f09` equals the exact head tree.
This establishes the prototype's technical CI, not source authenticity or live quality.

The actual dispatch is `scripts/chat_gateway.py:execute`, before the canonical
ledger lock/restore. It calls only `chat_situation.execute_situation`. The six
existing queue kinds and original capture/decide/result Service remain separate.

| Surface | Implemented here | Deployment state |
|---|---|---|
| CLI | `python scripts/chat_situation.py --request request.json` | Local operator entrypoint; original CORE CLI unchanged |
| REST | authenticated `POST /v1/situation` with exact typed JSON | Real loopback HTTP tested; not deployed |
| MCP | `sefirot_situation`, same exact schema and dispatcher | Real loopback MCP tested; not installed/deployed as a new ChatGPT app |
| Worker | `kind=situation`, same dispatcher; completion carries lease attempt | Local HTTP→relay→PostgreSQL→worker tested; production allowlist unchanged |
| Supabase relay | `situation_source`, `situation_enqueue`, leased `complete` | `server/chat_store_gateway.js` is a fail-closed source template with no enrolled token hashes |
| SQL | bridge-only receipt registry, idempotent enqueue and leased completion RPCs | `schema/supabase_chat_situation.sql` is a reviewable extension, not applied |

Read-only cloud inspection confirmed the existing relay version 2 and six-kind
SQL constraint. The original public RPCs have service_role-only EXECUTE and empty
search_path. The extension preserves those privileges and old-kind behavior.
Old completion explicitly refuses `situation`; it cannot bypass the new lease.
No original canonical Supabase table or persistent snapshot was changed.

## Trust boundary and typed contract

`research/situation_contract.py` defines frozen request/identity/response types.
Required fields are fixture_id, provider_status, kickoff, status_observed_at,
request_at, intent (`auto/prematch/live`), depth (`auto/fast/deep`),
original_provider_receipt_id, and identity containing source_id, integer
source_revision, receipt_hash, model_hash. Unknown fields, client permission,
inline receipt/path/comparison, naive clocks, bool revisions and malformed hashes
are rejected. Request timestamps are assertions; server wall clock governs expiry.

The authenticated server resolves the original record by receipt ID from its
private registry; it never reads an inline client packet. Original body hash,
collector HMAC, fixture/status/kickoff/observation/source/revision and original
model identity must match. Observation <= receipt <= request <= server time;
requests older than 120s expire. Freshness uses observation, not a refreshed
local receipt. No sports API fetch, odds request or fallback source is triggered.

**HMAC authenticates the enrolled collector, not API-Football or a provider
timestamp. A SHA-256 alone does not authenticate either.** No external attestation
adapter is implemented in P1: every real `UNATTESTED_ARCHIVE` record returns HOLD.
`SYNTHETIC_TEST_ONLY` requires explicit server opt-in and is labelled in both the
short Russian summary and JSON. A caller cannot turn either into a betting grant.
Missing auth/config/record, forged source, contradictions and unavailable store
fail closed. The response never calls CORE or includes a probability, EV or quote.

The local operator source directory/key and synthetic switch are only test/review
configuration. They are not provisioned in production; no secret was replaced.
There is no client receipt registration route or provider health polling.

## Phase behavior and previous behavior

| Original recorded status | Current routing | CORE permission |
|---|---|---|
| fresh NS, >20m before kickoff | PREMATCH / DEEP | false; separate verified capture required |
| fresh NS, <=20m before kickoff | PREMATCH / FAST | false |
| NS at or after kickoff | HOLD | false |
| fresh 1H/HT/2H/ET/LIVE after kickoff | LIVE_RESEARCH / FAST | false; live model absent |
| FT/AET/PEN after kickoff | POSTMATCH | false; no automatic settlement |
| unknown/stopped/stale/mismatched/unattested | HOLD | false |

At PR #22, REST returned 404, MCP had no situation tool, and SQL rejected its
job kind. At PR #30, a local dict could produce a prematch routing permission;
recent receipt time could hide an old observation; duplicate equal market rows
could reach Python dict comparison while sorting; names implied verified prices.
Here permissions remain false, observation age is explicit, duplicate keys are
rejected, and the prototype viewer labels all candidates NOT_ATTESTED. The viewer
still cannot attest arbitrary comparison JSON and is intentionally not connected
to any client-facing surface. P2 must invoke canonical compare_grid itself.

## Durable jobs and validation

Situation enqueue derives one UUID from the complete server-normalized request
SHA-256 (including source revision, model identity, intent/depth and UTC as_of).
Equivalent offsets reuse the same job; differing identity/depth/as_of are isolated.
An unlikely UUID collision is rejected unless the entire request is identical.
The SQL request-key hash uses PostgreSQL JSONB serialization; response request_key
uses Python canonical JSON. They are separate implementation identity scopes.
Completed job replies are archived evaluations at evaluated_at, never fresh status
checks. A new current question requires a new request_at and original fresh receipt.

Claim uses the original three-attempt SKIP LOCKED lease. Situation completion
checks exact attempt, kind, original fixture/receipt and false permissions under
row lock. Same completion can be acknowledged again; stale worker cannot overwrite
a reclaimed attempt. Queue writes are isolated journal writes, not predictions.
The source registry is append-only at application/trigger level; an administrator
remains able to replace underlying storage, as with the existing ledger.

Tests include real local HTTP/MCP, server capacity 429, source outage, cutoff ±1s,
late NS/live, observation vs receipt lag, halftime, timezone/DST, source forgery,
arbitrary JSON, odds 1.99/2.00/2.01, duplicate markets and old client regression.
SQL/auth tests execute 14 SQL groups and 11 relay groups on pinned PGlite 0.5.8
(PostgreSQL 18 WASM); missing dependency fails, no skips. This differs from cloud
PostgreSQL 17 and does not test the hosted Supabase/Deno runtime.

The local full queue test records an original synthetic CORE prediction/decision,
checkpoints the SQLite, processes situation, restarts PostgreSQL, re-enqueues the
same job, restores identical SQLite bytes and replays the original decision.
Only claim/source/complete RPCs occur during situation. No pull/save/checkpoint.
CLI JSON and the Node subprocess protocol explicitly use UTF-8. The CLI regression
forces PYTHONIOENCODING=cp1252 and requires the Russian summary to survive. The
initial Windows CI exposed both missing encoding declarations and Python 3.11's
locale-sensitive strftime. Format directives stay ASCII; Russian labels are
appended afterwards. These failures were fixed, not skipped.

Commands: `npm ci --ignore-scripts --no-audit --no-fund`,
`python test_sefirot.py`, `python scripts/verify_release.py`.
For reproducible measurements: `python scripts/benchmark_situation.py --n 100 --output /absolute/new-report.json`.
The warm benchmark makes 100 controlled loopback requests per five synthetic
classes, reports p50/p95/p99 and server processing. It excludes CORE, ARENA,
cloud cold start, queue and sports network latency. FAST/DEEP currently route
presentation depth only. No full-path acceleration or production SLO is claimed.

## Шпаргалка пользователя

Первым приходит `summary`: режим, матч, время UTC/Киев, статус/давность,
CORE NOT_EVALUABLE/NO_SOURCE, основание и одно следующее действие. Полный JSON
с паспортом и измерением времени — доказательная часть ответа.

- `auto`: система выбирает фазу и FAST/DEEP по свежему статусу и времени начала.
- `prematch`: live или уже начавшийся NS даст HOLD; нужен отдельный capture с
  полными проверенными спортивными данными до чтения цены.
- `live`: только LIVE_RESEARCH при согласованном свежем статусе. Live-прогноза
  и денежного входа здесь нет. Старый прематчевый прогноз для live не применяется.
- Без удостоверенного источника — HOLD. Без API можно читать старый журнал и
  проводить явно синтетическую инженерную демонстрацию.
- Альтернативы >=2.00 в situation пока отсутствуют: P2 должен привязать точные
  bookmaker receipts. Сам коэффициент >=2.00 не отменяет PASS/EV/Policy.

## Stop and remaining blockers

STOP after P1. No source recovery, billing/key change, deployment or main merge.
Issue #29 remains open: current API-Football access UNKNOWN, last authenticated
suspension on 2026-10-06. No new provider probe was made. External trusted status
collection, cloud migration/deployment and hosted end-to-end verification remain
blocked/deferred. The old generic queue remains at-least-once and can leave an
exhausted RUNNING lease; this extension does not revise old mutating job semantics.
P2 quote binding/EV alternatives and P3 standalone live model are not implemented.
P4 full-path cold/warm budgets and global provider quota guard are not measured.
Real model metrics, benefit, betting edge and independent HOLDOUT are NOT_MEASURED.
