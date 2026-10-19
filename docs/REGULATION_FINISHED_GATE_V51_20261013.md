# V5.1: reject premature regulation FINISHED

VERIFIED: exact #45 accepted FINISHED at kickoff+1 second in service,
feature history and walk_forward; provider normalization/archive could
introduce the same observation. Five regression methods reproduce this
across the actual paths (13 failed subcases among 16 methods before repair).

FIXED: contracts.result_chronology compares timezone-aware instants. For
REGULATION_90 FINISHED, finished_at >= kickoff+90 minutes and
received_at >= finished_at. It is a necessary integrity bound, not proof
of a real whistle, correct score or provider authenticity. Receipts are
completion upper bounds; no timestamp is replaced with kickoff+90.

FIXED: Service rejects before result/feedback/audit mutations; history
rejects malformed direct input before feature construction; reconstructed
backtest rejects it before scoring. Offline normalization excludes invalid
FT rows with the existing IMPOSSIBLE_RESULT_CHRONOLOGY reason. Archive
quarantines a fixture with an impossible first FT even if a later packet
is also FT: it never claims the invalid first packet as availability.
Raw archive bytes are preserved. A manually supplied packet/hash still
does not establish source attestation or whole-league completeness.

TESTED: exact 90-minute boundary, one microsecond before, kickoff+1 second,
45 minutes, differing offsets, late receipt, received-before-finished,
idempotency, no write on refusal, preserved seals/packet bytes, bounded
offline source processing and early scoreless VOID. VOID keeps the existing
finished_at > kickoff rule and produces no calibration records. Pre-kickoff
cancellation semantics are unchanged. Unsupported formats remain governed
by the existing format gate; no new format is admitted.

Model identity intentionally changes because contracts.py/evidence.py are
model dependencies. Policy fingerprint, VERSION 2.4.2, payoff formulas and
goal-rate formulas are unchanged. Old calibrators/goal-model artifacts must
not be relabelled to the new hash; fit/validation and monetary permission
are not inherited. Replay old decisions on their archived build.

No database migration, historical correction, production deploy, refit or
provider call is part of this change. A prospective holdout and coherent
probability calibration remain BLOCKED/PROPOSED, not improved by these tests.

Verification commands (disposable checkout; release writes old report paths):

```bash
python -m unittest discover -s tests -p 'test_finished_chronology_v51.py' -v
python test_sefirot.py
python scripts/verify_release.py
```

Full release and exact-head remote CI evidence belong to the PR/delivery
report; 16 tests passing alone is not a full release or empirical model claim.

TESTED locally: full release 997/997, exit 0 (base #45: 981); demo/replay/
integrity and 12 synthetic fixtures / 84 scored contracts passed. Policy
fingerprint is unchanged. One controlled valid fixture has identical raw,
base and probability-bound hashes before/after, not empirical OOS evidence.
New model_hash: 2b4b6e396d34cf74132a3bfead508ab71d1f4df0caefd753e845ee7d056b1300.
