# SEFIROT situational dispatcher V1 — research only

Integration update, 2026-10-13: selectively ported #32 onto #55 with the current
ledger/source/budget checks preserved. FT now requires at least 90 minutes
at the original observation. See
[SITUATION_INTEGRATION_20261013.md](SITUATION_INTEGRATION_20261013.md).
The base and test/benchmark statements below record the older prototype.

PR base: `feature/chat-sefirot-bridge-20261010` (#22). Date: 2026-10-11.

P0–P1 continuation: see [SITUATION_BRIDGE_P1_20261011.md](SITUATION_BRIDGE_P1_20261011.md).
The original PR #30 remains an archived green prototype; this branch corrects
its permissions/labels and adds the read-only dispatcher on exact PR #22.
`route_fixture` now declares `source_attestation=NOT_ATTESTED`,
`prematch_candidate` separately from `prematch_core_allowed=false`. Server
integration always uses original observation time as well as receipt time.
The local router does not authenticate input. No real source can become
eligible in P1 without a future external attestation adapter.

## Present engineering scope

- New `research/situational_v1.py`: **explicit PREMATCH / LIVE_RESEARCH / POSTMATCH_RECAP / HOLD** on exact fixture and status chronology.
- PREMATCH always retains the existing canonical sealed prediction and its Policy. On kickoff or stale fixture status, refuse an old prematch quote rather than switching to an invented LIVE model.
- LIVE currently **has no fitted outcome model or independently calibrated in-play probabilities**. Mode LIVE_RESEARCH only displays the existence of a fresh in-play status; no live odds screen, no advice, no stake, no pre-match fallback. Full implementation is a separate Work milestone.
- Time-aware view depth: imminent prematch (<=20m) or live => FAST; early prematch => DEEP; caller may request FAST but cannot force DEEP when imminent. The 2s/12s numbers are **SLO design targets only, not measured latency**; no external calls, caching, async stages, or performance acceleration are part of this PR.
- `screen_alternatives`: isolated read-only **view** of a comparison dictionary, up to 3 market families and odds **>= 2.00 inclusive**. It does not independently establish that comparison came from canonical `compare_grid`. Exactly one fresh price, string line ID and no scenario conflict required; duplicate market rows are rejected. Status is `CANDIDATES_NOT_ATTESTED` or `NO_CANDIDATE_GE_2_NOT_ATTESTED`. This viewer is NOT exposed by situation; original quote binding belongs to P2.
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
3. The prototype displays only NOT_ATTESTED candidates. A future receipt-bound P2 endpoint must use `NO_VERIFIED_ALTERNATIVE_GE_2` for an empty verified comparison. Do **not** increase odds via parlays, alternate providers, unsupported corners or fabricated thresholds. Other fixtures need separate prospective seals.
4. Bound requests/retries: provider account is currently not proven restored (last `PROVIDER_ACCOUNT_SUSPENDED` 2026-10-06); no new API-Football calls.
5. Pipeline performance requires measured p50/p95 and tracing of network/provider, queue wait, data normalize, CORE, ARENA, rendering, with testable budgets for FAST/DEEP. A numerical SLO field alone does not make calls faster.
6. CI must pass Linux/Windows Python 3.11/3.13. Tests are all synthetic, no claim of live quality/real odds edge.
7. Price >=2.00 is a display/filter preference **not** a positive EV guarantee; minimum odds required by the existing CORE's conservative EV/uncertainty gate may be higher and may be undefined. All gates must run independently before any betting recommendation.
8. `main`, existing worker, API-Football key, Stake and any service not touched. Production rollout is explicitly not authorized.

## Work next milestones

This original roadmap predates the V3.3 audit. The binding current scope is
P0–P1 status-only integration, then STOP. Its P2 is exact bookmaker receipt
binding; P3 is an independent live model. Performance/cloud rollout remain
unverified. The historical milestone numbering below does not override V3.3.

- P0: inventory actual active Render service, deployed branch, Supabase durable queue; preserve old v2.4.2 API behavior and resolve draft PR branch ancestry.
- P1: build typed entrypoint/response schema for `GET situation`, explicit status source/timestamp/cutoff, cold cache, no process startup fetch, rate-limit-safe.
- P2: FAST/DEEP progressive orchestration with cache only for immutable trusted observations, asynchronous optional enrichment and actual tracing; measure true p50/p95 on identical scenarios with network waits included.
- P3: canonical preview for <2.00 rejection and >=2.00 ranked alternatives per exact market with valid source, line, period and no blocked original scenario. Distinguish snapshot-verified research card from an actually admitted candidate; support 0 valid alternatives.
- P4: separate LIVE research data contract and historical archive with live score, minute, red cards, current lineups, timestamps and coherent status; never use future data. Do not expose betting picks until independent walk-forward fitted live model and specific live market settlement validated.
- P5: user presentation (RU): `РЕЖИМ`, `ЧТО ПРОВЕРЕНО`, `ВЕРДИКТ`, `АЛЬТЕРНАТИВЫ >=2`, `ЧЕГО НЕ ХВАТАЕТ`, `КОГДА ОБНОВИТЬ`, `ОДНА СЛЕДУЮЩАЯ ОПЕРАЦИЯ`. No long reasoning pasted as critical-path output.
