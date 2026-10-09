"""SEFIROT scenario/vector post-audit: research-only, never a betting gate.

Encodes five audit lessons without changing CORE probabilities, Policy, money gates,
or enabling LIVE. Inputs are manually assembled research cases and therefore cannot
certify edge/provenance. Archived live snapshots are accepted only for post-hoc QA.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.contracts import Policy, digest

SCHEMA = "scenario-vector-audit-v1"
INPUT_SCHEMA = "scenario-vector-case-v1"
FAMILIES = {"GOALS", "SIDE", "CORNERS", "TIMING", "CARDS", "SHOTS", "OTHER"}
DECISIONS = {"PLAY", "PASS", "OBSERVE"}
OUTCOMES = {"WIN", "LOSS", "PUSH", "VOID", "UNKNOWN"}
PHASES = {"PREMATCH_REVIEW", "POSTMATCH_REVIEW", "ARCHIVED_LIVE_REVIEW"}
SIDES = ("HOME", "DRAW", "AWAY")


def _finite(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name}: finite number required")
    value = float(value)
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{name}: outside range")
    return value


def _leg_complexity(leg):
    market = leg["market"].upper().replace(" ", "_")
    if leg["family"] == "SIDE" and ("DOUBLE_CHANCE" in market or market in {"1X", "X2", "12"}):
        return 1
    if leg["family"] == "GOALS" and "TOTAL" in market and "TEAM" not in market and "HALF" not in market:
        return 1
    if leg["family"] == "CORNERS" and "TOTAL" in market and "TEAM" not in market:
        return 1
    if "BTTS" in market or "TEAM_TOTAL" in market or "HALF" in market or "DNB" in market:
        return 2
    if "HANDICAP" in market or "FIRST" in market or "SCORE" in market:
        return 3
    return 2


def _validate_leg(leg, index):
    if not isinstance(leg, dict):
        raise ValueError("leg object required")
    allowed = {"id", "family", "market", "outcome"}
    if set(leg) != allowed:
        raise ValueError(f"leg {index}: exact fields required")
    if not isinstance(leg["id"], str) or not leg["id"]:
        raise ValueError(f"leg {index}: nonempty id required")
    if leg["family"] not in FAMILIES:
        raise ValueError(f"leg {index}: invalid family")
    if not isinstance(leg["market"], str) or not leg["market"].strip():
        raise ValueError(f"leg {index}: market required")
    if leg["outcome"] not in OUTCOMES:
        raise ValueError(f"leg {index}: invalid outcome")
    return dict(leg)


def derive_vector(legs):
    """Describe the structural hypothesis before looking at price or settlement."""
    counts = Counter(leg["family"] for leg in legs)
    top = max(counts.values())
    primary = sorted(k for k, v in counts.items() if v == top)
    primary_family = primary[0] if len(primary) == 1 else "MIXED"
    present = set(counts)
    if present == {"GOALS"}:
        vector = "GOALS"
    elif present <= {"GOALS", "TIMING"} and "GOALS" in present:
        vector = "GOALS_WITH_TIMING"
    elif present == {"SIDE"}:
        vector = "SIDE"
    elif present <= {"GOALS", "SIDE"} and present == {"GOALS", "SIDE"}:
        vector = "GOALS_WITH_SIDE_GUARD"
    elif present <= {"GOALS", "CORNERS"} and present == {"GOALS", "CORNERS"}:
        vector = "OPEN_ACTIVITY_MIXED"
    else:
        vector = "MIXED:" + "+".join(sorted(present))
    simplest = min(_leg_complexity(leg) for leg in legs)
    benchmarks = [
        {"leg_id": leg["id"], "family": leg["family"], "market": leg["market"],
         "outcome": leg["outcome"], "complexity": _leg_complexity(leg)}
        for leg in legs if _leg_complexity(leg) == simplest
    ]
    primary_simple = [b for b in benchmarks if b["family"] == primary_family]
    if primary_simple:
        benchmarks = primary_simple
    return {
        "primary_vector": vector,
        "primary_family": primary_family,
        "family_counts": dict(sorted(counts.items())),
        "simple_market_benchmark_candidates": benchmarks,
        "benchmark_policy": "structural_simplicity_only_not_result_or_price_optimization",
    }


def _prob_vector(obj, name):
    if not isinstance(obj, dict) or set(obj) != set(SIDES):
        raise ValueError(f"{name}: HOME/DRAW/AWAY required")
    values = {side: _finite(obj[side], f"{name}.{side}", 0, 1) for side in SIDES}
    if abs(sum(values.values()) - 1.0) > 1e-6:
        raise ValueError(f"{name}: probabilities must sum to 1")
    return values


def _fair_from_odds(odds):
    if not isinstance(odds, dict) or set(odds) != set(SIDES):
        raise ValueError("market_1x2_odds: HOME/DRAW/AWAY required")
    inverse = {s: 1.0 / _finite(odds[s], "market odds", 1.0000001) for s in SIDES}
    total = sum(inverse.values())
    return {s: inverse[s] / total for s in SIDES}


def divergence_diagnostic(model_1x2, market_1x2_odds, policy=None):
    """Compare model side vector to no-vig 1X2; research stop only."""
    policy = policy or Policy()
    model = _prob_vector(model_1x2, "model_1x2")
    market = _fair_from_odds(market_1x2_odds)
    gaps = {s: model[s] - market[s] for s in SIDES}
    max_side = max(SIDES, key=lambda s: abs(gaps[s]))
    max_gap = abs(gaps[max_side])
    if max_gap >= policy.extreme_divergence:
        status = "HARD_RESEARCH_STOP"
    elif max_gap >= policy.divergence:
        status = "REVIEW_REQUIRED"
    else:
        status = "ALIGNED_WITHIN_POLICY_REVIEW_BAND"
    return {
        "status": status,
        "model_1x2": model,
        "market_no_vig_1x2": market,
        "signed_gap": gaps,
        "max_abs_gap": max_gap,
        "max_gap_side": max_side,
        "policy_review_threshold": policy.divergence,
        "policy_extreme_threshold": policy.extreme_divergence,
        "canonical_effect": "NONE_RESEARCH_DIAGNOSTIC_ONLY",
    }


def archived_live_quality(snapshot):
    """Post-hoc anti-pattern check. It cannot be used as a LIVE runtime gate."""
    if snapshot is None:
        return None
    if not isinstance(snapshot, dict):
        raise ValueError("archived_live_snapshot object required")
    allowed = {
        "focus_side", "possession_home", "possession_away", "shots_home", "shots_away",
        "shots_on_target_home", "shots_on_target_away", "corners_home", "corners_away",
        "xg_home", "xg_away", "big_chances_home", "big_chances_away",
        "shots_in_box_home", "shots_in_box_away",
    }
    if set(snapshot) - allowed:
        raise ValueError("archived live snapshot contains unsupported fields")
    side = snapshot.get("focus_side")
    if side not in ("HOME", "AWAY"):
        raise ValueError("archived live focus_side HOME/AWAY required")
    foe = "away" if side == "HOME" else "home"
    me = "home" if side == "HOME" else "away"
    volume = []
    for metric in ("possession", "shots", "corners"):
        a, b = snapshot.get(f"{metric}_{me}"), snapshot.get(f"{metric}_{foe}")
        if a is not None and b is not None:
            a = _finite(a, metric, 0); b = _finite(b, metric, 0)
            volume.append({"metric": metric, "advantage": a > b, "delta": a - b})
    quality = []
    for metric in ("shots_on_target", "xg", "big_chances", "shots_in_box"):
        a, b = snapshot.get(f"{metric}_{me}"), snapshot.get(f"{metric}_{foe}")
        if a is not None and b is not None:
            a = _finite(a, metric, 0); b = _finite(b, metric, 0)
            quality.append({"metric": metric, "advantage": a > b, "delta": a - b})
    positive = [q for q in quality if q["advantage"]]
    confirmed = len(quality) >= 2 and len(positive) >= 2
    return {
        "status": "QUALITY_CONFIRMED_POSTHOC" if confirmed else "NO_QUALITY_CONFIRMATION",
        "volume_signals": volume,
        "quality_signals": quality,
        "available_quality_metrics": len(quality),
        "positive_quality_metrics": len(positive),
        "volume_only_is_insufficient": True,
        "live_runtime_enabled": False,
        "usable_for_live_selection": False,
    }


def settlement_diagnostic(decision, outcome):
    """Keep realized result separate from any claim about ex-ante edge."""
    if decision not in DECISIONS or outcome not in OUTCOMES:
        raise ValueError("invalid decision/outcome")
    if outcome == "UNKNOWN":
        label = "UNSETTLED"
    elif decision == "PLAY" and outcome == "WIN":
        label = "PLAY_WIN_OUTCOME_ONLY"
    elif decision == "PLAY" and outcome in {"LOSS", "PUSH", "VOID"}:
        label = "PLAY_NONWIN_OUTCOME_ONLY"
    elif decision == "PASS" and outcome == "WIN":
        label = "PASS_WIN_FALSE_NEGATIVE_OUTCOME_ONLY"
    elif decision == "PASS" and outcome in {"LOSS", "PUSH", "VOID"}:
        label = "PASS_NONWIN_TRUE_NEGATIVE_OUTCOME_ONLY"
    else:
        label = "OBSERVED_OUTCOME_ONLY"
    return {
        "label": label,
        "decision": decision,
        "outcome": outcome,
        "edge_conclusion": "NOT_INFERABLE_FROM_SINGLE_SETTLEMENT",
        "accuracy_conclusion": "NOT_INFERABLE_FROM_SINGLE_SETTLEMENT",
    }


def _validate_case(case):
    if not isinstance(case, dict):
        raise ValueError("case JSON object required")
    allowed = {
        "schema", "case_id", "phase", "decision", "outcome", "legs",
        "model_1x2", "market_1x2_odds", "archived_live_snapshot",
    }
    if set(case) - allowed:
        raise ValueError("unknown case fields")
    for field in ("schema", "case_id", "phase", "decision", "outcome", "legs"):
        if field not in case:
            raise ValueError(f"missing {field}")
    if case["schema"] != INPUT_SCHEMA:
        raise ValueError("scenario-vector-case-v1 required")
    if not isinstance(case["case_id"], str) or not case["case_id"].strip():
        raise ValueError("case_id required")
    if case["phase"] not in PHASES:
        raise ValueError("invalid phase")
    if case["decision"] not in DECISIONS or case["outcome"] not in OUTCOMES:
        raise ValueError("invalid decision/outcome")
    if not isinstance(case["legs"], list) or not 1 <= len(case["legs"]) <= 12:
        raise ValueError("1..12 legs required")
    legs = [_validate_leg(leg, i) for i, leg in enumerate(case["legs"])]
    if len({leg["id"] for leg in legs}) != len(legs):
        raise ValueError("duplicate leg id")
    if case["phase"] != "ARCHIVED_LIVE_REVIEW" and case.get("archived_live_snapshot") is not None:
        raise ValueError("live snapshot allowed only in archived live review")
    return legs


def audit(case, policy=None):
    legs = _validate_case(case)
    vector = derive_vector(legs)
    div = None
    if case.get("model_1x2") is not None or case.get("market_1x2_odds") is not None:
        if case.get("model_1x2") is None or case.get("market_1x2_odds") is None:
            raise ValueError("both model_1x2 and market_1x2_odds required")
        div = divergence_diagnostic(case["model_1x2"], case["market_1x2_odds"], policy)
    live = archived_live_quality(case.get("archived_live_snapshot"))
    settlement = settlement_diagnostic(case["decision"], case["outcome"])
    out = {
        "schema": SCHEMA,
        "case_id": case["case_id"],
        "phase": case["phase"],
        "vector": vector,
        "market_divergence": div,
        "archived_live_quality": live,
        "settlement": settlement,
        "rules": {
            "core_vector_first": True,
            "simple_market_benchmark": True,
            "market_divergence_stop": "RESEARCH_ONLY_USES_EXISTING_POLICY_BANDS",
            "live_quality_gate": "ARCHIVED_POSTHOC_ONLY_LIVE_RUNTIME_DISABLED",
            "result_not_edge": True,
        },
        "input_provenance": "MANUAL_RESEARCH_CASE_NOT_PROVIDER_ATTESTED",
        "parameters_modified": False,
        "model_probabilities_modified": False,
        "canonical_decision_modified": False,
        "edge_certified": False,
        "monetary_permission": False,
        "execution_enabled": False,
        "live_runtime_enabled": False,
        "stake": 0.0,
    }
    out["hash"] = digest(out)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="SEFIROT scenario/vector audit; post-decision research only")
    parser.add_argument("case", help="scenario-vector-case-v1 JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        case = json.loads(Path(args.case).read_text(encoding="utf-8"))
        report = audit(case)
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        print(json.dumps({
            "schema": report["schema"], "vector": report["vector"]["primary_vector"],
            "divergence": None if report["market_divergence"] is None else report["market_divergence"]["status"],
            "settlement": report["settlement"]["label"], "monetary_permission": False,
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.exit(2, "Scenario vector audit: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
