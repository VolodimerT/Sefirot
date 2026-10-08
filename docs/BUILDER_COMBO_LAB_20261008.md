# SEFIROT Bet Builder Combo Lab v0.2 — 08.10.2026

STATUS: SHADOW RESEARCH ONLY. New standalone script and tests based on PR #15 (Stake Market Atlas). No changes to src/sefirot, original Policy, seven MODEL_MODULES, canonical CLI, main market pool, ledger or Money Gate.

## What is implemented

**Step 1 / FREEZE (no prices).** The command python scripts/builder_combo_lab.py freeze ORIGINAL_PREDICTION.json --at ISO_TIMESTAMP --sizes both --output FREEZE.json checks the original capture hash, Policy/model/build, runs existing sports grid reproduction, and predeclares 16 push-free goal selections. Complete 2/3-leg enumeration has 120 pairs + 560 triples = 680 attempts. Invalid contradictions and redundant implied legs are separately counted. No market-price information determines the palette or pruning.

Predeclared palette: 1X2 HOME/DRAW/AWAY, DC 1X/X2/12, BTTS YES/NO, TOTAL OVER 1.5/2.5 and UNDER 2.5/3.5, TEAM_TOTAL HOME/AWAY OVER 0.5/1.5. Existing builder_contract enforces exact rules and rejects integer PUSH legs, Asian quarter lines, contradictory or implied conditions, and unsupported different-fixture combinations.

For each valid combination, the joint probability P(all legs win) sums exact win cells in the SAME full-time score distribution. It never multiplies marginal probabilities. A product is included ONLY as a diagnostic of dependence gap. The report retains raw score-branch contributions and four fixed lambda stress scenario probabilities, all uncalibrated and research-only. Explicit original selection constraints propagate as blockers. stake_joint_odds, builder_ev and execution remain null/false. stake=0.

**Step 2 / INSPECT (Stake snapshot after freeze).** The command python scripts/builder_combo_lab.py inspect FREEZE.json ORIGINAL_STAKE_SNAPSHOT.json --output INSPECTION.json matches each frozen leg to exact Stake outcome ID and market ID in an original hash-checked, prematch, same-fixture snapshot. If and only if market status is active/open and the individual outcome has active=true and customBetAvailable=true, mark that individual leg as flagged. Even if all legs are flagged, this does NOT mean Stake accepts their combination. There is no confirmed SGM compatibility endpoint or joint quote in this implementation; no multiplying individual odds, no synthetic quote, EV=null.

Stake published rules say: if ANY selection of one Same Game Multi is void, the WHOLE SGM is void (https://stake.com/policies/sportsbook). The research script therefore rejects PUSH/void-dependent contracts until settlement and repricing behavior can be independently verified. Stake's SGM overview: https://stake.com/th/blog/same-game-multi-bet-builder .

## Further research

- mixed combinations GOALS+CORNERS, GOALS+SHOTS, GOALS+SOT, GOALS+FOULS, GOALS+YELLOW_CARDS, GOALS+PLAYER_PROPS, CORNERS+CARDS are inventoried but UNMODELED; joint P and EV are null. Goals and cards are not independent by default.
- referee-dependent markets need referee assignment and YC/game, YC/foul evidence. Fouls are not automatically cards.
- subsequent step requires a verified READ-ONLY bookmaker SGM quote/compatibility contract with full constituent selection IDs and quote/receipt timestamps; no betslip creation or live execution.
- validate true provider semantics including 90-min regulation, cancelled/void, alternate line, Asian PUSH and player substitution rules before any pricing.
- run a complete predeclared prospective test with original SEFIROT decisions, zero cherry-picking, missing data counted, calibration/holdout and abstention costs tracked; no real-money approval.

## Commands

From repo root, Python 3.11+, using real timestamps and existing original files:

    python scripts/builder_combo_lab.py freeze data/prediction.json --at REAL_PREMATCH_ISO_TIMESTAMP --sizes both --output data/builder_combo_freeze.json
    python scripts/stake_market_atlas.py harvest --prediction data/prediction.json --output data/stake_snapshot.json --atlas data/stake_market_atlas.json
    python scripts/builder_combo_lab.py inspect data/builder_combo_freeze.json data/stake_snapshot.json --output data/builder_stake_inspection.json
    python -m unittest discover -s tests -p test_builder_combo_lab.py -v

Do not backdate a freeze or infer a real quote from a synthetic demo. The Stake snapshot must have been saved AFTER freeze and BEFORE kickoff. New output files only; no overwrites. The tool does not access network itself, does not retain token and does not modify databases.

LIMITATIONS: No new Stake real API traffic or combined bookmaker prices; offline synthetic tests do not prove advantage or profitability. Original signed/provider provenance is NOT cryptographically attested by local JSON hash. The catalog of actual Stake lines remains incomplete until real authenticated snapshots and pagination semantics are observed.
