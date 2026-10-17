# Issue #69: preserve sources across a bounded collection failure

At candidate `8c75f6e53acb2eee4619eb1d34a0aaad6bfd434c`, the explicit CLI kept
fixture, coverage and enrichment responses in memory and wrote its output only
after every request succeeded. A valid status and fixture followed by a shared
budget MINUTE_LIMIT refusal produced exit2 with no saved fixture packet. Six
owned CLI regressions fail on that immutable baseline; the original 14 collector
tests did not cover recovery after a later failure.

The existing collector now archives each validated sports packet before quota
planning or the next request. The CLI reserves `<output>.sources/` before any
networking. Each packet is canonical JSON under its own content-hash filename,
written to a private temporary file, flushed/fsynced and published by exclusive
hardlink. It never overwrites an existing packet. Existing output/archive names,
including occupied symlink names, refuse before provider I/O. A disk failure
stops collection before another request; originals already published are kept.
Failure to complete the final output does not remove the packet archive.

Original packet data, receipts, UTC timestamps and hashes are preserved. This
is **CANONICAL_GATEWAY_JSON**, not original HTTP wire bytes or independent
provider attestation. Raw account status is never written. Unknown quota can
stop further use after a valid source has been retained; a saved packet does not
by itself establish model eligibility. Invalid provenance/hash is not admitted.
There is no retry, automatic resume, reconstructed response or new scheduler.

The CLI paces sequential requests at least 61 seconds after the previous
response, matching the observed gateway limit of one request per minute. Every
call still requires the shared gateway guard; a concurrent request can still
cause a refusal, which stops the run. The library's injected getter remains
available for offline use; it is not evidence that a real budget is open.
Allowlisted shared-budget failures retain their fixed public code instead of
becoming an unexplained transport error. Arbitrary private upstream text is not
printed by the CLI.

Independent QA found that the pacing wait itself could cross a PREMATCH
kickoff after planning. The actual fetch now rechecks the selected NS fixture
cutoff after every wait, before transport. A 180-second-to-kickoff owned case
retains both base packets and refuses the fourth request at 183 seconds. It
does not mark that run complete. If an in-flight response arrives after kickoff,
its valid packet is first archived, then the run refuses PREMATCH completion.
Published packets are flushed; this does not
claim a guarantee against filesystem/power failure of directory metadata.

## Actual state and next permitted collection

Read-only observations on 16 October: queue DONE104/ERROR23, no pending/running;
claim/probe completion parked; budget enabled=false, QUOTA_STOP, remaining5,
reserve5, expired validity and no in-flight reservation. Five historical
successful reservations consumed the five allowed calls, reaching the protected
reserve. The last saved provider quota on 15 October was 7496/7500 day and
299/300 minute. This is not the current provider quota. It is **NOT_VERIFIED**
until a separately authorized fresh status request.

The prior five requests yielded 56 unique fixture IDs but no full archived
source packets. Compact history cannot recover the original responses. Old
hashes/timestamps are retained; missing source evidence remains missing.

After a separate owner-approved quota/time window, the minimal proposed run is
four requests for one explicitly selected finished fixture: status, fixture,
league-season coverage, then fixture statistics only if coverage and quota
permit. A contemporary postmatch collection is not a historical PREMATCH
forecast. A minimal explicit command, **not executed in this stage**, is:

```
python scripts/football_enrichment_collect.py --fixture-id REAL_ID --league-id REAL_LEAGUE --season REAL_SEASON --max-requests 4 --reserve 5 --output /private/new-run.json --execute-single-fixture
```

The operator must approve the real IDs/window/call cap first; placeholder IDs
are not runnable source data. A denied/error run is inspected from its existing
`.sources/` archive and fixed public reason, never retried automatically. A
later authorized run chooses a new output name. Fixture packets can be passed
individually to the existing `football-archive` importer; leagues/statistics
remain enrichment evidence and are not mislabeled fixture-history packets.

Real chain remains conditional: original Football packet → original sports
archive → source-backed PREMATCH seal → independently verified Stake quote →
canonical decision/journal → later original result → evaluation. Missing history,
Stake permissions or calibration means **PASS**, not invented probabilities/EV.
Small markets remain **SHADOW**. No budget activation, provider call, hosted
mutation, model/Policy change or bet was performed by this repair.
