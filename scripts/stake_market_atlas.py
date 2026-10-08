"""Stake market atlas: lossless raw inventory of observed prematch markets.

Research only. It does not promote provider prices to SEFIROT quote contracts.
Use existing authenticated Stake bridge solely on exact prematch sealed fixtures.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.contracts import digest, time
from sefirot.odds_provider import require_prematch_seal
from sefirot.stake_mapper import normalize_snapshot
from sefirot.stake_provider import (
    sports_events, exact_event, fixture_groups, fixture_markets, research_snapshot,
)

SCHEMA = "stake-market-atlas-v1"
MAX_SNAPSHOTS = 100
MAX_MARKETS = 100000
# Provider's present GraphQL query requests up to 50 templates and 50
# markets per template, without a verified pagination mechanism.
PROVIDER_TEMPLATE_LIMIT = 50
PROVIDER_MARKET_LIMIT = 50


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_new(path, data):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _classify(market):
    label = " ".join(str(market.get(k) or "") for k in ("group", "template", "name")).lower()
    # These are labels, NOT a rulebook or fitted predictive markets.
    if re.search(r"(yellow cards?|yellow card bookings?)", label):
        metric = "YELLOW_CARDS"
    elif re.search(r"(red cards?|sending off)", label):
        metric = "RED_CARDS"
    elif re.search(r"(cards?|bookings?)", label):
        metric = "CARDS_RULES_UNKNOWN"
    elif "foul" in label:
        metric = "FOULS"
    elif "corner" in label:
        metric = "CORNERS"
    elif re.search(r"(shots? on (target|goal))", label):
        metric = "SOT"
    elif "shot" in label:
        metric = "SHOTS"
    elif "offside" in label:
        metric = "OFFSIDES"
    elif re.search(r"(goals?|both teams to score|correct score|total|btts)", label):
        metric = "GOALS_OR_TOTAL"
    elif re.search(r"(1x2|handicap|draw no bet|double chance|match result|winner)", label):
        metric = "RESULT"
    else:
        metric = "UNCLASSIFIED"
    if re.search(r"(1st|first)\s*half|half\s*1|1h\b", label):
        period = "FIRST_HALF"
    elif re.search(r"(2nd|second)\s*half|half\s*2|2h\b", label):
        period = "SECOND_HALF"
    elif re.search(r"(extra time|overtime|penalt(y|ies) shootout)", label):
        period = "EXTRA_TIME_OR_PENALTIES"
    elif re.search(r"(quarter|\bq[1-4]\b|\d+\s*(st|nd|rd|th)\s*minute)", label):
        period = "OTHER_PERIOD"
    else:
        period = "UNVERIFIED_FULL_TIME"
    return metric, period


def _check_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("Stake snapshot object required")
    if (snapshot.get("provider") != "STAKE_GRAPHQL_EXPERIMENTAL"
            or snapshot.get("status") != "RESEARCH_ONLY"
            or snapshot.get("monetary_permission") is not False
            or snapshot.get("execution_enabled") is not False):
        raise ValueError("only an original research-only Stake snapshot is accepted")
    signed = dict(snapshot)
    signature = signed.pop("hash", None)
    if not isinstance(signature, str) or digest(signed) != signature:
        raise ValueError("Stake snapshot hash mismatch")
    if not snapshot.get("fixture_id") or not snapshot.get("stake_event_id"):
        raise ValueError("exact fixture and Stake event IDs required")
    if time(snapshot["received_at"]) >= time(snapshot["kickoff"]):
        raise ValueError("live/after-kickoff snapshot rejected")
    markets = snapshot.get("markets")
    if not isinstance(markets, list) or len(markets) > 5000:
        raise ValueError("bounded raw Stake market list required")
    if snapshot.get("market_count") != len(markets):
        raise ValueError("Stake market_count mismatch")
    if not isinstance(snapshot.get("home"), str) or not isinstance(snapshot.get("away"), str):
        raise ValueError("team names required")
    return markets


def make_atlas(snapshots):
    """Preserve every raw market/outcome, whether mapped, inactive or unfamiliar."""
    if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= MAX_SNAPSHOTS:
        raise ValueError("1..100 original Stake snapshots required")
    items, fixtures, seen, warnings = [], [], set(), []
    for snap in snapshots:
        markets = _check_snapshot(snap)
        event_identity = (snap["fixture_id"], snap["stake_event_id"])
        if event_identity in seen:
            raise ValueError("duplicate fixture snapshot; choose one observation explicitly")
        seen.add(event_identity)
        mapped_main, mapped_small, errors = set(), set(), []
        # A broken or unfamiliar mapper MUST NOT discard the raw provider item.
        for idx, market in enumerate(markets):
            if not isinstance(market, dict):
                errors.append({"index": idx, "error": "INVALID_RAW_MARKET"})
                continue
            try:
                isolated = dict(snap)
                isolated["markets"] = [market]
                isolated["market_count"] = 1
                # The mapper's accepted shapes can change; mappings are advisory.
                converted = normalize_snapshot(isolated)
                for q in converted["main_quotes"]:
                    mapped_main.add((idx, str(q.get("stake_outcome_id"))))
                for q in converted["small_quotes"]:
                    mapped_small.add((idx, str(q.get("stake_outcome_id"))))
            except (ValueError, TypeError, KeyError, OverflowError):
                errors.append({"index": idx, "error": "NORMALIZATION_UNAVAILABLE"})
            metric, period = _classify(market)
            # Preserve full provider content including active/outcome flags and lines.
            outcomes = market.get("outcomes")
            if not isinstance(outcomes, list):
                outcomes = []
                errors.append({"index": idx, "error": "OUTCOMES_MALFORMED"})
            mapped = []
            for outcome in outcomes:
                oid = str(outcome.get("id")) if isinstance(outcome, dict) else None
                mapped.append({
                    "outcome_id": oid,
                    "classification": (
                        "MAIN_REFERENCE_ONLY" if (idx, oid) in mapped_main else
                        "SMALL_REFERENCE_ONLY" if (idx, oid) in mapped_small else
                        "UNMAPPED_RAW"
                    ),
                })
            items.append({
                "fixture_id": snap["fixture_id"], "stake_event_id": snap["stake_event_id"],
                "snapshot_hash": snap["hash"], "received_at": snap["received_at"],
                "kickoff": snap["kickoff"], "raw_index": idx,
                "raw": market, "outcome_mapping": mapped,
                "metric_hint": metric, "period_hint": period,
                "verified_settlement": False,
                "probability_model_available": False,
                "referee_gate_passed": False,
                "monetary_permission": False,
            })
            if len(items) > MAX_MARKETS:
                raise ValueError("global raw market limit exceeded; split atlas")
        template_groups = Counter(
            (str(m.get("group")), str(m.get("template")), str(m.get("template_ext_id")))
            for m in markets if isinstance(m, dict)
        )
        near_limit = [
            {"group": g, "template": t, "template_ext_id": x, "markets": n}
            for (g, t, x), n in sorted(template_groups.items()) if n >= PROVIDER_MARKET_LIMIT
        ]
        group_set = {str(m.get("group")) for m in markets if isinstance(m, dict)}
        requested = snap.get("requested_groups")
        missing_groups = sorted(set(requested) - group_set) if isinstance(requested, list) else None
        fixtures.append({
            "fixture_id": snap["fixture_id"], "stake_event_id": snap["stake_event_id"],
            "snapshot_hash": snap["hash"], "market_count": len(markets),
            "group_count_observed": len(group_set),
            "requested_groups": requested if isinstance(requested, list) else None,
            "missing_groups": missing_groups, "market_limit_indicators": near_limit,
            "normalizer_errors": errors,
            "completeness": "NOT_PROVEN_PROVIDER_HAS_FIXED_LIMITS",
        })
        if near_limit or missing_groups:
            warnings.append({"fixture_id": snap["fixture_id"], "possible_truncation": True})
    metrics = Counter(row["metric_hint"] for row in items)
    map_counts = Counter(m["classification"] for row in items for m in row["outcome_mapping"])
    out = {
        "schema": SCHEMA, "status": "OBSERVED_MARKET_INVENTORY_NOT_EXHAUSTIVE",
        "source": "STAKE_GRAPHQL_EXPERIMENTAL", "snapshots": len(snapshots),
        "fixture_count": len(fixtures), "raw_market_count": len(items),
        "raw_outcome_count": sum(
            len(row["raw"].get("outcomes")) if isinstance(row["raw"].get("outcomes"), list) else 0
            for row in items
        ),
        "metric_inventory": dict(sorted(metrics.items())),
        "outcome_mapping_inventory": dict(sorted(map_counts.items())),
        "fixtures": fixtures, "markets": items,
        "completeness_proven": False, "coverage_warnings": warnings,
        "provider_limits": {"templates_per_group": PROVIDER_TEMPLATE_LIMIT,
                            "markets_per_template": PROVIDER_MARKET_LIMIT,
                            "pagination_verified": False},
        "note": "Unknown provider markets are preserved, never invented or automatically enabled.",
        "settlement_rules_verified": False, "probabilities_calibrated": False,
        "allow_live": False, "allow_express": False, "monetary_permission": False,
        "execution_enabled": False, "stake": 0.0,
    }
    out["hash"] = digest(out)
    return out


def harvest(prediction, *, max_events=200, max_groups=500):
    """One exact sealed, UPCOMING soccer fixture; no scanning live sports."""
    if not isinstance(prediction, dict):
        raise ValueError("sealed prediction object required")
    sealed = dict(prediction)
    identity = sealed.pop("id", None)
    if not isinstance(identity, str) or digest(sealed) != identity:
        raise ValueError("sealed prediction hash mismatch")
    now = datetime.now(timezone.utc).isoformat()
    match = require_prematch_seal(prediction, now)  # before network
    if not 1 <= max_events <= 200 or not 1 <= max_groups <= 500:
        raise ValueError("bounded event/group limits required")
    packet = sports_events(first=max_events, sport_slug="soccer", match_type="upcoming")
    received = packet["receipt"]["received_at"]
    event = exact_event(packet["events"], prediction, received)
    if event.get("status") in ("live", "ended", "settled"):
        raise ValueError("non-prematch Stake event")
    groups = fixture_groups(event["slug"])
    names = groups["group_names"]
    if len(names) > max_groups:
        raise ValueError("group cap would truncate fixture; raise --max-groups explicitly")
    # A call can span kickoff. Recheck BEFORE requesting markets, not only
    # after the response. Never deliberately fetch in-play quotes.
    require_prematch_seal(prediction, datetime.now(timezone.utc).isoformat())
    packet_markets = fixture_markets(event["slug"], groups=names)
    received = datetime.now(timezone.utc).isoformat()
    require_prematch_seal(prediction, received)
    snapshot = research_snapshot(
        event, prediction, received, packet_markets["markets"],
        [packet["receipt"], groups["receipt"]] + packet_markets["receipts"],
    )
    snapshot["requested_groups"] = names
    snapshot["reported_group_count"] = len(names)
    snapshot["hash"] = digest({k: v for k, v in snapshot.items() if k != "hash"})
    return snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stake observed market atlas (research-only, no bets)")
    subs = parser.add_subparsers(dest="action", required=True)
    build = subs.add_parser("build", help="index saved original snapshots, including unsupported markets")
    build.add_argument("snapshots", nargs="+")
    build.add_argument("--output", required=True)
    capture = subs.add_parser("harvest", help="fetch one pre-sealed UPCOMING soccer fixture")
    capture.add_argument("--prediction", required=True)
    capture.add_argument("--output", required=True, help="output raw snapshot JSON")
    capture.add_argument("--atlas", required=True, help="output market atlas JSON")
    capture.add_argument("--max-events", type=int, default=200)
    capture.add_argument("--max-groups", type=int, default=500)
    args = parser.parse_args(argv)
    try:
        paths = [args.output] if args.action == "build" else [args.output, args.atlas]
        if len(set(paths)) != len(paths) or any(Path(path).exists() for path in paths):
            raise ValueError("output exists or output paths collide; no overwrite")
        if args.action == "build":
            payload = make_atlas([_read(p) for p in args.snapshots])
        else:
            snapshot = harvest(_read(args.prediction), max_events=args.max_events,
                               max_groups=args.max_groups)
            payload = make_atlas([snapshot])
            _write_new(args.output, snapshot)
        _write_new(paths[-1], payload)
        print(json.dumps({
            "atlas": paths[-1], "raw_markets": payload["raw_market_count"],
            "raw_outcomes": payload["raw_outcome_count"],
            "completeness": payload["completeness_proven"],
            "monetary_permission": False,
        }, ensure_ascii=False))
        return 0
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, f"Stake atlas: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
