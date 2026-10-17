# SEFIROT CORNERS_SHADOW_V0 — 11.10.2026

**Scope:** Research-only, no integration with capture/decide, portfolio, booking, or production. The original BASELINE_V1 and sealed predictions are unchanged. Every shadow result sets monetary_permission=false.

## Why

The October 10 forensic audit found incomplete league history, research presented as betting permission, and stale LIVE match state. Junior Barranquilla — Internacional de Bogotá on 11 October supplied corner markets outside the goals-only CORE:
- Original Stake bundle @2.38: Junior scores first + total FT corners OVER8.5 + Junior 1X.
- Parik24 full-time corners OVER9.5 @1.82 / UNDER9.5 @1.98.
- First-half corners OVER4.5 @1.85 / UNDER4.5 @1.90.
- Internacional FT team Asian corners OVER4 @2.04 (4=push).
- Corners double chance 1X @1.28, X2 @2.57 — these refer to CORNER counts, not the football score.

The canonical CORE 2.4.2 sealed *goals* prediction da80f4e23efddfc21b4f868b3f610ca7d18ad38b221079e10ccfedc59ee9afe1 came from 324 full-league *goal* results, with lambda 1.761/1.092. Official decision PASS D, bankroll allocation zero. Goal intensities cannot be used as corner probabilities.

## Required data

Every CornerMatch needs independent source ID, unique match ID, competition ID, normalized home/away teams, timezone-aware kickoff and *actual availability time of the result*, full-time HCFT/ACFT and first-half HC1H/AC1H. Validate: no duplicated IDs, foreign league, future/unavailable results, missing periods or first-half corners larger than FT corners.

Complete league history is required — **not a two-team subset**. The minimum 80 prior league matches and eight prior venue-specific games per team are *technical shadow thresholds*, not evidence that an edge is established.

Potential sources:
- https://footiqo.com/es/base-de-datos/ligas/colombia-primera-a/ — exposes HCFT/ACFT/HC1H/AC1H fields on the public sample, but NOT the complete training history.
- https://www.totalcorner.com/team/view/848 — recent team matches, including **cup fixtures and unfinished rows**, requiring explicit exclusion.
- https://www.colombia.com/futbol/liga-colombiana/torneo/resultados — finished goals, **not** complete corner history.

Check licenses and provider terms before ingesting.

## Implemented standalone research engine

src/sefirot/corners_shadow.py:
1. Price-blind FT/1H intensities built on **league-wide priors**, 180-day decay, venue-corrected for/conceded counts, eight effective-game shrinkage.
2. Separate 1H and FT distributions. Poisson independent-side baseline; NB alternative only as *distribution stress*, NOT fitted calibration.
3. Explicit TOTAL, TEAM, and CORNER DOUBLE_CHANCE markets, integer Asian-push settlement and .5 line support; unsupported quarter lines fail closed.
4. Raw EV, win/push/loss, fair odds, rate/family stress, history SHA-256 and source provenance. Monetary permission always false.
5. Time-ordered walk-forward evaluation: Brier/log loss, frequency and model mean, never training on results published after kickoff; explicitly NOT independent HOLDOUT.
6. Nine deterministic synthetic unit tests verify contract and chronology, count=0, no leaked future results, corner-vs-goal separation, Asian push, fail-closed and reproducible evaluation. Synthetic tests do not indicate forecast accuracy.

## Findings on the fixture

- The auxiliary goal-first calculation for Junior at @1.45 gives about 58.17% vs 68.97% break-even.
- First Junior goal AND Junior 1X, modeled **jointly**, was around 54.28% from the goal model, with no corner coupling inferred. The Stake @2.38 three-leg bundle would require about 77.4% chance of corners OVER8.5 **conditional on both goal conditions**; no verified model supplies that.
- Internacional team corners OVER4 @2.04 had only 4 wins, 1 push, and 5 losses in the 10-match away sample. Its season averages differ across sample definitions; no independent calibration.
- Parik24 margin: corners full-time O/U9.5 ~5.45%; first-half corners O/U4.5 ~6.69%; first-goal result market ~13.60%.
- No approved bet; official CORE verdict PASS D / stake 0 remains binding.

## Acceptance prerequisites

P0: A licensed **complete match-level corner feed** with 1H and FT split, venue, provenance and known-at timestamps. Missing or ambiguous data produce PASS.

P0: Keep this experiment disconnected from production chat gateway, decisor, and betting ledger. No synthetic fixture can enter real reporting.

P1: Pre-register targets and hyperparameters. Evaluate with a chronological **untouched holdout >=100 matches/league**, alongside benchmarks: league-average, bookmaker no-vig, Poisson, NB and venue adjustments. Report Brier, log loss, calibration, intervals, failure modes.

P1: Bet Builder conditional joint goals x corners requires an empirical jointly verified distribution. Never assume marginal independence or infer calibration from one night.

P1: Confirm rules for 1H, push, abandoned matches and official corner corrections, quote timestamps, liquidity and concentration risks.

No production activation or monetary authorization before P0/P1 completion and separate review.

Test command:

~~~bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_corners_shadow.py' -v
~~~
