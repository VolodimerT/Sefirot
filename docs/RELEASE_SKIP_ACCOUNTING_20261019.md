# Release evidence: passed and skipped tests

`scripts/verify_release.py` previously parsed unittest's `Ran N tests` line and
printed `N/N` as successful, even when the suite explicitly skipped tests.
The known integration baseline ran 1,632 tests, including nine skips: 1,623
executed successfully. This was an evidence-reporting defect, not nine failures.

The release gate preserves its legacy `tests` total, adds `tests_passed` and
`tests_skipped`, and prints all three counts in its Markdown report. It refuses
missing, ambiguous, zero or inconsistent successful summaries. The subprocess
exit status still gates the release before summary parsing.

Regression tests invoke the real release entry point with isolated temporary
reports and controlled subprocess results. They cover the skipped-suite artifact,
a suite without skips, and invalid evidence. Against the old implementation the
corrected regression fixture fails; all three methods pass after repair.

The first combined-candidate Windows CI exposed two portability errors in the
new test harness: implicit locale decoding of the UTF-8 report and a global
`subprocess.run` patch intercepting Python 3.11's Windows platform detection.
The test now reads artifacts explicitly as UTF-8 and replaces only the release
module's subprocess adapter, preserving the real platform module's subprocess.
Both failed Windows runs remain evidence; they are not reported as successful.

This changes technical-build evidence only. Demo and synthetic backtest output
remain explicitly non-certifying. No new real-data model qualification is claimed.
