# V5.1: stable score-probability summation

VERIFIED: exact PR #47 source failed strict calibration on 18 of 121 fixed
Poisson rate pairs when a supported extreme line placed all score cells in
one category. Example: rates 1.35/1.35, TOTAL UNDER 1000, WIN=
1.000000000000001 although the stable sum of the input mass was below one.
Actual capture failed on ordinary synthetic history and histories containing
only 0, 1 or 2 goals. This was a fail-closed crash, not a demonstrated bet.

FIXED: Poisson normalization and explicit residual tail use math.fsum. Market
projection independently sums WIN/PUSH/LOSS with fsum and checks the unchanged
1e-8 partition-total tolerance before any boundary correction. Individual
cells outside [0,1], bool/nonfinite values and invalid scores fail closed.
Only aggregate overshoot within four ULP at one (8.881784197001252e-16) is
bounded to one; larger excess raises ValueError. The vector is not rescaled,
small opposing probabilities are retained and missing tail is not folded
into the last score. Settlement caching still stores rules only.

This intentionally changes two MODEL_MODULES. New model_hash:
`bdb154a9ea169a1a7b9b719df0d90a1cc7126f9978bc66e7195a4e83d8edefee`.
Old calibrators fail their existing compatibility check; no fit/relabel or
automatic inheritance of validation/approvals. Policy, sporting rate equations,
settlement contracts, historical ledger/seals and archived reports are unchanged.
Replay of an old seal still requires its archived exact build.

TESTED: 12 new regression methods. On the old source, 9 methods failed
(151 failing subcases and 4 errors; these are not 155 independent tests).
After repair all 12 pass. The suite includes 121 rate pairs x 8 extreme
contracts, order independence, a Decimal(80) numerical oracle, >4096-cell
uncached support, tiny opposing mass, material excess, cache validation,
explicit tail, previous artifact refusal and actual capture/decide.

The actual extreme-line workflow now reaches its existing bounded-coherence
refusal: PASS/D, stake=0, no bets or approvals and valid ledger integrity.
Strict calibration validation was not relaxed to make the crash disappear.

Two old cache tests required equality with the original += rounding. Their
reference helper now sums the same cells independently in Decimal(80);
exact assertEqual, every supported contract and all cache assertions remain.
The first full release failed these two methods (253 subcase failures).
After correcting this obsolete oracle, all 23 runtime tests passed.
Full final release: 1033/1033, exit=0, demo/replay/integrity, 12 synthetic
fixtures / 84 contracts and compileall. Exact-head remote CI is required
and recorded in the PR/delivery report, not inferred from this local result.

TESTED measurement: scripts/probability_summation_benchmark.py loads both
actual local source trees under distinct packages. The fixed 121-pair grid
has 18 calibration failures before and 0 after. For one default fixture,
max raw/base/bound delta=4.44e-16 and max stress delta=1.22e-15; candidate
keys, Policy hash and prepare issue codes are unchanged. This is numerical
regression evidence, not an OOS football cohort or fitted calibration.

31 alternating warm timing pairs, same host and inputs:
projection 0.324->0.353 ms, median paired delta +0.025 ms;
default sports prepare 23.578->24.650 ms, median paired delta +1.093 ms.
The accuracy fix has a small measured cost. An extra full-cell summation
pass was removed before the final measurement. Timing is descriptive;
no whole API/DB/decision speed improvement or production SLO is claimed.

Reproduce with two disposable local checkouts:

```bash
python -m unittest discover -s tests -p 'test_probability_summation_v51.py' -v
python -m unittest discover -s tests -p 'test_runtime_optimization.py' -v
python scripts/probability_summation_benchmark.py --baseline-root /path/to/pr47
python scripts/verify_release.py
```

BLOCKED / PROPOSED: genuine permitted source evidence, a coherent joint
calibrator, new predeclared unseen holdout and market-specific performance
remain separate work. This repair establishes no predictive-quality,
profitability or monetary permission. No provider/API, production, migration,
main merge, historical fit, private data publication or additional agents.
