# Open pull requests at the P2 baseline

2026-11-25 UTC. GitHub returned 63 open PRs before this draft. Default branch main was `d09a8af22f0dec8c84bc203d468b913b46fc2f94`. Each row uses the base and head supplied by GitHub. Behind/ahead counts use the merge base. Conflict means git merge-tree failed for that exact pair. A clean simulated merge does not establish acceptance.

## Integration order

1. Review the December Quest work on its own branch. Validate #86 against its calendar branch, then #87 against #86, then this change against #87. Stage the additive SQL, switch the worker fleet together, replay sealed fixtures, and obtain independent acceptance before any production change.
2. For CORE, start with source and evidence review of the roots targeting main. #53 carries work from #51 and #52. Verify the contained commits before deciding whether individual ancestors need integration. Review the incremental #54 and #55 on their declared parents. #56 is a separate integration candidate with its own baseline.
3. For research and SHADOW, review each declared parent before its child. The RC base of #62 needs independent acceptance. Keep the #62 → #63 → #25 → #65 → #66 → #67 line separate from the #78 → #79 → #80 → #81 → #82 → #83 → #84 → #85 line. #78 ports the facts-first work from #77 onto a different deployment baseline. Select the intended baseline before integrating either port.
4. Resolve conflict rows on an isolated integration branch and rerun their original gate suites. Treat old update dates as a triage signal. Review each contained or patch-equivalent candidate with its owner before retiring it.

All 63 were drafts. All declared target/head pairs merged cleanly in the local simulation. No complete PR patch had the same stable patch ID as another. Thirty heads were already ancestors of a separate integration candidate, so their standalone integration may be obsolete for that target. #77 and #78 have documented functional overlap on different bases. Independent release gates still block #85 (prospective SHADOW evidence) and #86 (scheduled run and real FT acceptance); #87 and P2 depend on the selected December Quest baseline. These are acceptance blockers even with a clean merge tree.

## Inventory

“Included” identifies exact commit ancestry in a different integration stack, excluding the normal PR base chain. It makes the individual PR a candidate for redundant integration. “Active” means an independent review increment. “Blocked” marks a tree conflict. Draft status and business acceptance are separate. A closed parent is shown explicitly when one exists. Table rows link to the original evidence and discussions.

