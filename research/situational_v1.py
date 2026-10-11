"""SEFIROT situational dispatcher and >=2.00 research-only alternative viewer.

This module NEVER places bets or opens live betting. It cannot independently
authenticate provider snapshots. Exact odds comparison must come from
sefirot.market_grid.compare_grid, not a manually constructed quote.
"""
from __future__ import annotations

import math
import re
from sefirot.contracts import time
from sefirot.markets import market_from_key

SCHEMA = "sefirot-situational-research-v1"
LIVE = frozenset(("1H", "HT", "2H", "ET", "BT", "P", "LIVE"))
FINISHED = frozenset(("FT", "AET", "PEN"))
STOPPED = frozenset(("PST", "CANC", "SUSP", "ABD", "TBD"))
FAST_WINDOW_MINUTES = 20
PREMATCH_STATUS_MAX_AGE_SECONDS = 900
NEAR_KICKOFF_STATUS_MAX_AGE_SECONDS = 120
LIVE_STATUS_MAX_AGE_SECONDS = 30


def _hold(fixture_id, at, reason):
    return {"schema": SCHEMA, "fixture_id": fixture_id, "at": at,
            "mode": "HOLD", "depth": "NONE", "reason": reason,
            "latency_target_ms": None, "latency_target_validated": False,
            "prematch_core_allowed": False, "live_betting_allowed": False,
            "monetary_permission": False, "execution_enabled": False}


def route_fixture(fixture, *, at, intent="AUTO", detail="AUTO"):
    """Routing only; a provider status is not independent source attestation.

    No fallback from in-play to prematch. Deadline-based FAST is a presentation
    target, not a measured service-level guarantee or simplified risk policy.
    """
    now = time(at)
    if not isinstance(fixture, dict) or set(fixture) != {
        "fixture_id", "kickoff", "status", "status_received_at", "source_id"
    }:
        raise ValueError("exact fixture routing contract required")
    fid = fixture["fixture_id"]
    source = fixture["source_id"]
    if not isinstance(fid, str) or not 1 <= len(fid) <= 128 or not fid.strip():
        raise ValueError("invalid fixture_id")
    if not isinstance(source, str) or not 1 <= len(source) <= 128 or not source.strip():
        raise ValueError("invalid source_id")
    if intent not in ("AUTO", "PREMATCH", "LIVE", "POSTMATCH"):
        raise ValueError("unsupported requested phase")
    if detail not in ("AUTO", "FAST", "DEEP"):
        raise ValueError("unsupported response detail")
    kickoff = time(fixture["kickoff"])
    received = time(fixture["status_received_at"])
    status = fixture["status"]
    if not isinstance(status, str) or len(status) > 16:
        raise ValueError("invalid provider status")
    asof = now.isoformat()
    if received > now:
        return _hold(fid, asof, "FUTURE_STATUS_RECEIPT")
    age = (now - received).total_seconds()
    remaining = (kickoff - now).total_seconds()
    if status == "NS":
        if remaining <= 0:
            return _hold(fid, asof, "KICKOFF_REACHED_NO_INPLAY_CONFIRMATION")
        if intent in ("LIVE", "POSTMATCH"):
            return _hold(fid, asof, "REQUEST_PHASE_NOT_CONFIRMED")
        near = remaining <= FAST_WINDOW_MINUTES * 60
        if age > (NEAR_KICKOFF_STATUS_MAX_AGE_SECONDS if near else PREMATCH_STATUS_MAX_AGE_SECONDS):
            return _hold(fid, asof, "STALE_PREMATCH_STATUS")
        path = "PREMATCH"
        depth = "FAST" if near or detail == "FAST" else "DEEP"
        return {"schema": SCHEMA, "fixture_id": fid, "at": asof,
                "mode": path, "depth": depth, "reason": "SOURCE_REPORTS_NOT_STARTED",
                "latency_target_ms": 2000 if depth == "FAST" else 12000,
                "latency_target_validated": False,
                "source_id": source, "status_received_at": received.isoformat(),
                "prematch_core_allowed": True,  # only routing; canonical still validates evidence
                "live_betting_allowed": False, "monetary_permission": False,
                "execution_enabled": False}
    if status in LIVE:
        if now < kickoff or received < kickoff:
            return _hold(fid, asof, "INPLAY_STATUS_CHRONOLOGY_CONFLICT")
        if age > LIVE_STATUS_MAX_AGE_SECONDS:
            return _hold(fid, asof, "STALE_LIVE_STATUS")
        if intent in ("PREMATCH", "POSTMATCH"):
            return _hold(fid, asof, "REQUEST_PHASE_NOT_CONFIRMED")
        return {"schema": SCHEMA, "fixture_id": fid, "at": asof,
                "mode": "LIVE_RESEARCH", "depth": "FAST",
                "reason": "FRESH_INPLAY_STATUS_NOT_A_LIVE_MODEL",
                "latency_target_ms": 2000, "latency_target_validated": False,
                "source_id": source, "status_received_at": received.isoformat(),
                "prematch_core_allowed": False, "live_betting_allowed": False,
                "monetary_permission": False, "execution_enabled": False}
    if status in FINISHED:
        if now < kickoff or received < kickoff:
            return _hold(fid, asof, "FINISHED_STATUS_CHRONOLOGY_CONFLICT")
        if intent in ("LIVE", "PREMATCH"):
            return _hold(fid, asof, "REQUEST_PHASE_NOT_CONFIRMED")
        return {"schema": SCHEMA, "fixture_id": fid, "at": asof,
                "mode": "POSTMATCH_RECAP", "depth": "FAST",
                "reason": "RESULTS_NOT_FORECAST", "latency_target_ms": 2000,
                "latency_target_validated": False, "source_id": source,
                "status_received_at": received.isoformat(),
                "prematch_core_allowed": False, "live_betting_allowed": False,
                "monetary_permission": False, "execution_enabled": False}
    return _hold(fid, asof, "STOPPED_OR_UNKNOWN_FIXTURE_STATUS")


