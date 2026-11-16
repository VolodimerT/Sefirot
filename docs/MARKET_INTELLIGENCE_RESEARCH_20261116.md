# Market Intelligence research slice (16 November 2026)

This branch is based on PR #78 (`integration/facts-first-livebase-20261109`),
which already includes the two later PR #77 fixes for absent holdout releases
and mixed regulation-market express settlement. It is not deployed.

The confirmed importer defect was a mixed `totals` block containing a supported
2.5 line and an unsupported 2.25 line: the whole block was rejected. The
adapter now records each valid quarter-line outcome as
`UNSUPPORTED_QUARTER_LINE` while preserving complete supported partitions.
Malformed prices, times, teams, duplicates and incomplete lines still fail
closed. Quarter prices are **not** promoted into the CORE quote contract.

Exact-head CI also exposed an independent runner break: `ubuntu-latest` moved
to Ubuntu 26.04, while the public `actions/python-versions` manifest lists
Python 3.14.3 only for Ubuntu 22.04 and 24.04. The `tests` workflow now pins
Ubuntu 24.04 across Python and isolated PostgreSQL jobs. Python 3.14.3 remains
required; this does not skip or relax a test.

The main grid's read-only comparison now exposes separate `sport_quality` and
`bet_value` axes. It never derives a sport score from price or treats raw model
EV as verified value. Its `C/PASS/stake=0` admission remains unchanged.
`OFFSIDES` may be reviewed as a source-bound full-time count in the existing
small-market laboratory. Defensive line, runner roles and tactical mechanism
are explicitly missing, as are the corresponding factors for other small
markets. All small markets remain SHADOW.

`quarter_lines.review_independent_express` checks two or three distinct
fixtures against the original sealed grid and quote receipt. It calculates
PUSH-aware raw expected gross under an **unverified independence assumption**
and compares it with the best predeclared single-leg raw diagnostic. Shared
teams, league, match day, cross-bookmaker prices and synthetic inputs are
reported as risks. The product of full-win odds is a diagnostic, **not** an
accepted bookmaker combined price. Validated probability and EV stay null;
decision is always PASS. Same-fixture legs continue through the existing
joint-score-cell builder, which lacks a real combined quote and calibration.
The offline `simulate_express` remains the settlement test for half wins and
losses; it does not imply that a bookmaker accepts the ticket or settles it by
the assumed rule.

`research_projection.match_research_view` is a read-only data contract for a
future authenticated Android API. It recomputes the sealed comparison before
returning fixture, facts, market cards, price review and PASS reasons. No HTTP
route, public access or write path has been added. An eventual endpoint needs
authentication, role-scoped authorization, rate limiting and private storage
review before deployment.

Independent acceptance:

1. Run `PYTHONPATH=src:tests python -m unittest tests.test_market_expansion tests.test_quarter_lines tests.test_small_market -q`.
2. Run `python scripts/verify_release.py`; inspect `replay_matches` and journal
   integrity in `reports/RELEASE_CHECK.json` (generated, not committed).
3. Check exact-head GitHub `tests` and `shared-provider-budget` workflows.
4. Confirm no production deployment, provider requests or database writes.

Supabase metadata on 16 November showed 485 `sports_archive` rows, zero
`predictions` and zero `decisions`; this is **not** a complete source-integrity
audit or a prospective validation cohort. Genuine match-specific xG, lineups,
injuries, bookmaker combined prices, independent small-market calibration and
prospective holdout remain unverified. No positive EV, CLV or profitability
claim follows from these synthetic tests or archival row counts.
