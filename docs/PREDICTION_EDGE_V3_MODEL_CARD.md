# PREDICTION EDGE V3 model card

Research-only, disabled in production. No money permissions. No trained real-data artifact
is shipped. Status: KEEP_SHADOW / INSUFFICIENT_REAL_DATA.

| Model | Implementation | Limits |
|---|---|---|
| BASELINE_V1 | Calls unchanged CORE `probability.estimate`; unchanged policy required | Independent Poisson, current priors and caps preserved |
| DC_DYNAMIC_V1 | Exponentially weighted, L2-regularized team attack/defense and separate home/away log intercepts; then fit low-score rho on TRAIN | Two-stage conditional rho, not full DC MLE. Dynamic means refit with time-decayed weights, not online latent-state dynamics. No superiority evidence |
| SOS_LITE_V1 | Own/opponent normalized goals with venue league rates, frozen earlier opponent strength, decay and season shrinkage | Sparse historical receipts cause prior-only opponent estimates; not equivalent to observed xG or lineup quality |

Reference for the DC family: Dixon & Coles (1997), *Modelling Association Football Scores
and Inefficiencies in the Football Betting Market*, JRSS C 46(2), 265–280,
https://doi.org/10.1111/1467-9876.00065 . This implementation is an explicitly simplified
research variant; the paper's historical findings are not evidence for SEFIROT.

## Inputs and artifacts

Strict rows: id, home, away, league, competition_profile, season, kickoff, finished_at,
received_at, home_goals, away_goals, source_id, receipt_sha, synthetic. Unknown fields such
as odds are rejected. Explicit context; no inference of competition profile from a team name.
At most current and two previous seasons. Future receipts, duplicate/revised IDs and stale
rows reject the submitted fit rather than silently selecting convenient observations.

Artifact records code hash (all research files + unchanged canonical model hash), config,
training IDs, digest, cut-off, context, parameters, optimizer convergence, synthetic flag
and content hash. Artifact rows can be private; DO NOT commit user sports packets or secrets.
A digest is corruption detection, not provider authentication. Caller must obtain/verify
original receipt-backed data. A forged-but-consistent JSON is not made trustworthy here.

Score mass supports rates 0..12, grid 0..50, explicit residual and normalization. The DC
four-cell correction is rejected if nonpositive. All main-market probabilities and research
builders project from the same mass; CORE's separate 0..35 builder is not reused implicitly.
Baseline retains its original domain and exact output, including existing truncation.

Score-temperature calibration raises cell masses to 1/T and renormalizes in log space.
It preserves common-market coherence but is not necessarily well calibrated; its five-point
TRAIN-independent CALIBRATION fit is an experimental alternative to per-contract v4 bins.
Zero cells stay zero. No fitted calibration is fabricated when data are absent.

## Known limitations and next engineering work

1. Implement audited adapter from original sports archive/ledger to research training rows,
   including immutable first-observed packet binding, profile/season proofs and revision policy.
2. Bind forecast model hashes and calibration artifacts to the original prospective seals;
   diagnostic JSON currently validates internal consistency only.
3. Prospectively register exact fixtures and prove new HOLDOUT exclusion from every fit;
   implement multi-batch registration before claiming a large future test.
4. Validate optimizer and hyperparameters on TRAIN-only splits; benchmark runtime on a real
   multi-season archive. Current tests exercise numerical invariants, not predictive quality.
5. SOS preprocessing is quadratic-plus in historical context; cache immutable frozen feature
   tables before scaling. No xG, squad/lineup or injury ablations in this iteration.
6. Add rolling/block-bootstrap sensitivity, formal sample-size/power rationale, calibration
   uncertainty and provider/missingness sensitivity before any empirical release claim.
7. Validate model-specific individual probability intervals; caller-provided comparator lower
   bounds are not certified. Quotes carry an explicit verified assertion, not a provider proof.
8. No verified bookmaker consensus, executable-price history, no-vig CLV, ROI or combined
   quote settlement adapter exists in this patch. Raw same-book CLV is not profitability.
9. ARENA ablation is a separate diagnostic helper. Integrate PR #14 receipts and quote-backed
   utility before interpreting veto quality; original analyst timestamped comparisons absent.

Actual real model metrics: null for every arm. New externally verified HOLDOUT matches: 0.