def screen_alternatives(comparison, route, *, min_odds=2.0, limit=3):
    """Rank at most three different prematch market families, never recommend.

    Only for an existing canonical `compare_grid` result. This function is a
    *viewer*, not a substitute for receipt verification or Policy admission.
    It deliberately returns nothing without a fresh matching comparison.
    """
    if isinstance(min_odds, bool) or not isinstance(min_odds, (float, int)) or not math.isfinite(min_odds) or not 2 <= min_odds <= 10000:
        raise ValueError("minimum decimal odds must be >=2.00")
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError("1-3 research alternatives required")
    if not isinstance(route, dict) or route.get("schema") != SCHEMA:
        raise ValueError("validated phase route required")
    result = {"schema": "sefirot-alternatives-ge2-shadow-v1",
              "fixture_id": route.get("fixture_id"),
              "mode": route.get("mode"), "odds_floor": float(min_odds),
              "alternatives": [], "status": "NO_VERIFIED_ALTERNATIVE",
              "reason": "NO_CANONICAL_PRICE_COMPARISON",
              "source_provenance": "INPUT_COMPARISON_NOT_INDEPENDENTLY_ATTESTED",
              "class": "RESEARCH_ONLY", "monetary_permission": False,
              "execution_enabled": False, "stake": 0}
    if route.get("mode") != "PREMATCH":
        result["reason"] = "PREMATCH_COMPARISON_FORBIDDEN_OUTSIDE_PREMATCH"
        return result
    if not isinstance(comparison, dict) or comparison.get("schema") != "main-market-comparison-v1":
        return result
    if comparison.get("monetary_permission") is not False or comparison.get("execution_enabled") is not False:
        result["reason"] = "COMPARISON_PROMOTION_FORBIDDEN"
        return result
    candidates = comparison.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 50 or not candidates:
        result["reason"] = "MISSING_OR_UNBOUNDED_GRID"
        return result
    try:
        stamp = time(comparison.get("at"))
        asof = time(route["at"])
        if not 0 <= (asof - stamp).total_seconds() <= 120:
            result["reason"] = "STALE_OR_FUTURE_COMPARISON"
            return result
    except (ValueError, KeyError, TypeError):
        result["reason"] = "INVALID_COMPARISON_TIME"
        return result
    ranked = []
    for row in candidates:
        if not isinstance(row, dict) or row.get("selection_status") != "NO_EXPLICIT_CONFLICT":
            continue
        if row.get("verdict") != "RESEARCH_ONLY" or row.get("price_status") != "PRICED":
            continue
        prices = row.get("prices")
        if not isinstance(prices, list) or len(prices) != 1:
            continue  # ambiguous duplicate or missing line; never cherry-pick
        p = prices[0]
        if not isinstance(p, dict) or isinstance(p.get("odds"), bool):
            continue
        odds = p.get("odds")
        if not isinstance(odds, (float, int)) or not math.isfinite(odds) or not min_odds <= odds <= 10000:
            continue
        try:
            market = market_from_key(row["key"])
            timestamp = time(p["observed_at"])
            if not 0 <= (asof - timestamp).total_seconds() <= 120:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if not isinstance(p.get("bookmaker"), str) or not p["bookmaker"].strip() or not p.get("line_id"):
            continue
        # A conservative ordering of research observations, NOT measured value.
        low = p.get("calibration_ev_low")
        low = float(low) if type(low) in (int, float) and math.isfinite(low) else float("-inf")
        ranked.append((-low, -float(odds), market.kind, row["key"],
                       {"market": market.key, "family": market.kind,
                        "odds": float(odds), "bookmaker": p["bookmaker"],
                        "line_id": p["line_id"], "observed_at": timestamp.isoformat(),
                        "experimental_calibration_ev_low": None if low == float("-inf") else low,
                        "calibration_status": row.get("calibration"),
                        "status": "CANDIDATE_RESEARCH_ONLY", "monetary_permission": False}))
    used = set()
    for _, _, family, _, candidate in sorted(ranked):
        if family in used:
            continue
        used.add(family)
        result["alternatives"].append(candidate)
        if len(result["alternatives"]) == limit:
            break
    result["status"] = "RESEARCH_CANDIDATES_ONLY" if result["alternatives"] else "NO_VERIFIED_ALTERNATIVE"
    result["reason"] = ("VIEW_ONLY_NOT_VALIDATED_EDGE" if result["alternatives"]
                        else "NO_UNAMBIGUOUS_FRESH_LINE_GE_2_OR_ALL_CONFLICTED")
    return result
