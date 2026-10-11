# SEFIROT situational dispatcher V1 — research only

PR base: `feature/chat-sefirot-bridge-20261010` (#22). Date: 2026-10-11.

## Present engineering scope

- New `research/situational_v1.py`: **explicit PREMATCH / LIVE_RESEARCH / POSTMATCH_RECAP / HOLD** on exact fixture and status chronology.
- PREMATCH always retains the existing canonical sealed prediction and its Policy. On kickoff or stale fixture status, refuse an old prematch quote rather than switching to an invented LIVE model.
- LIVE currently **has no fitted outcome model or independently calibrated in-play probabilities**. Mode LIVE_RESEARCH only displays the existence of a fresh in-play status; no live odds screen, no advice, no stake, no pre-match fallback. Full implementation is a separate Work milestone.
- Time-aware view depth: imminent prematch (<=20m) or live => FAST; early prematch => DEEP; caller may request FAST but cannot force DEEP when imminent. The 2s/12s numbers are **SLO design targets only, not measured latency**; no external calls, caching, async stages, or performance acceleration are part of this PR.
- `screen_alternatives`: read-only **view** of the already validated `sefirot.market_grid.compare_grid` result, up to 3 distinct market families and odds **>= 2.00 inclusive**. Candidate needs exactly one eligible fresh price observation (<=120s), bookmaker, line ID, no scenario conflict. It returns observed research candidates with `monetary_permission=false`, never a forced BET. If all missing/stale/sub-2.00 it says NO_VERIFIED_ALTERNATIVE, never fabricates a price.
- **Not an input validator**: a caller forging a JSON comparison could create counterfeit research observations. Production must require canonical `compare_grid` invocation with the original sealed prediction, exact provider quote receipt, fixture ID, bookmaker and market mapping before any display. A local SHA alone does not authenticate the source.
- No candidate selection on LIVE, no Bet Builder multiplication, no claims of positive long-term EV, no source restoration or payments. Existing BASELINE, ledger, identity fingerprints and web service untouched.

## Usage for local research (not live REST)

```python
from research.situational_v1 import route_fixture, screen_alternatives

route = route_fixture({
    "fixture_id": "api-football:fixture:123",
    "kickoff": "2026-10-11T15:00:00+00:00",
    "status": "NS",
    "status_received_at": "2026-10-11T13:00:00+00:00",
    "source_id": "api-football",
}, at="2026-10-11T13:00:20+00:00")
# comparison MUST come from canonical compare_grid on an existing valid
# frozen sports prediction and actual provider odds receipt.
result = screen_alternatives(comparison, route, min_odds=2.0)
```

This is *illustrative*, not a real fixture or price. The module never sends
network requests or creates bookmaker odds.

## Engineering stop gates and acceptance

1. Respect effective stage: sports-only PREMATCH uses existing Service; LIVE must use independent in-play data model and separate provider contract. Where blocked, respond `HOLD` with a reason.
2. Exact sportsbook, event ID, fixture identity, phase, period, settlement rules, provider timestamp and original quote receipt mandatory in integrated production. One line = one bookmaker/time, no cross-book synthesis.
3. If original targeted match has no eligible >=2.00 line, display `NO_VERIFIED_ALTERNATIVE`. Do **not** increase odds via parlays, alternate odds providers, unsupported corners, fabricated thresholds or bookmaker margin interpretations. Other fixture suggestions must have their own prospective sealed forecast.
4. Bound requests/retries: provider account is currently not proven restored (last `PROVIDER_ACCOUNT_SUSPENDED` 2026-10-06); no new API-Football calls.
5. Pipeline performance requires measured p50/p95 and tracing of network/provider, queue wait, data normalize, CORE, ARENA, rendering, with testable budgets for FAST/DEEP. A numerical SLO field alone does not make calls faster.
6. CI must pass Linux/Windows Python 3.11/3.13. Tests are all synthetic, no claim of live quality/real odds edge.
7. Price >=2.00 is a display/filter preference **not** a positive EV guarantee; minimum odds required by the existing CORE's conservative EV/uncertainty gate may be higher and may be undefined. All gates must run independently before any betting recommendation.
8. `main`, existing worker, API-Football key, Stake and any service not touched. Production rollout is explicitly not authorized.

## Work next milestones

- P0: inventory actual active Render service, deployed branch, Supabase durable queue; preserve old v2.4.2 API behavior and resolve draft PR branch ancestry.
- P1: build typed entrypoint/response schema for `GET situation`, explicit status source/timestamp/cutoff, cold cache, no process startup fetch, rate-limit-safe.
- P2: FAST/DEEP progressive orchestration with cache only for immutable trusted observations, asynchronous optional enrichment and actual tracing; measure true p50/p95 on identical scenarios with network waits included.
- P3: canonical preview for <2.00 rejection and >=2.00 ranked alternatives per exact market with valid source, line, period and no blocked original scenario. Distinguish snapshot-verified research card from an actually admitted candidate; support 0 valid alternatives.
- P4: separate LIVE research data contract and historical archive with live score, minute, red cards, current lineups, timestamps and coherent status; never use future data. Do not expose betting picks until independent walk-forward fitted live model and specific live market settlement validated.
- P5: user presentation (RU): `РЕЖИМ`, `ЧТО ПРОВЕРЕНО`, `ВЕРДИКТ`, `АЛЬТЕРНАТИВЫ >=2`, `ЧЕГО НЕ ХВАТАЕТ`, `КОГДА ОБНОВИТЬ`, `ОДНА СЛЕДУЮЩАЯ ОПЕРАЦИЯ`. No long reasoning pasted as critical-path output.
