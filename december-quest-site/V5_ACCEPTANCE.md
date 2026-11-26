# SEFIROT DECEMBER QUEST V5 — Acceptance and deployment
Date: 2026-11-23 (Europe/Kyiv)

## Scope and isolation
- Static frontend: Vercel project `sefirot-december-quest-2026`, https://sefirot-december-quest-2026.vercel.app/
- Independent repository branch: `feature/december-quest-web-v3-20261123`. Canonical SEFIROT model/main/render processes NOT modified.
- Private cloud record: Supabase `public.sefirot_december_quest_saves`, user-owned by existing RLS. V5 evidence in `payload.intel.cards`; validated by app sanitizer.
- Public curated fixtures: `public.sefirot_december_quest_fixtures`, 114 fixtures, 25 dates, 98 officially-confirmed, 15 provisional, 1 conditional as of release. 21:00–23:00 Kyiv time.

## New V5 modules
- AI Scout: selected scheduled fixture, provenance, manual xG/xGA, lineup, injuries, tactical fit, public trap, death-test and notes. No unsupported auto-generated probabilities.
- Match Arena 2.0: fact-based comparisons and existing optional game-OVR radar.
- Weak Leg Detector: independent model probability, implied probability, conditional EV (subtracts cost only once), correlation and Referee Gate warnings.
- CAP vs SEFIROT: existing original/alternate/actual comparison plus prospective Brier score from sealed snapshots before kickoff; returns and halves excluded.
- Hypothesis lab: registered exploratory rule "busy" = at least five evening fixtures; not a causal claim.
- Career: existing XP, completed tour achievements, sealed scouting entries and calibration sample size.
- Operations: fixture freshness flag, source rechecking discipline, no sportsbook integrations.
- Separate December fixture-change automation enabled for 1–31 Dec; daily at 18:30 Europe/Kyiv. Notifications on confirmed changes or blockers; no private journal / model mutations.

## Verification completed
1. All 5 inline JavaScript blocks and three V5 external JS sources parsed successfully; V4 fixture module parsed successfully.
2. Deterministic calculations: 2-leg EV, implied P, correlation block, missing P, paid/unpaid PASS, strict YC gate, sealed Brier, refunds excluded, late snapshot exclusion, URL validation and readiness gating.
3. All seven V5 UI route functions rendered in synthetic runtime.
4. Form state transitions tested: research edit => private store => local sealed snapshot => no edits => click to add an empty-odds fixture leg to a draft.
5. Data sanitizer tested for repeated round-trip persistence of new private intel and existing tours.
6. Vercel deployment READY; HTML, JS and CSS each 200 OK.
7. Live browser rendering checked with Firecrawl: `#scout` shows Inter–Genoa (Dec 1, 22:00 Kyiv), actual source and 0/7 evidence; `#weak` shows N/D and PASS without a coupon.
8. Supabase verification: two initial draft scouting entries added to cloud (Inter–Genoa; Coventry–Ipswich), no fabricated xG/P/odds; original 1 December tour preserved.
9. Existing RLS remains enabled. No secret/service-role key embedded into static frontend.

## Known limits
- "AI Scout" auto-loads fixture metadata/provenance; live xG/lineups/fitness requires a licensed and verified data source or user-supplied research. It is not an autonomous prediction engine.
- Browser interaction was tested in a synthetic runtime; the full mobile account session, cross-device pull/merge and end-user save have not yet been tested on the user's Android.
- Calendar is not all world football; fixtures may move and 16 entries require checking. Nightly monitor's first real run has not executed yet.
- Vercel deployed as isolated inline-file production, not auto-linked Git CI; follow-up changes require manual release.
- This is a paper-only QA environment; no real bets or financial actions.
