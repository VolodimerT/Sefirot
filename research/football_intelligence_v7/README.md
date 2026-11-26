# SEFIROT V7 — Football Intelligence P0 (research only)

Base: 320b5507aa2eca79a4fe73175258c77eff23c31a (PR #92). No production, Policy, cron, database, site or SHADOW change. No money authority. Do not merge or activate this draft. No paid API calls.

## Observed constraints (read-only)
26 Nov 2026, December Quest auto_forecasts, kickoff > now(): 114 rows, 60 MODEL_ONLY, 54 UNSUPPORTED_LEAGUE, all PASS. 98 confirmed kickoff (44/60 modeled), 0 confirmed lineups, 0 verified fit, 0 verified prices, 0 ELIGIBLE odds-window rows. No coverage percentage for empty odds window. Model rows: EPL 26, Ligue1 12, SerieA 11, LaLiga 8, Bundesliga 3. Unsupported UCL 14, UEL 9, UECL 26, Coppa 5. These are current evidence flags, not proof of missing provider capabilities.

Source: december-quest-site/autonomous/markets.js derives 68 goal-based variants, supports settlement distribution and evaluateQuote; v5-core.js scenario multiplies entered p and decimal odds, independent() checks unique match aliases/IDs, plus manual review. This binary display proxy is not a complete Asian settlement distribution or empirical independence proof. Do not conflate this with the shared admission gate, which currently authorizes only PASS.

## P0 reference
Run: node research/football_intelligence_v7/settlement_reference.mjs
12 synthetic assertions executed for the same function definitions in an isolated JS runtime before upload (not Node CI). Example: hypothetical 45% full win, 30% push, 25% loss at decimal 2; binary proxy -0.10 vs five-grade reference +0.20 per unit. This is a synthetic mathematical counterexample, not a forecast, measured edge or recommended selection. Joint payout enumeration assumes synthetic independence only and rejects duplicate fixture IDs, missing price, invalid distributions and absent assumption. No real joint dependence model or live integration.

## P1 data contract and collection
Reuse existing source ledger, gateway, caching, shared budgets and confirmed kickoff; no new providers without authorization. Build field-level provenance/availability matrix on identical future fixture cohort. Original immutable receipts: fixture ID/competition/season, source, source observation and provider update time, cutoff, UTC kickoff, content hash, coverage/completeness and conflicts. Distinguish missing/unavailable/stale/not yet eligible/not supported. No post-cutoff data. Record quote market/line/period/rules/source/observed timestamps, only when already approved and eligible; stale or conflicting prices cannot qualify. Deduplicate requests, collect stable history incrementally, then context nearer kickoff, then lineups/referee when available. Separate historical, context, verified pricing, and final outcome receipts. Source coverage KPI: by league and field, with denominators and empty-window N/A. Do not infer actual provider calls from database flags.

## P2 market research
Reuse existing main-market and independent small-market modules. Model cards separately from foul counts (Referee Gate). No derived corners/shots/fouls from goal grid alone. Team/period context, opponent-specific style and scenario hypotheses are marked unverified until original pre-match evidence. Compare against fixed baseline on paired identical chronological fixtures; no lookahead, no tuning on holdout. Record missing-data PASS and market-specific failure modes. No expansion to production.

## P3 portfolio evaluation
Virtual only. Compare preregistered single/2/3-event research strategies and abstention on same data; enumerate five-grade payouts using consistent bookmaker rules, account for uncertainty and empirical dependence. Distinct IDs are necessary not sufficient. Retain existing v21.2 gates and zero money authority; no forced candidate when evidence missing. Separate sports probabilities from price verification, use calibration and baseline comparisons before any model adoption. Track proper scores, uncertainty and coverage; do not infer edge from synthetic tests.

## Next acceptance
First recover field-level source coverage and a real chronological fixture receipt in an isolated authorized research environment. Reuse C1/C2 and existing SHADOW; no new pipeline or repeated broad audit. Then independently validate the reference against existing settle code and bookmaker rules (no external calls by this patch). Production release and physical Android acceptance remain independent. Frozen V6.3 continues unchanged.

## Реализация и результаты

Матрица, правила очереди, повторяемый replay, описание рынков и открытые условия приёмки приведены в [VALIDATION.md](VALIDATION.md). Исследовательский CLI читает существующий Repository. Эталон экспрессов и ранговый стресс работают изолированно, существующие settlement и Policy остаются без изменений.
