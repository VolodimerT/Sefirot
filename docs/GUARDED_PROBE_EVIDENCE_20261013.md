# Guarded research probe and reproducible source evidence

VERIFIED: the bounded #48 sports_probe collector called get_sports without
requiring shared reservation. On the current SDK dependency, absent gateway
configuration could fall back to direct provider transport. A valid mocked
fixture query made one direct call; the repaired route makes zero. A real
SDK test using an unmarked mocked gateway reply stops after the first reply.
No real provider request is used by these regressions.

VERIFIED: only compact rows plus the original data hash were returned. That
hash cannot be rechecked from a lossy projection. This does not mean the data
is fabricated; it means the original parsed packet is unavailable for
independent revalidation. Old jobs must not be reconstructed or relabelled.

FIXED: selectively integrate the read-only sports_probe route on exact #49,
using the shared-budget SDK dependency from that stack. Do not merge the
entire older #48 stack or its unrelated model changes. Request validation is
still bounded to eight queries; invalid calendar dates reject before I/O.
Wrong exact fixture IDs, duplicate known statistics and malformed object/bool/
nonfinite statistic values stop the batch with an opaque machine reason.
Earlier successful rows are retained; malformed metadata cannot trigger retry.

FIXED: archive safe canonical gateway data with its whitelisted receipt,
original payload_hash, projection_hash and source_packet_hash. Deep copies
preserve source/input immutability. Status nested receipts use the same safe
whitelist; extra authorization/header fields are not returned. Unknown or
sensitive source fields are not raw archived. Archive byte budget is 128 KiB
per job, within the existing queue response cap; refusal is explicit.

verify_evidence reads current bytes, detects missing original, source/projection
mutation or request relabelling, and never recalculates a missing original
hash as if it were historical evidence. It does not fetch, repair, refit or
write anything. The source format is CANONICAL_GATEWAY_JSON, not exact HTTP
wire bytes. A hash binds content and is not a signature or source attestation.
An attacker able to replace all data/hashes is outside this content-binding
guarantee. Provider origin, licence, full-league coverage and actual sports
quality remain separately unverified; model_fit_eligible=false and money=false.

FIXED: the original research route opened Repository in writable mode and
ran bootstrap, changing existing SQLite header bytes even without new records.
The new route requires an existing ledger and opens it read-only. Corruption
fails before transport. Durable restore is allowed, checkpoint is never called
for sports_probe; canonical forecasts/results/approvals remain unchanged.

TESTED: first 14 adverse methods on the unchanged #48 collector with selective
integration failed in 13 methods (5 failures, 8 errors). A later dedicated
status privacy regression reproduced forwarding of a synthetic credential
inside a nested receipt, then passed after sanitization. No real credential
leak or production exploitation is claimed.

Final probe suite: 27 methods, including the 3 retained #48 methods and
24 new methods. The one original mocked getter assertion now requires
require_shared_budget=True; original count/value/privacy assertions remain.
Complete release: 1060/1060, demo/replay/integrity and 12 synthetic fixtures /
84 contracts passed. Exact-head remote CI is recorded in the PR/report.

CORE code_hash remains 03cb3149b4463711603ca76215bc435385cdb10ef1a093c2dd6bffe006f464e6;
model_hash remains bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee.
All src/sefirot modules and Policy are unchanged from #49. Script changes
have their own probe_version/probe_code_hash rather than pretending to be a
new fitted CORE. Historical seals/fit compatibility are not relabelled.

TESTED measurement: reproducible scripts/benchmark_probe_evidence.py loads
both actual scripts with the same eight mocked queries. Compact rows match;
old rehashable packets=0, new=8. Source archive=6256 bytes; serialized job
output grows 5380->15847 bytes for this synthetic case. 31 alternating CPU
pairs: 0.172->1.172 ms, median paired +0.998 ms. Source preservation has a
small measured cost; no network/whole-decision acceleration is claimed.

```bash
python -m unittest discover -s tests -p '*probe*.py' -v
python scripts/benchmark_probe_evidence.py --baseline-probe /path/to/pr48/chat_sports_probe.py
python scripts/verify_release.py
```

Use disposable checkout for release; preserve tracked historical reports.
This is a draft source integration, not worker deployment, new collection,
API budget arming, model training, unseen holdout or monetary promotion.
The already deployed guarded gateway and the still-blocked legacy Render
suspension are separate operational facts. Private source evidence is not Git.
