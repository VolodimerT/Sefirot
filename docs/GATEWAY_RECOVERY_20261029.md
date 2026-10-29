# 29 October API-Football recovery (research only)

## Observed incident

At 20:38:59 UTC a single shared-budget permit was reserved; it was finalized
`FAILURE` at 20:39:08 UTC. Supabase Edge recorded HTTP 502 after 9447 ms.
The gateway then returned five HTTP 429 responses. Render completed those
probe jobs as `DONE` even though their first query held an error. One had
`PROVIDER_TRANSPORT_OR_AUTH_UNAVAILABLE`; the others had
`SHARED_BUDGET_PAUSED`. The 429s made no additional provider reservations.

The 9000 ms upstream cap is close to the 9447 ms edge duration and is a
plausible contributor. Existing logs do not distinguish an upstream timeout
from a later source-archive or edge-runtime failure, so **the exact source of
the 502 is not verified**. A budget `FAILURE` correctly fails closed; it must
not be automatically converted to `SUCCESS` or refunded. The gateway now has
7000 ms upstream cap, leaving time for its mandatory budget-finalization RPC,
and emits only fixed stage/error labels for future diagnosis. It never retries
an uncertain provider attempt.

The confirmed worker defect is independent of the 502's precise cause: after
any failed probe the worker claimed the next queued job. It now latches a
process-local `PROBE_REQUIRES_REVIEW` stop after the fenced completion is
acknowledged. `/status` exposes `provider_paused` and
`provider_pause_reason`; while paused it does not claim more jobs. A reviewed
restart clears this local stop, but **does not rearm the PostgreSQL budget**.

## Read-only verification before recovery

1. Verify exact deployed gateway version, Render commit and worker status.
2. Compare `sports_attempt` permits/outcomes with original `sports_archive`
   hashes and each affected job. Do not infer a provider response from HTTP
   502 or reconstruct a missing source packet.
3. Check provider's official account status and quota through an authorized,
   separately budgeted call only after owner approval. A dashboard value or
   stale response is not proof of current quota.
4. Confirm no active `in_flight` permit and decide whether the last uncertain
   attempt consumed provider quota. Count it conservatively if unknown.
5. Verify that the new branch's full exact-head CI is green. Prepare gateway
   source with the existing deployment-only auth injection; never commit or
   display injected values. Deploy gateway and the existing Render service
   only after separate production approval and coordinate the versions.

## Controlled recovery after separate approval

1. Freeze new producer submissions; inspect existing `PENDING` and errored
   jobs without resetting their attempts or source-dispatch fences.
2. Under the protected budget operator procedure, open only a bounded window
   consistent with the provider's verified quota and the 3000-call research
   ceiling **minus all prior attempts**. Do not directly update budget rows.
3. Restart the existing worker only after the budget and deployed code are
   checked. Test one PREMATCH fixture through the gateway and verify the
   archived original packet, receipt, SHA-256 and exact job identity.
4. Confirm `/status` shows the live worker and no local pause. On any 429,
   502/503, network timeout or SOURCE_SAFETY, stop the window and review the
   fixed gateway stage/error, budget permit and archive before another call.
5. Resume bounded daily collection only after the one-fixture check. No LIVE,
   automatic bets, synthetic source substitution, or model promotion.

The offline daily scanner and day-bundle qualifier already exist in draft
PR #73 and #74. They retain PASS for incomplete or unqualified data. This
change does not duplicate that scanner or claim that all leagues have been
collected. Qualification of a real 30 October day still needs real archived
PREMATCH packets, a validated CORE snapshot and independent evidence.

No production deployment, hosted migration, budget rearm, provider call,
main merge or money action is part of this PR.