| PR | Subject | Target or parent | Head | Behind / ahead | Review disposition |
|---|---|---|---|---:|---|
| [#8](https://github.com/VolodimerT/Sefirot/pull/8) | CORE 2.4.2: audited gates, runtime optimization and readiness | `main` | `0389e1422` | 0 / 39 | Active · base review |
| [#9](https://github.com/VolodimerT/Sefirot/pull/9) | CORE 2.4.2: API-выборка, голевые билдеры и проверка прогнозов | #8 | `cde546c5b` | 0 / 50 | Active · stacked |
| [#11](https://github.com/VolodimerT/Sefirot/pull/11) | Stability reset: manual inbox panel, probability audit and atomic workflow | #10 (closed) | `6a4c7c8f4` | 0 / 268 | Active · stacked; review closed base |
| [#12](https://github.com/VolodimerT/Sefirot/pull/12) | SEFIROT ARENA v0 — 8 isolated reviewers (shadow research only) | #11 | `59c02bc5c` | 0 / 3 | Active · stacked |
| [#13](https://github.com/VolodimerT/Sefirot/pull/13) | SEFIROT ARENA v0.1 — prospective paired shadow scorecard | #12 | `19a81f961` | 0 / 6 | Active · stacked |
| [#14](https://github.com/VolodimerT/Sefirot/pull/14) | ARENA v0.2: PIT evidence firewall, market-local review and original decision alignment | #13 | `ee433953e` | 0 / 3 | Active · stacked |
| [#16](https://github.com/VolodimerT/Sefirot/pull/16) | Bet Builder Combo Lab: exact joint-goal 2/3-leg research and Stake eligibility | #15 (closed) | `503793b87` | 0 / 4 | Included in #53, #56, #78, #85; review closed base |
| [#17](https://github.com/VolodimerT/Sefirot/pull/17) | Calibration quality audit: true cohort coverage, exact bins, paired fixture metrics | #16 | `167a5b703` | 0 / 3 | Included in #53, #56, #78, #85 |
| [#18](https://github.com/VolodimerT/Sefirot/pull/18) | Calibration recovery and source-backed real fit gate (no model promotion) | #17 | `921307134` | 0 / 6 | Included in #53, #56, #78, #85 |
| [#19](https://github.com/VolodimerT/Sefirot/pull/19) | Prospective CALIBRATION: opt-in bounded multi-season FT history collection | #18 | `8a8e64ced` | 0 / 6 | Included in #53, #56, #78, #85 |
| [#20](https://github.com/VolodimerT/Sefirot/pull/20) | Add vector-first scenario post-audit research layer | #18 | `b0502b3dd` | 0 / 4 | Active · stacked |
| [#21](https://github.com/VolodimerT/Sefirot/pull/21) | Prediction Edge V3: isolated DC/SOS models and paired evaluation | #19 | `121a58014` | 0 / 1 | Included in #53, #56, #78, #85 |
| [#22](https://github.com/VolodimerT/Sefirot/pull/22) | SEFIROT Chat Bridge: canonical Python runner, Supabase durable journal + chat jobs [research] | #21 | `9b88d130e` | 0 / 19 | Included in #53, #56, #78, #85 |
| [#23](https://github.com/VolodimerT/Sefirot/pull/23) | Prediction Edge V3.1 P0: read-only original-source adapter | #21 | `67e109302` | 0 / 1 | Active · stacked |
| [#24](https://github.com/VolodimerT/Sefirot/pull/24) | V3.1: validate fixture query echo and IANA timezone before collection | #23 | `3707cbf2f` | 0 / 1 | Active · stacked |
| [#25](https://github.com/VolodimerT/Sefirot/pull/25) | CORNERS SHADOW: reuse count model on audited CORE, period-correct evaluation (Issue #60) | #63 | `6275ccd18` | 0 / 33 | Included in #56, #78, #85 |
| [#26](https://github.com/VolodimerT/Sefirot/pull/26) | ARENA 1.0: diagnostic error registry with original evidence and frozen forecasts | #14 | `c99351ca7` | 0 / 1 | Active · stacked |
| [#27](https://github.com/VolodimerT/Sefirot/pull/27) | RESEARCH: FootyStats free-trial offline provider probe and strict evidence gate | #24 | `a97fdf632` | 0 / 10 | Active · stacked |
| [#28](https://github.com/VolodimerT/Sefirot/pull/28) | RESEARCH: FootyStats Premium CSV no-cost trial and offline admission gate | #27 | `38d35377e` | 0 / 9 | Active · stacked |
| [#30](https://github.com/VolodimerT/Sefirot/pull/30) | RESEARCH: PREMATCH/LIVE situational routing and >=2.00 odds alternatives viewer | #22 | `b7266fd60` | 0 / 3 | Active · stacked |
| [#32](https://github.com/VolodimerT/Sefirot/pull/32) | V3.3 P0–P1: receipt-bound read-only situation in Chat Bridge | #22 | `e291b6c03` | 0 / 3 | Active · stacked |
| [#34](https://github.com/VolodimerT/Sefirot/pull/34) | STABILITY: AI handoff and private daily report autosave (append-only) | #22 | `7f34ec2d4` | 0 / 8 | Active · stacked |
| [#35](https://github.com/VolodimerT/Sefirot/pull/35) | V4 P0: verify original CORE chat answers and small-market readiness | #22 | `9024889b1` | 0 / 3 | Included in #53, #56, #78, #85 |
| [#36](https://github.com/VolodimerT/Sefirot/pull/36) | STABILITY P2: private Supabase daily report archive + ChatGPT save contract | #34 | `649629c9a` | 0 / 9 | Active · stacked |
| [#37](https://github.com/VolodimerT/Sefirot/pull/37) | V4 P0: offline small-market observation v2 and full-league QC contracts | #35 | `c4d249508` | 0 / 1 | Included in #53, #56, #78, #85 |
| [#38](https://github.com/VolodimerT/Sefirot/pull/38) | B1: bind saved API-Football FT statistic packets to observation-v2 QC | #37 | `f547cc4f9` | 0 / 1 | Included in #53, #56, #78, #85 |
| [#39](https://github.com/VolodimerT/Sefirot/pull/39) | V4.2 P0: reject impossible exposure settlement receipts; freeze UTC risk day | #37 | `17a6c2a6b` | 0 / 3 | Included in #53, #56, #78, #85 |
| [#40](https://github.com/VolodimerT/Sefirot/pull/40) | API-Football: safe single-request account status probe (no credential in Git) | #37 | `89873881f` | 0 / 4 | Active · stacked |
| [#41](https://github.com/VolodimerT/Sefirot/pull/41) | V4.3 P0: audit original risk rows through read-only Repository and Service | #39 | `5a4b1d9a4` | 0 / 1 | Included in #53, #56, #78, #85 |
| [#42](https://github.com/VolodimerT/Sefirot/pull/42) | V4.4: preserve sanitized gateway evidence on one tested source/risk stack | #41 | `6c7b6d152` | 0 / 3 | Included in #53, #56, #78, #85 |
| [#43](https://github.com/VolodimerT/Sefirot/pull/43) | P0: reserve one shared API-Football budget across gateway runners | #42 | `ec91a4a80` | 0 / 4 | Included in #53, #56, #78, #85 |
| [#44](https://github.com/VolodimerT/Sefirot/pull/44) | API-Football Enrichment V1: standings, stats, events, H2H, coaches + quota-safe planning | #38 | `7a11cc3d5` | 0 / 24 | Active · stacked |
| [#45](https://github.com/VolodimerT/Sefirot/pull/45) | Preserve original forecasts and harden quotes, quota checks and ledger verification | #43 | `975b69458` | 0 / 2 | Included in #53, #56, #78, #85 |
| [#46](https://github.com/VolodimerT/Sefirot/pull/46) | Reject premature regulation FINISHED before history and feedback | #45 | `6fb99cef6` | 0 / 1 | Included in #53, #56, #78, #85 |
| [#47](https://github.com/VolodimerT/Sefirot/pull/47) | Block conflicting calibrated market probabilities before admission | #46 | `955c40946` | 0 / 2 | Included in #53, #56, #78, #85 |
| [#49](https://github.com/VolodimerT/Sefirot/pull/49) | Stabilize Poisson probability projections without weakening admission gates | #47 | `7a4d644e8` | 0 / 1 | Included in #53, #56, #78, #85 |
| [#50](https://github.com/VolodimerT/Sefirot/pull/50) | Guard research probes and preserve verifiable canonical source evidence | #49 | `5efcfa8ea` | 0 / 1 | Included in #53, #56, #78, #85 |
| [#51](https://github.com/VolodimerT/Sefirot/pull/51) | Fix gateway statistics receipt validation and preserve complete archive metadata | #50 | `ac2671294` | 0 / 2 | Included in #53, #56, #78, #85 |
| [#52](https://github.com/VolodimerT/Sefirot/pull/52) | Fix result chronology, ledger integrity and duplicate inbox processing | `main` | `c1ae595f6` | 0 / 2 | Included in #53, #56, #78, #85 |
| [#53](https://github.com/VolodimerT/Sefirot/pull/53) | Integrate CORE 2.4.2 with audit fixes and isolated PostgreSQL CI | `main` | `1e3936ca9` | 0 / 175 | Included in #56, #78, #85 |
| [#54](https://github.com/VolodimerT/Sefirot/pull/54) | Fix PR53 API contracts and accelerate fresh-row integrity checks | #53 | `9744ba239` | 0 / 2 | Included in #56, #78, #85 |
| [#55](https://github.com/VolodimerT/Sefirot/pull/55) | Integrate read-only V3 source adapter with current ledger and query guards | #54 | `5b11061ac` | 0 / 1 | Included in #56, #78, #85 |
| [#56](https://github.com/VolodimerT/Sefirot/pull/56) | SEFIROT research recovery: independent fixture evaluation and source-to-CORE gates | `main` | `50e91e7ad` | 0 / 335 | Active · base review |
| [#62](https://github.com/VolodimerT/Sefirot/pull/62) | Audited offline PREMATCH source → seal → quote → original chat (Issue #58) | `release/core242-rc-issue57-20261013` | `e32fd7e7a` | 0 / 2 | Included in #56, #78, #85 |
| [#63](https://github.com/VolodimerT/Sefirot/pull/63) | Honest original-cohort evidence audit and prospective HOLDOUT plan (Issue #59) | #62 | `d5175c926` | 0 / 4 | Included in #56, #78, #85 |
| [#64](https://github.com/VolodimerT/Sefirot/pull/64) | Phone-first authenticated read-only operator cockpit prototype (Issue #61) | #63 | `ee168f8f6` | 0 / 5 | Included in #56, #78, #85 |
| [#65](https://github.com/VolodimerT/Sefirot/pull/65) | SHOTS/SOT independent count SHADOW and paired-source QC (Issue #60) | #25 | `d611c086e` | 0 / 4 | Included in #56, #78, #85 |
| [#66](https://github.com/VolodimerT/Sefirot/pull/66) | FOULS SHADOW: separate direct committed/suffered counts and honest missing data (Issue #60) | #65 | `d00446015` | 0 / 4 | Included in #56, #78, #85 |
| [#67](https://github.com/VolodimerT/Sefirot/pull/67) | Strict referee YC SHADOW gate with null unverified probability and EV (Issue #60) | #66 | `9b363914d` | 0 / 4 | Included in #56, #78, #85 |
| [#73](https://github.com/VolodimerT/Sefirot/pull/73) | C1: offline daily prematch scanner with strict PASS and provenance gates | #56 | `08246f7af` | 0 / 2 | Active · stacked |
| [#74](https://github.com/VolodimerT/Sefirot/pull/74) | C2: offline Day Bundle Qualification, Kyiv day and source lineage | #73 | `f5d8bede5` | 0 / 1 | Active · stacked |
| [#75](https://github.com/VolodimerT/Sefirot/pull/75) | P0: stop API-Football probe queue on gateway failure | #74 | `caba6d63f` | 0 / 3 | Active · stacked |
| [#77](https://github.com/VolodimerT/Sefirot/pull/77) | Facts-first market review with honest C/D classes and quarter-line research math | #75 | `c7e6d193a` | 0 / 4 | Overlapping implementation · #77/#78 port |
| [#78](https://github.com/VolodimerT/Sefirot/pull/78) | Prepare facts-first review on deployed baseline | #11 | `72f8018e0` | 0 / 2 | Overlapping implementation · #77/#78 port |
| [#79](https://github.com/VolodimerT/Sefirot/pull/79) | Research market intelligence and fail-closed express review on live baseline | #78 | `84dce563f` | 0 / 3 | Active · stacked |
| [#80](https://github.com/VolodimerT/Sefirot/pull/80) | Fix express correlations and verify saved prematch day offline | #79 | `dbf32996c` | 0 / 1 | Active · stacked |
| [#81](https://github.com/VolodimerT/Sefirot/pull/81) | Fix postponed and quarter-line QA; route exact-build historical replay | #80 | `45889c4a5` | 0 / 1 | Active · stacked |
| [#82](https://github.com/VolodimerT/Sefirot/pull/82) | Harden historical replay and fixture chronology; verify xG lineage | #81 | `62eddbc94` | 0 / 1 | Active · stacked |
| [#83](https://github.com/VolodimerT/Sefirot/pull/83) | SEFIROT 4.4: protect historical replay and gate xG by availability | #82 | `7d8bb1e3a` | 0 / 1 | Active · stacked |
| [#84](https://github.com/VolodimerT/Sefirot/pull/84) | SEFIROT 4.5: exclude unfinished and opponent-only xG; verify prospective seal gates | #83 | `8346bb454` | 0 / 1 | Active · stacked |
| [#85](https://github.com/VolodimerT/Sefirot/pull/85) | SEFIROT 4.5 S1 — prospective SHADOW pipeline and scorecards | #84 | `0fae05487` | 0 / 3 | Active · stacked |
| [#86](https://github.com/VolodimerT/Sefirot/pull/86) | December Quest V6.3 — staging acceptance | `feature/december-quest-web-v3-20261123` | `bc7676e6d` | 0 / 14 | Active · base review |
| [#87](https://github.com/VolodimerT/Sefirot/pull/87) | Reuse score grading across 68 markets and parse each season CSV once | #86 | `e2762b78e` | 0 / 1 | Active · stacked |

Each row is a proposed review disposition. No prior PR was closed, retargeted or merged.
