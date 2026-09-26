# SEFIROT CORE 1.0 research

Local standalone prematch analysis and audit journal based on `SEFIROT_AUDIT_FOUNDATION_v0.1.md`. It does **not** provide licensed sports feeds, calibrated monetary probabilities, or automatic bets. Every decision is PASS, even if illustrated EV is positive. See `docs/INDEPENDENT_AUDIT_CORE_1.md` for the rule-by-rule audit.

## Windows

1. Download this repository as ZIP from GitHub and extract it. Install Python 3.11+ and enable **Add Python to PATH**.
2. Open PowerShell, change into the extracted folder (`cd C:\\path\\to\\Sefirot-main`); run `py -3 test_sefirot.py`.
3. Run `py -3 SEFIROT_CORE.py examples/full_case.json --db data/research.sqlite`. The JSON result prints to screen; SQLite decision is preserved. Running the identical fixture again with the same database intentionally fails due to duplicate match ID. For a second trial use another database path or a new fixture ID.

On Linux/macOS replace `py -3` with `python3`. No external packages or API credentials are required. `run_sefirot.py demo` remains the older 1X2 quick demo; the full analysis is `SEFIROT_CORE.py`.

## Design and constraints

`src/sefirot_core/system.py` implements the fixed-order prematch pipeline; `markets.py` defines seven main-market families and push-aware payoff; `storage.py` creates 11 relational tables locally; `governance.py` tracks contextual competence and paired model comparisons. `backtest.py` holds chronological 1X2 tests. `tests/test_system.py` checks new calculation, gates, persistence and chronology. All probabilities are generated independently of odds. Generated prices include implied probability, fair odds, EV and edge. Intervals remain UNCALIBRATED pending holdout coverage. The death test checks whether the declared thesis includes a losing branch, without granting a vote on probability.

Input JSON must include a unique `match_id`, timezone-aware `kickoff`, `as_of`, `decision_at`, source-timestamped `facts` (confirmed home/away teams), historical scores with result receipt times, an analyst scenario, quote observations and recheck metadata. `examples/full_case.json` provides a deliberately weak synthetic case to exercise PASS. Do not use unverified input to make financial decisions.

This repository never places wagers and has no code path for live, express, small markets or doubling. SQLite research is self-contained. `.env.example` is empty because no secrets are needed. Production Supabase schema/connectors are not provisioned by this local build.
