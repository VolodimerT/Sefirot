# CORNERS_SHADOW_V0.1 — corner data coverage and frozen evaluation (11 Oct 2026)

**Branch:** feature/corners-shadow-v0-20261011
**Review:** PR #25 into feature/stability-reset-20261005
**Deployment:** NONE. Canonical CORE 2.4.2, scores, official PASS/DECIDE, bookmaker API, Supabase queue and betting ledger are unchanged.

## Verified source survey

| Source | What is publicly observable | What is missing/blocked |
|---|---|---|
| Footiqo Primera A corners and cards, Colombia 2026 | 25 public match rows with FT and 1H/2H corners on the index page, 20 clubs visible | Full historical extract is not supplied in the public snapshot; full dataset/export has separate availability terms; matchDate timezone and historical publication timestamps are not documented |
| Colombia.com 2026 results | 324 historical league matches with goals before target fixture; suitable for goals CORE | Does not provide team FT/1H corner counts and original publication timestamps |
| TotalCorner Primera A | Public league result rows with goals, full and half corners | Explicit contact/usage terms for personal/business use; cannot treat bulk extraction as licensed unrestricted dataset |
| ProBettingHub Primera A | League-wide 2026 summary: 325 matches, mean 9.0 corners, over8.5 in 53%, over9.5 in 41% | Not a match-by-match 1H/FT dataset, no matched pre-match lines or captured-at records |
| FootyStats Colombia datasets | 324/394 league matches in a documented public view, 2026 season; lists match CSV/API | Registered/paid access may be required; cannot assert data acquired |

**No verified and appropriately usable COMPLETE corner dataset has been acquired.**
This PR MUST NOT claim a real 100-match holdout, a live predictive edge, or an approved bookmaker recommendation.

## New code beyond v0

- `src/sefirot/corners_dataset.py`: explicit Footiqo-format CSV adapter; home/away FT and half corner contract, season/date/year validation, exact FT = 1H + 2H, duplicate ID check, full source SHA-256, configurable timezone, no future/unfinished rows and immutable source acquisition time.
- **Non-negotiable timestamp rule:** the `matchDate` is the match kickoff; it cannot be used as `available_at`. The importer assigns `available_at=acquired_at` (when the archive was actually obtained). This correctly blocks fake historical backtests on newly obtained archives.
- `coverage_report` compares to an independently verified, pre-harmonized expected fixture manifest. Without the manifest it returns `COVERAGE_UNKNOWN` and `monetary_permission=false`; user-supplied `source_accepted` is a research readiness condition, not a real edge certificate.
- `src/sefirot/corners_holdout.py`: frozen train/test cutoff, fixture-specific predictions from training data only, Asian push handling, historical-rate benchmark from TRAIN ONLY, Brier/log loss and baseline comparison, calibration bins and Wilson intervals, evaluated match IDs and skipped counts. No holdout retuning. No value claims, no odds/CLV proxy.
- `tests/test_corners_dataset.py` and `tests/test_corners_holdout.py`: 12 new synthetic-only contract tests, in addition to nine original model tests; original fixture generator corrected to vary visiting corners.
- Both new modules are **not** imported by canonical `src/sefirot/engine.py`, `service.py` or `scripts/chat_gateway.py`; experiment cannot trade.

## Exact research-only workflow

1. Secure **permission/license** to use a complete historical per-fixture dataset with FT+1H home/away corners (and competition IDs).
2. Independently verify source's matchDate timezone and exact source acquisition timestamp. Do not infer `available_at=kickoff+4h` for a retroactively downloaded file.
3. Normalize known historical team names, validate all match IDs against a separate complete league fixture manifest, inspect missing values and corrections.
4. Use `load_footiqo_csv(path, acquired_at=..., fixture_timezone=..., league=...)`; FAIL CLOSED if any corner half is inconsistent, missing, late or unverified.
5. For **future** model predictions, use the archive only AFTER its acquisition timestamp; leave any before-acquisition backtest excluded.
6. To evaluate historical data legitimately, obtain **source-timestamped original match snapshots** that prove scores and corners were known before every evaluated training cutoff. If unavailable, collect prospective results and defer independent validation.
7. Freeze model, source manifest, hyperparameters, target markets and date cutoff BEFORE an untouched holdout of >=100 independently eligible matches. Compare with TRAIN league baseline and timestamp-matched no-vig closing odds; report calibration and confidence intervals by market family.
8. Report edge only after a separate evaluation of out-of-sample EV, reference line time/quality, confidence bounds and risks; until then default PASS.
9. Bet Builder corners x goal probabilities require validated JOINT distribution. Do not multiply marginals.

Test command:

~~~bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_corners_*.py' -v
~~~

**Status:** Research implementation and synthetic unit tests; full historical data and independently verified edge remain blocked. 
