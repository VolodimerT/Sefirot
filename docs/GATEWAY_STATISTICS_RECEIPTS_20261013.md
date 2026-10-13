# Gateway statistics receipts and archive compatibility

VERIFIED: the actual football_gateway.get_sports SDK adds transport and
upstream_received_at to successful receipts. validate_statistics_packet
previously rejected these as unknown fields; real SDK-shaped statistics
therefore could not reach offline small-source import. The probe separately
dropped sports_only, which is mandatory in both saved-packet validators.
The defects are reproduced with actual SDK execution and mocked HTTP only.

FIXED: the statistics validator accepts both gateway fields together, requires
SUPABASE_GATEWAY and request_started_at <= upstream_received_at <= received_at,
and retains legacy direct-shaped saved receipts without either optional field.
The legacy offline format does not authorize DIRECT transport for new probes.
HTTP status must be exactly an integer 200; quota is a numeric string whitelist.
Unknown receipt fields, malformed/partial chronology and wrong sports marker
remain rejected. Validation never strips, repairs or modifies source packets.

FIXED: bounded probe archives preserve the original sports_only marker and
require all three chronology instants. Evidence schema becomes explicit v2.
Old v1 records are not upgraded or rewritten; reproduce them on their archived
build. Incomplete receipts cannot claim current CANONICAL_PACKET_ARCHIVED.
This still does not attest provider origin, licence, whole-league coverage,
exact HTTP bytes, fitted model eligibility, or monetary permission.

TESTED: initial 15-method regression suite on exact #50 reproduced defects
in 12 methods (10 failures and 5 errors including subtests). Final suite has
17 methods, including two schema/version guards. A successful path exercises
the actual SDK with a mocked HTTP reply, and another path passes both probe
fixture/statistics archives through import_api_archive without fabricating
missing receipt metadata. Canonical data/receipt envelopes are explicitly
serialized as new local bytes; original HTTP bytes remain unbound.

The probe fixtures/benchmark now carry a realistic full gateway receipt rather
than the previous incomplete synthetic receipt. Original assertions remain.
Existing probe (27) and saved-source adapter (37) suites also passed.
Full local release passed 1077/1077 in 60.724 seconds with integrity/replay=true.
Exact-head remote CI results are recorded in the PR/report.

VERIFIED/FIXED: the first Windows 3.11 CI run exposed an unrelated existing
PanelHttpTests client timeout at five seconds while a valid /run completed
real SQLite/CORE work. The handler reached send(303) after the client closed.
Controlled 5.1-second action delay reproduced TimeoutError with the unchanged
auth test (5.158s); bounded 30-second test-client waiting passed the same
test (5.166s). All authorization/303/durable-ledger assertions remain; no
POST retry, production timeout or handler behavior is changed. This is a
test harness timing correction, not a production speed improvement. The
initial failed CI remains evidence; the updated exact head is checked afresh.

small_market.py is outside MODEL_MODULES: exact CORE code_hash changes,
model_hash and Policy remain unchanged. No old money approval is inherited
by a different build, and no model/calibrator is fitted or relabelled.
Small markets remain descriptive research with P/EV=null and stake=0.

```bash
python -m unittest discover -s tests -p test_gateway_statistics_receipts.py -v
python -m unittest discover -s tests -p '*probe*.py' -v
python -m unittest discover -s tests -p test_small_source_adapter.py -v
python scripts/benchmark_probe_evidence.py --baseline-probe /path/to/pr50/chat_sports_probe.py
python scripts/verify_release.py
```

Benchmark runs actual before/after collectors with identical synthetic inputs,
not network requests. It reports the evidence schema and counts supported by
each version; both can bind canonical data but v1 lacks the required marker.
Measured paired collector CPU median 1.185 -> 1.235 ms (+0.055 ms paired),
31 alternating warm pairs of 10 repeats. Serialized response 17351 -> 17687
bytes for eight queries; v2 raw archive 7128 bytes. Compact rows are equal,
both versions bind eight canonical data packets. No claimed production speed,
forecast quality or out-of-sample improvement.
Preserve tracked historical reports after release; private source packets
and operational journals are not Git deliverables. This PR is not deployment.
