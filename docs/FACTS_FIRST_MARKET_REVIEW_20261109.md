# Facts-first market review, 9 November 2026

The deployed branch remains `feature/stability-reset-20261005` at
`6a4c7c8f4fd37adad6af5621cd50b4fc183b13f7` at the time of review.
This change is stacked on the existing research candidate PR #75. It does
not alter the live service.

## Existing behavior and change

`market_grid.create_grid` already sealed a price-blind sporting distribution.
`compare_grid` assigned D to all fifty rows, including absent quotes.
`builder_research` and `small_market` assigned D while explicitly lacking
joint prices or a validated probability. The CORE final decision used D
whenever no candidate survived, which also mixed missing evidence with bad
price. These labels were conservative blocks, not permission defects:
`decision=PASS`, `stake=0`, the calibration/holdout/Policy gates and execution
protections remain intact.

The grid now presents resolved FACT records with source ID/group, observed,
published and received times, operator-asserted reliability, model team-game
sample counts, and explicit missing metrics before quote comparison. It does
not infer directional support from merely listed facts. Missing xG/xGA, player
roles, rest and schedule remain explicit. Source independence from bookmaker
lines is NOT_ATTESTED unless provenance is independently checked.

Comparison retains raw/base EV for research diagnostics but labels certified
probability and EV unknown when the expanded selection and holdout are not
validated. C means evidence/validation/price is insufficient; RED marks an
explicit sealed scenario-market conflict. D in the CORE final card now
requires an observed negative EV, calibrated bin, passed release, normal
sports mode and no other blockers. A/B still depend exclusively on the
unchanged admission path; a research card cannot promote PASS to BET.
Small markets and same-game builders remain C/SHADOW and unpriced where
joint model calibration or real combined quote is absent.

The existing `market_reference` compares only a complete simultaneous
same-bookmaker line. A 1.85/1.85 two-way line gives a proportional no-vig
reference of 0.5/0.5, fair reference odds 2/2. At independently verified
fair odds 2.00, a hypothetical 100-unit stake at 1.85 has EV -7.50;
the quoted odds already include the margin and EV does not subtract it
again. No-vig is a benchmark, not proof of true probability or value.

The CORE WIN/PUSH/LOSS contract cannot represent half wins/losses. The new
`quarter_lines` module is a separate research-only settlement calculator:
1.25 splits into 1.0 and 1.5, 1.75 into 1.5 and 2.0. Exactly one goal on
team OVER 1.25 is half LOSS and half PUSH. It reports only raw score-model
diagnostics, validated probability/EV unknown, C/PASS/stake=0. The offline
two/three-leg express calculator applies partial returns and an exposure
cap; same-fixture correlated legs are refused without a joint builder
contract. The existing builder integrates joint score cells and does not
multiply dependent marginals, but a real combined bookmaker price and
independent calibration remain missing.

This changes the overall build code hash. Existing sealed predictions must
not be relabelled or rewritten; a new prospective capture is needed for the
new build. MODEL_MODULES and Policy remain unchanged. Historical examples
used during development are regression evidence, not independent HOLDOUT.
Continue prospective observation with original pre-kickoff source receipts,
sealed model outputs, complete same-bookmaker quotes, FT results and
time-separated TRAIN/CALIBRATION/HOLDOUT before any A/B claim.
