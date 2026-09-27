"""Deterministic prematch research pipeline. Never transmits or places wagers."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from math import exp, factorial
import json

from .core import Fact, SportsOnlySnapshot, _utc
from .model import HistoricalMatch
from .markets import Market, MAIN_ORDER, probabilities, implied, payoff_ev, fair_odds, margin, settle

VERSION = "SEFIROT CORE 1.0-research"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def parse_time(value):
    dt = datetime.fromisoformat(value)
    return _utc(dt)


def _check_event(event):
    if event.get("bet_type", "SINGLE") != "SINGLE" or event.get("mode", "PREMATCH") != "PREMATCH":
        raise ValueError("live and express are disabled")
    snap = SportsOnlySnapshot(event["match_id"], parse_time(event["kickoff"]), parse_time(event["as_of"]),
        tuple(Fact(f["key"], str(f["value"]), f["source"], parse_time(f["published_at"]),
                   parse_time(f["received_at"]), f["kind"]) for f in event["facts"]))
    teams = {f.key: f.value for f in snap.facts if f.key in ("sports.home_team", "sports.away_team") and f.kind == "FACT"}
    if len(teams) != 2 or teams["sports.home_team"] == teams["sports.away_team"]:
        raise ValueError("two distinct confirmed team identities required")
    return snap, teams


def _history(event, snap):
    rows = []
    seen = set()
    for row in event["history"]:
        m = HistoricalMatch(row["match_id"], parse_time(row["kickoff"]), parse_time(row["result_received_at"]),
                            row["home_team"], row["away_team"], row["home_goals"], row["away_goals"], row["source"])
        if m.match_id in seen:
            raise ValueError("duplicate historical match")
        seen.add(m.match_id)
        if _utc(m.kickoff) < _utc(snap.as_of) and _utc(m.result_received_at) <= _utc(snap.as_of):
            if m.match_id == snap.match_id:
                raise ValueError("target match leaked into history")
            rows.append(m)
    return sorted(rows, key=lambda m: (_utc(m.kickoff), m.match_id))


def _poisson(lam, n):
    return exp(-lam) * lam ** n / factorial(n)


def _distribution(rows, home, away):
    """Transparent fixed heuristic, never claimed calibrated; tail folded into final bin."""
    def team(team):
        selected = [m for m in rows if team in (m.home_team, m.away_team)]
        goals = [(m.home_goals, m.away_goals) if team == m.home_team else (m.away_goals, m.home_goals) for m in selected]
        return len(goals), (sum(g[0] for g in goals) + 4 * 1.35) / (len(goals) + 4), (sum(g[1] for g in goals) + 4 * 1.35) / (len(goals) + 4)
    nh, ha, hd = team(home)
    na, aa, ad = team(away)
    lh, la = min(5., max(.1, (ha + ad) / 2 * 1.08)), min(5., max(.1, (aa + hd) / 2 / 1.08))
    ph = [_poisson(lh, i) for i in range(11)]
    pa = [_poisson(la, i) for i in range(11)]
    ph[-1] += 1 - sum(ph)
    pa[-1] += 1 - sum(pa)
    return {(h, a): ph[h] * pa[a] for h in range(11) for a in range(11)}, (nh, na), (lh, la)


def _quote(quote, snap, cutoff):
    market = Market(quote["kind"], quote["side"], quote.get("line"))
    timestamp = parse_time(quote["received_at"])
    if not _utc(snap.as_of) <= timestamp <= cutoff < _utc(snap.kickoff):
        raise ValueError("quote must be known before prematch decision")
    odd = float(quote["odds"])
    implied(odd)
    return market, odd


def analyze(event):
    """All timestamps are supplied; identical input and version yield identical output."""
    snap, teams = _check_event(event)
    cutoff = parse_time(event["decision_at"])
    if cutoff < _utc(snap.as_of) or cutoff >= _utc(snap.kickoff):
        raise ValueError("decision outside prematch window")
    rows = _history(event, snap)
    mass, counts, rates = _distribution(rows, teams["sports.home_team"], teams["sports.away_team"])
    reasons = []
    def veto(code):
        if code not in reasons:
            reasons.append(code)
    if min(counts) < 8:
        veto("INSUFFICIENT_TEAM_HISTORY")
    facts = snap.facts
    if any(f.kind == "ASSUMPTION" and f.key in event.get("critical_keys", []) for f in facts):
        veto("CRITICAL_ASSUMPTION")
    if any(f.kind != "FACT" and f.key in {"sports.home_team", "sports.away_team"} for f in facts):
        veto("UNCONFIRMED_IDENTITY")
    if not event.get("scenario", {}).get("thesis") or not event.get("scenario", {}).get("branches"):
        veto("SCENARIO_MISSING")
    unknown = list(event.get("novelty", []))
    if min(counts) < 8:
        unknown.append("NEW_OR_UNDEROBSERVED_TEAM")
    if unknown:
        veto("UNKNOWN_MODE")
    if not event.get("tactical_fit", {}).get("supported", False):
        veto("TACTICAL_FIT_UNCONFIRMED")
    if event.get("public_trap", {}).get("unresolved", True):
        veto("PUBLIC_TRAP_UNRESOLVED")
    if event.get("conflicts"):
        veto("CONFLICT_REQUIRES_NEW_SNAPSHOT")
    if any(state in ("WEAK", "FROZEN", "UNKNOWN") for state in event.get("health", {}).values()):
        veto("SUBSYSTEM_HEALTH")
    if not event.get("independent_holdout_validated", False):
        veto("UNSEEN_HOLDOUT_UNVALIDATED")
    if not event.get("calibration_validated", False):
        veto("PROBABILITY_UNCALIBRATED")
    recheck = event.get("recheck", {})
    if not recheck.get("lineup_confirmed") or not recheck.get("news_checked"):
        veto("RECHECK_INCOMPLETE")
    else:
        if parse_time(recheck["received_at"]) > cutoff or parse_time(recheck["received_at"]) < _utc(snap.as_of):
            veto("RECHECK_STALE_OR_LATE")
    if event.get("exposures"):
        veto("CORRELATED_EXPOSURE_REQUIRES_REVIEW")
    seal = {"model": event.get("model_version", VERSION), "snapshot": snap.digest(), "history": [m.match_id for m in rows],
            "scenario": event.get("scenario", {}), "rates": rates,
            "1x2": [sum(p for (h, a), p in mass.items() if (h > a if side == "HOME" else h == a if side == "DRAW" else h < a)) for side in ("HOME", "DRAW", "AWAY")],
            "interval_status": "UNCALIBRATED"}
    seal["digest"] = digest(seal)
    quotes = event.get("quotes", [])
    candidates = []
    for q in quotes:
        market, odd = _quote(q, snap, cutoff)
        win, push, loss = probabilities(market, mass)
        edge = win - (1 - push) * implied(odd)
        candidate = {"market": market.key, "kind": market.kind, "odds": odd, "implied": implied(odd),
                     "win_probability": win, "push_probability": push, "loss_probability": loss,
                     "fair_odds": fair_odds(win, push), "edge": edge, "ev": payoff_ev(win, push, odd),
                     "uncertainty": "UNCALIBRATED", "quote_received_at": q["received_at"]}
        branches = event.get("scenario", {}).get("branches", [])
        fragile = [b for b in branches if b.get("supports_thesis") and settle(market, b["home_goals"], b["away_goals"]) == "LOSS"]
        candidate["death_test_losses"] = fragile
        if fragile:
            veto("DEATH_TEST_FRAGILITY")
        if q.get("movement_explained") is False:
            veto("UNEXPLAINED_LINE_MOVEMENT")
        candidates.append(candidate)
    candidates.sort(key=lambda c: (MAIN_ORDER.index(c["kind"]), c["market"], c["odds"]))
    if not candidates:
        veto("NO_MAIN_MARKET_PRICE")
    if not event.get("price_groups_complete", False):
        veto("ALTERNATIVE_MARKET_CHECK_INCOMPLETE")
    if candidates and not any(c["ev"] > 0 for c in candidates):
        veto("NO_POSITIVE_EV")
    # A locally supplied calibration/holdout assertion cannot authenticate validation.
    # This release has no certified holdout and therefore never grants monetary admission.
    veto("NO_CERTIFIED_RELEASE_GATE")
    limitations = {"data": "LOW" if unknown else "MEDIUM", "model": "INSUFFICIENT", "market": "LOW" if not candidates else "MEDIUM"}
    return {"version": VERSION, "match_id": snap.match_id, "snapshot_digest": snap.digest(), "probability_seal": seal,
            "candidates": candidates, "selected": None, "alternative_market_check": "INCOMPLETE" if not event.get("price_groups_complete") else "COMPARED",
            "mode": "UNKNOWN" if unknown else "NORMAL", "unknown_reasons": unknown,
            "confidence": "INSUFFICIENT", "limiting_factors": limitations, "vetoes": reasons,
            "verdict": "PASS", "class": "RED" if any(x in reasons for x in ("CONFLICT_REQUIRES_NEW_SNAPSHOT", "SUBSYSTEM_HEALTH")) else "D",
            "stake": 0, "execution_enabled": False,
            "input_digest": digest(event), "decision_digest": digest({"event": event, "version": VERSION, "vetoes": reasons})}
