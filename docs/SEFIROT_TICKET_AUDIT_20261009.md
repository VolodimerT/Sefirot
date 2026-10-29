# SEFIROT — аудит 09.10.2026 (reported settlement screenshots)

**Evidence:** seven Parik24 screenshots + user-confirmed 2300 UAH starting bank, 2843 UAH ending bank, and 150 UAH stake on #3027. These screenshots establish ticket settlement but NOT the accuracy of SEFIROT forecasting, which requires original sealed prematch probability vectors and immutable source receipts.

## Source clarification (user-confirmed 10.10.2026)

**Stake originals = YARYI PROPOSALS; Parik24 settled tickets = OUR EXECUTIONS.** Do not record Parik losses under Yaryi bankroll even if inspired by the same Yaryi Stake pick. Separate recommendation correctness (Stake originals) from our Parik24 ROI, and tag OUR_COPY vs OUR_MODIFIED vs OUR_INDEPENDENT only when evidenced. Source-of-origin comparison is in docs/YARYI_STAKE_PARIK_PROVENANCE_20261010.md and the private Supabase manual_source_comparison ledger.

## Reconciliation

| Measure | UAH |
|---|---:|
| Start | 2300.00 |
| End | 2843.00 |
| Bank change | **+543.00 (+23.61%)** |
| Nine bets stake | 1300.00 |
| Payout including cashout | 1788.17 |
| Coupon profit | **+488.17 (+37.55% turnover ROI)** |
| UNRECONCILED_BALANCE | **54.83** |

Missing ticket identifier 3028 is NOT evidence of a bet. Never create a fabricated record to reconcile the difference.

## Tickets and segmentation

| ID* | Market | PRE / LIVE | Stake | Payout | Profit |
|---|---|---|---:|---:|---:|
| 3024 | Veres–Shakhtar P2 + U3.5 @1.86 | PRE | 150 | 279 | +129 |
| 3025 | Veres–Shakhtar BTTS YES @2.38 | PRE | 150 | 0 | -150 |
| 3026 | Dortmund–Werder -1.5 + corners O8.5 @2.71 | PRE | 100 | 0 | -100 |
| 3027 | Dortmund–Werder home win + corners O8.5 + home goals O1.5 @2.08 | PRE | 150 | 0 | -150 |
| 3029 | Lens–Lyon shots O25.5 + Malaga–Espanyol corners O7.5 @2.1413 | PRE | 150 | 321.19 | +171.19 |
| 3030 | Lens–Lyon shots O26.5 + Malaga–Espanyol corners O8 @2.4957 | PRE | 150 | 374.35 | +224.35 |
| 3031 | Beveren–Lommel O3.5 + West Ham–QPR X2 @2.1414 | LIVE Cashout | 150 | 247.86 | +97.86 |
| 3032 | Bray–Wexford goal #3 Bray + Athlone–Treaty X2 @1.9118 | LIVE | 150 | 286.77 | +136.77 |
| 3033 | Malaga–Espanyol cards O6.5 @1.86 | LIVE | 150 | 279 | +129 |

*IDs 3024/3026 are sequential hypotheses: top portions of original coupons cropped. 3031 is a CASHOUT (not a won multi-leg ticket). #3027 stake confirmed by user.*

PREMATCH 6: stake 850, P&L +124.54, ROI +14.65%, 3W/3L.
LIVE 3: stake 450, P&L +363.63, ROI +80.81%, 2W/1 Cashout.

## Findings / implementation backlog

- **P0** Duplicated game/scenario exposure: Dortmund–Werder tickets lost 250 UAH together. #3029/#3030 have nested shots/corners thresholds on identical fixtures: two linked wins are NOT independent evidence. Group exposure 300 UAH is 13.04% of opening bank.
- **P0** For every future fixture, seal source-backed price-blind sports, fixture and kickoff identifiers, full probability vector, policy/model hashes, quoted market and timestamps before placing any price-based decisions. No retrospective seals or fake probabilities.
- **P0** Track factor-level correlation, cross-ticket risk caps and bankroll drawdown. Flat 150 UAH is 6.52% of 2300 UAH starting bank; without validated EV this is aggressive.
- **P1** Separate PREMATCH v21.2 from 3031–3033 LIVE; include Cashout as its own settlement type. Enforce bookmaker settlement rules for shots, corners and Asian corner totals.
- **P1** For cards apply Referee Gate; winning 3033 doesn't validate referee calibration. For mixed shots/corners Bet Builder, joint model and actual combined quote are required; unknown joint EV must remain UNPRICED/PASS.
- **P2** Evaluate true prospective baseline, DC_DYNAMIC_V1 and SOS_LITE_V1 using common-match Brier/log loss/ECE, no-vig and CLV, independent HOLDOUT and coverage; no profitability claim from nine observed tickets.

## Engine connection

On 10 Oct SEFIROT CORE 2.4.2 responded to a research status job and a synthetic end-to-end job through connected Supabase private queue → Render runner → Supabase response. Durable research SQLite checkpoint restored from private Supabase snapshot revision 1 with hash verification. Original reported bets are NOT inserted as fake prior predictions. API-Football account remains blocked pending provider resolution, and DC/SOS remain shadow. The model's monetary certification remains unproven.
