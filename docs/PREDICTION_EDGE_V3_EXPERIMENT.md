# V3 experiment protocol — implementation freeze, not an enrolled HOLDOUT

Status: KEEP_SHADOW. This document fixes hypotheses before any new outcomes are examined.
The runner saves `reports/PREDICTION_EDGE_V3_MANIFEST.json` alongside diagnostics.
A real manifest with fixture IDs, UTC kickoff times, league/profile, registration timestamp,
CORE policy hash and research code hash must be registered before collection. The empty
report is a template and is **not** evidence that a HOLDOUT has been registered.

## Arms and primary hypothesis

A = exact BASELINE_V1; B = DC_DYNAMIC_V1; C = SOS_LITE_V1. Raw and score-temperature
calibrated variants reported separately. Primary cohort is regulation football MEN, one
predeclared league; select that league on verified history availability before outcomes.
Primary endpoint is raw full 1X2 three-class log loss, candidate minus baseline on the same
fixtures. B is the first primary candidate; C and calibrated variants are exploratory in
this first registration (avoid picking a winner among many metrics after seeing results).
Secondary: multiclass Brier (sum, not divided by number of classes), and exact contracts
DOUBLE_CHANCE:1X, DNB:HOME, HANDICAP:HOME:-1, TOTAL:OVER:2.5, BTTS:YES,
TEAM_TOTAL:HOME_OVER:1.5, each as WIN/PUSH/LOSS. Log loss uses a fixed 1e-15 floor for zero probabilities;
Brier retains the raw vector. ECE uses five fixed classwise bins.
UNKNOWN is reported separately and not trainable; WOMEN/RESERVE/LOWER require their own
registrations. Do not pool them into the primary result.

## Splits and temporal boundaries

1. TRAIN: all explicitly supplied, timestamp-valid FT rows in exact league/profile, at most
   current + two preceding seasons and 730 days. Minimum 60 matches, four teams, six games
   for each target team. These are engineering floors, not statistical power guarantees.
2. CALIBRATION: disjoint later fixtures with original raw forecasts. At least 60 evaluated
   fixtures, ≥80% assigned coverage; five score temperatures [.8,.9,1,1.1,1.2], tie toward 1.
   Temperature minimizes 1X2 log loss only. Insufficient records means calibrated=null.
3. Historical TEST: already observed 380 games are descriptive material only. IDs must be
   enumerated in viewed_test_ids for a real registration; an empty list is only a template.
4. HOLDOUT: predeclare IDs/dates BEFORE kickoff. No overlap with any fit/calibration/viewed
   fixture. Freeze fitted artifacts and evaluate over at most seven days (fit expires).
   If not enough matches can be enrolled within this window, use prospectively declared
   weekly batches, each separately frozen; no using earlier holdout outcomes for fit.
   Such multi-batch orchestration is not implemented in this patch.

All assigned matches stay in the denominator, including missing capture, unknown result,
VOID, missing calibration and model-specific abstention. Report each model's coverage plus
the common three-model intersection; no seven-market pseudo-replication. Results cannot be
received after the evaluation cutoff. Hashes do not prove external timestamps.

## Predeclared review gate (not an automated approval)

Target ≥300 paired HOLDOUT fixtures and ≥30 UTC kickoff-date clusters, ≥80% scored coverage
in every arm, ≤5 percentage-point coverage drop vs baseline. These provisional floors
reduce fragile tiny-sample claims; they are not a formal power analysis. If the fixed-week
collection cannot meet them, KEEP_SHADOW until a separately registered multi-batch protocol
exists. Do not extend sampling opportunistically after checking outcomes.

B must improve primary log loss by at least .01, with the upper end of a paired date-cluster
95% percentile-bootstrap interval below zero (1000 resamples, seed 212). Brier must not
worsen by >.005; no predeclared segment with ≥50 cases may deteriorate in log loss by >.05.
All gates fixed before outcomes; these thresholds are research design choices. Manual
statistical review, source verification and separate owner authorization remain necessary.
Current evaluator **never promotes a model**, even when numeric thresholds happen to pass.
Bootstrap covers within-date clustering but not longer serial dependence; block-bootstrap
sensitivity is required before accepting actual results.

## Model choices fixed now

Half-life 180 days; prior 8 games; season multiplier .5 per earlier season; DC ridge 4;
400 deterministic line-search iterations, gradient/weight tolerance 1e-7; rho grid −.20
through .20 in .01 increments. Nonconvergence, stale fit, unknown team or invalid DC tau
means abstention. No parameter tuning on the old TEST. No bookmaker price in sports rows.
DC is a two-stage weighted Poisson/rho implementation, not full joint MLE. SOS freezes
opponent context at each historical kickoff; no invented xG/injuries/lineups.

## Market and ARENA protocol

Freeze forecast before quote import. Same fixture, REGULATION_90, full simultaneous 1X2
partition, receipt chronology, ≤120-second observed-age window, latest partition per
bookmaker. Proportional no-vig is an assumption; bookmakers are not independent samples.
Supplied lower bounds must later come from a separately validated probability uncertainty
method. Metric bootstrap is not such a bound. Same-book raw price-ratio CLV is labeled
separately from no-vig CLV, execution and ROI. No verified quote means NO_DATA.

ARENA: eight fixed role names from the chosen version registered before collection. Record
CORE/candidate vectors, each role veto, reviewed_at and original result on same fixtures.
Report CORE, CORE+veto, candidate, candidate+veto coverage, role precision/false-veto,
missed errors, leave-one-role-out and phi correlations. This implementation's error label
is wrong top 1X2 class, **not** bad expected value. Quote-backed utility evaluation and
original PR #14 adapters remain TODO. Missing reviews are not PASS.

Builder probabilities integrate shared score cells; PUSH legs are unsupported without
combined settlement rules. No combined price ingestion yet: all builder_ev=null/UNPRICED.
