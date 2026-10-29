# V5.1: price-blind coherence admission gate

VERIFIED: independent contract bins can contradict identical events across
families, not just HOME/AWAY outcomes from a research grid. On exact #46,
controlled HOME 1X2=.80 and HOME DNB=.75 produced BET when all other gates
were represented as passed. Four of the first five regression methods
failed: base conflict, stress conflict, price/stale-diagnostic bypass and
actual contract-bin output without a conflict finding.

FIXED: `probability_coherence` derives settlement events from the existing
canonical WIN/PUSH/LOSS payoffs. It checks identical events, subset ordering,
impossible/necessary events, and min/max multiplicity of 2-3 event groups.
This detects disjoint sums, exhaustive partitions and overlapping covers.
PUSH is not treated as LOSS or conditional WIN. Prices do not enter the check.

The finite score grid represents every possible settlement signature, not
just the Poisson support. Let L=ceil(max(abs(line)))+1 and cap=2L+1. If both
scores exceed L, keep the smaller at L and retain/clamp the difference beyond
the largest difference threshold. Otherwise retain the small score and cap
the large one. Individual goals, sum, difference and BTTS settlement signs
are unchanged. All nonnegative integer outcomes therefore have a representative.
At most 16,384 grid cells / 7 markets / 16 aligned stress scenarios are checked.
Out-of-scope or mismatched stress coverage is UNVERIFIED and blocks admission.

Cache (32 entries) holds settlement relations only. Every call reads the
current probability vectors; no probability, quote, verdict or approval is
cached. Reports retain up to 16 witness violations per scenario plus totals.
Roundoff tolerance is 1e-10, not an empirical edge threshold.

FIXED: prepare records the diagnostic before the seal; decide recomputes it
instead of trusting a caller-supplied old diagnostic. Conflict/unverified
scope blocks every candidate in that pool, leaving PASS/D and zero stake.
Original P, interval bounds, raw mass, calibrator and historical records are
not changed. The user action points to MODEL_VALIDATION; a price refresh does
not resolve the block. Numerical EV may remain visible as an ineligible
diagnostic, never an admitted value signal.

TESTED: same HOME event across 1X2/DNB, draw/PUSH, DNB/AH0, half-line PUSH,
totals/BTTS disjointness, team-total containment, exhaustive 1X2, double-chance
overlapping coverage, arbitrary far-out scores, roundoff, cache mutation,
bounded refusal and stress alignment. Seven business regressions plus
17 numerical methods; full release/CI evidence in the PR/delivery report.

One old EV-ranking test used HOME=.5 in 1X2 but HOME=.25 in DNB. It now uses
one valid distribution HOME=.5, DRAW=.25, AWAY=.25; prices 2.5/2.0 keep EV=.25
for both. Its BET, chosen DNB and exact EV-tie assertions are unchanged.

LIMITATION: these are necessary local constraints, not complete marginal-
polytope feasibility, joint interval coverage or a fitted coherent model.
`joint_distribution_verified=false` even on NECESSARY_CONDITIONS_PASS.
Full coherent score-distribution calibration needs a versioned challenger,
predeclared independent data and unseen OOS validation; none was fitted here.
Model/Policy formulas are unchanged; old decisions still replay on archived
code, since the build/admission hash changes. No new money permission.

Observed separate P2: extreme Poisson lines can yield a category just above
1 through floating-point summation and raise ValueError upstream. That fails
closed before this gate. It is not normalized away by this admission repair;
a focused numerical fix and regression are still required.

No production change, provider request, migration or private ledger write.
Use a disposable checkout for release verification; generated old reports
must be restored and fresh evidence kept separately.

TESTED optimization: retain all inequalities and fsum arithmetic, replace
per-inequality generator allocations with fixed arity evaluation. Reports
matched on 100 synthetic normalized-vector comparisons and the default pool.
51 alternating warm-checker pairs on the same inputs: median 4.065→1.590 ms;
5 scenarios / 100 representative cells / 1,358 constraints per scenario.
The earlier unpaired 13 ms was not stable; no whole-pipeline speed claim.
Final local release 1,021/1,021, exit 0. Model/Policy hashes remain unchanged.
