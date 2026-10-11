# SEFIROT — FootyStats Premium CSV trial, 2026-10-11

Status: **SHADOW_ONLY / MANUAL_SAMPLE_PATH / NO_PREMIUM_PURCHASED**.

## Official free CSV test

The actual FootyStats public download page states that registered login is
needed for most league CSV files, BUT offers five **free sample** downloads
for English Premier League 2018/2019:

- https://footystats.org/download-stats-csv
- **Match Stats CSV**: https://footystats.org/c-dl.php?comp=1625&type=matches
- League: https://footystats.org/c-dl.php?comp=1625&type=league
- Teams: https://footystats.org/c-dl.php?comp=1625&type=teams
- Team Pt.2: https://footystats.org/c-dl.php?comp=1625&type=teams2
- Players: https://footystats.org/c-dl.php?comp=1625&type=players

The linked CSV **text** and real header (64 columns) were inspected via
public web source `c-dl.php?comp=1625&type=matches`. First rows include
Manchester United–Leicester City (2:1, 2:5 corners) and
Newcastle United–Tottenham Hotspur (1:2, 3:5 corners), consistent with the
previously inspected public JSON FootyStats sample for the same EPL season.

The full binary CSV could not be downloaded into the development container due
to disabled outbound DNS access; therefore **full 380-row CSV import is not
claimed to have actually run**. The public API JSON for EPL 2018/19 was separately
checked: 380 unique matches, goals and corners on 380, xG on 380; a distinct
format and a different, previously verified test. Do not conflate the two.

## What this trial builds

- `research/provider_compare/footystats_csv.py`: read-only CSV parser.
- `scripts/footystats_csv_probe.py`: manual offline CLI, new summary file only.
- `tests/test_footystats_csv.py`: synthetic documented-header and adversarial
  regressions, not real-user Premium output.
- No automated CSV download. FootyStats states: automated data downloads should
  use their API, rather than automated access to the CSV download page.

CSV column groups observed in the free match example: kickoff timestamp,
status, team *names* (NO stable provider team/fixture IDs), regulation goals,
FT corners, half-time goals, shots, cards, postmatch xG, pre-match-labeled
statistics, and various odds. The source's descriptive "Home Team Pre-Match xG"
and "Pre-Match PPG" columns are **NOT** proof of historical point-in-time
availability; the same export has final full-season team averages (`home_ppg`),
which would cause leakage if used naïvely in old backtests. Odds values likewise
lack source bookmaker, first-quote time and closing quote receipt.

The parser deliberately excludes odds, team full-season aggregates, xG and
prematch-labeled fields from its per-match research candidate. It captures only
raw counts (goal and corners) as descriptive observations and stamps first
observed-at **today**, never the match date. Local hashed IDs are only CSV
synthetic identities; do not join to existing API-Football IDs by name.

## Manual reproducible proof

Open FootyStats CSV download link in a browser, save the **free sample Match CSV**
locally. No Premium purchase needed. In checked-out feature branch, choose the
true timestamp when you actually downloaded it:

```sh
python scripts/footystats_csv_probe.py \
  --input /private/epl_2018_19_matches.csv \
  --season 2018/2019 \
  --received-at 2026-10-11T07:00:00+00:00 \
  --expected-matches 380 \
  --output /private/epl_2018_19_csv_check.json
python -m unittest discover -s tests -p test_footystats_csv.py
python scripts/verify_release.py
```

The `--received-at` above is a syntax example, NOT a claim of historical
capture. Change it to actual capture time. The report contains count, coverage,
SHA256 and blockers and no raw CSV rows.

## Premium economics / access

Official pages:
- https://footystats.org/premium
- https://footystats.org/download-stats-csv
- https://footystats.org/buy-csv-credits
- https://footystats.org/terms-and-conditions

At time of review, Premium plan displayed roughly GBP 19.99 monthly (check
checkout); official terms and credit store state **100 credits per month**,
**one CSV per credit**, with add-on credits optionally purchasable. Downloads
are grouped by league/season and type. Four to five file types per league can
consume several credits; first test **Match CSV alone**. Premium membership
does NOT grant API-key entitlement. Most CSV require login/subscription and
cannot be tested in this environment without the subscriber's account.
Avoid automated scraping or requests that breach the provider's terms.

## Acceptance before subscribing or importing into models

1. Test **current-season** downloads for 3-5 actually relevant leagues and
   declared season/profile, counts, missing goal/corner fractions.
2. Obtain provider's written permission for use/retention in private modeling
   if license is ambiguous; never commit raw CSV or publicise bulk dataset.
3. Explicit team/fixture identity mapping to original archived providers, no
   name-only collisions or mistaken cup vs league matches.
4. TRAIN/CALIBRATION may only use match result *labels* and features that can
   be reconstructed from earlier eligible events; no full-season averages,
   final match xG, hindsight prematch features or self-declared time as proof.
5. Pre-register a genuinely new future HOLDOUT, collect immutable pre-kickoff
   prediction/line receipts, and compare matched Brier/log loss. No hindsight
   reuse of the 380 old viewed EPL matches as new holdout.
6. Confirm provider corners/cards coverage for desired leagues, not just EPL.
7. Don't buy Premium/API, deploy, alter BASELINE or promote monetary authority
   until separate explicit action and verified forward evaluation.

**Verdict:** Free Match CSV is an excellent manual *format* and *history*
candidate; subscription cost is not justified until current leagues and
time-provenance restrictions are resolved. **KEEP_SHADOW**.
