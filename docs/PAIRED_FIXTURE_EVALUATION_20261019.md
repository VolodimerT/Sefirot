# Paired evaluation must count fixtures, 19 October 2026

Baseline: integration candidate `2bef3110c9be20c1cf4a1f8af28a463ef0eafc45`.
This repair is an isolated release candidate, not an installation or a model fit.

## Reproduced defect

`src/sefirot/feedback.py:compare_versions` used the number of common
`(match_id, market)` rows for `Policy.min_holdout` and an IID normal interval.
Nine synthetic fixtures with seven correlated markets each produced `n=63`,
`REVIEW_PROMOTION` and interval `[0.2, 0.2]`. Reversing the score difference
produced `ROLLBACK`. `Service.compare_and_rollback` can act on that result when
the active route is the newer model; the older model still needs its existing
activation/validation checks. This is a reproduced incorrect sample-size
decision, not evidence that any real route was changed.

The initial 14-method regression suite failed on the unchanged evaluator:
10 failures, 3 errors, 1 pass. Failures include the actual service method with
owned in-memory substitutes; no model routes, provider, database or secrets
were accessed. A further explicit equivalent-offset test was then added.

## Repair and interface

- `n`, `unpaired_old` and `unpaired_new` retain their event-market row meaning.
  New `paired_market_rows`, `distinct_fixtures`, `date_blocks`, missing-kickoff
  counts and interval thresholds make the denominator explicit.
- Average paired Brier differences across common markets within each fixture,
  then equally weight fixtures. Extra markets cannot inflate the fixture count
  or give a fixture more weight. The estimand is the common-market comparison;
  unequal/full-market cohort coverage is not certified by this function.
- Use UTC **kickoff** days as whole bootstrap clusters, preserving within-game
  and within-day dependence. Do not substitute result receipt/publication dates.
  Check kickoff identity across both models and all paired markets of a fixture;
  equivalent timezone offsets are accepted as the same instant.
- Reuse the existing read-only `scripts/calibration_quality_audit.py` method:
  2,000 deterministic draws, seed 20261008, percentile positions 49/1949,
  minimum 30 fixtures and eight UTC days to report an exploratory interval.
  `Policy.min_holdout` remains the additional **distinct-fixture** threshold
  for either recommendation. This does not invent a 60-day requirement.
- Missing kickoff or insufficient date clusters gives no interval and
  `KEEP_SHADOW`. Invalid/non-finite Brier values are refused. No pairing gives
  no interval. Positive/negative recommendations still use strict exclusion of
  zero, and `REVIEW_PROMOTION` remains a review rather than an activation.
- The interval is exploratory. An empirical bootstrap can have zero width
  when every observed cluster has the same effect; that does not establish
  unseen-data precision. `certifies_model=false` and
  `independent_holdout_verified=false` explicitly preserve this distinction.
  The function does not verify prospective seals, train/calibration separation,
  a preregistered market cohort, future team dependence, or a monetary edge.

The service caller and existing activation prerequisites remain unchanged.
All seven `MODEL_MODULES` files and `Policy` bytes are identical to baseline:

- model hash: `bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee`
- policy hash: `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9`

The exact build/code hash changes because evaluator code changes; old stored
hashes, archives, model registrations and sealed predictions are not rewritten.

## Validation

The final 15 new owned regression methods pass locally on Python 3.12.14,
including small-cohort routing refusal, single-day/missing-date refusal,
fixture weighting, repeated-market interval invariance, finite-score checks,
unpaired rows, kickoff identity/offsets and deterministic non-mutating output.
All 62 existing `test_core2.py` methods pass. Its existing 60-case comparison
test now supplies distinct real-format synthetic kickoff dates; its rollback
assertion and outcome-mismatch refusal are retained.

Independent read-only QA reran the initial 14 green methods, verified unchanged
model modules, and checked an additional heterogeneous ten-day example:
60 synthetic fixtures, delta +0.2 on five dates and -0.1 on five dates gives
mean +0.05, interval approximately [-0.04, +0.14], `KEEP_SHADOW`.

An owned CPU-only microbenchmark (60 fixtures, 420 common market rows, ten
UTC dates, 31 alternating before/after pairs, three repeats each) measured
median 0.506 ms before and 13.045 ms after on Python 3.12.14 in this container.
The increase pays for the deterministic clustered uncertainty calculation;
there is no latency improvement claim or provider/database I/O in this test.

Reproduce:

```sh
python -m unittest discover -s tests -p test_paired_fixture_evaluation.py -v
python -m unittest discover -s tests -p test_core2.py -v
python scripts/verify_release.py
```

Release CI and exact Python 3.14.3 verification must be recorded against the
published integration SHA before release. This document does not assert remote
CI has run for an unpublished isolated commit. No original historical data,
reports, receipts or seals are changed; generated local release reports must
be restored rather than committed as historical proof. No hosted writes,
provider calls, quota use, fit, deployment, main merge, or bets were performed.
