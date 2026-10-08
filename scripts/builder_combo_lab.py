"""SEFIROT Bet Builder Combo Lab: price-blind soccer SGM research only.

Freeze a finite deterministic set of 2/3-leg push-free goal combinations
using the ORIGINAL sports-only prediction. Optional Stake availability
inspection happens only AFTER the freeze, and never supplies combined prices.
No login, betslip, execution, or monetary permissions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.builder_research import BRANCHES, builder_contract, joint_probability, _branch
from sefirot.contracts import Policy, digest, time, strict
from sefirot.engine import market_constraint_issues
from sefirot.market_grid import create_grid
from sefirot.markets import market_of
from sefirot.odds_provider import require_prematch_seal
from sefirot.probability import estimate
from sefirot.stake_mapper import normalize_snapshot

SCHEMA = "builder-combo-lab-freeze-v1"
INSPECTION_SCHEMA = "builder-combo-stake-inspection-v1"
MAX_BUILDERS = 1200
# Predeclared finite palette; changes to the list create a new experiment
# and do NOT retroactively alter old frozen reports. No odds inform selection.
PALETTE = (
    {"kind": "1X2", "side": "HOME"},
    {"kind": "1X2", "side": "DRAW"},
    {"kind": "1X2", "side": "AWAY"},
    {"kind": "DOUBLE_CHANCE", "side": "1X"},
    {"kind": "DOUBLE_CHANCE", "side": "X2"},
    {"kind": "DOUBLE_CHANCE", "side": "12"},
    {"kind": "BTTS", "side": "YES"},
    {"kind": "BTTS", "side": "NO"},
    {"kind": "TOTAL", "side": "OVER", "line": 1.5},
    {"kind": "TOTAL", "side": "OVER", "line": 2.5},
    {"kind": "TOTAL", "side": "UNDER", "line": 2.5},
    {"kind": "TOTAL", "side": "UNDER", "line": 3.5},
    {"kind": "TEAM_TOTAL", "side": "HOME_OVER", "line": 0.5},
    {"kind": "TEAM_TOTAL", "side": "HOME_OVER", "line": 1.5},
    {"kind": "TEAM_TOTAL", "side": "AWAY_OVER", "line": 0.5},
    {"kind": "TEAM_TOTAL", "side": "AWAY_OVER", "line": 1.5},
)
MIXED_FAMILIES = (
    "GOALS+CORNERS", "GOALS+SHOTS", "GOALS+SOT", "GOALS+FOULS",
    "GOALS+YELLOW_CARDS", "GOALS+PLAYER_PROPS", "CORNERS+CARDS",
)


def _verify(document):
    if not isinstance(document, dict):
        raise ValueError("JSON object required")
    unsigned = dict(document)
    actual = unsigned.pop("hash", None)
    if not isinstance(actual, str) or digest(unsigned) != actual:
        raise ValueError("original file hash mismatch")


def _read(filename):
    return json.loads(Path(filename).read_text(encoding="utf-8"))


def _write_new(filename, payload):
    target = Path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _prematch_prediction(prediction, at):
    _verify(prediction)
    require_prematch_seal(prediction, at)
    policy = Policy(**prediction["policy"])
    grid = create_grid(prediction, policy, at)  # recomputes source sports and checks build
    if grid["prediction_id"] != prediction["id"]:
        raise ValueError("different sealed prediction")
    if grid["synthetic"] != prediction["synthetic"]:
        raise ValueError("synthetic flag mismatch")
    return policy, grid


def _valid_palette():
    parsed = [market_of(leg) for leg in PALETTE]
    if len(parsed) != len({m.key for m in parsed}):
        raise ValueError("duplicate palette contracts")
    if any(m.push_possible for m in parsed):
        raise ValueError("only push-free legs can be included")
    return parsed


def freeze(prediction, at, *, sizes=(2, 3)):
    """No quotes or results; deterministic complete palette enumeration."""
    if sizes not in ((2,), (3,), (2, 3)):
        raise ValueError("only predefined sizes: 2, 3, or both")
    policy, grid = _prematch_prediction(prediction, at)
    palette = _valid_palette()
    mass, variants, model = estimate(
        prediction["sports"], policy, prediction.get("goal_model")
    )
    if model["model_version"] != prediction["model_version"]:
        raise ValueError("model identity drift")
    rows, rejected = [], Counter()
    for count in sizes:
        for indices in combinations(range(len(palette)), count):
            legs = [PALETTE[i] for i in indices]
            try:
                markets, cells = builder_contract(legs)
            except ValueError as exc:
                reason = str(exc)
                if reason not in (
                    "contradictory builder legs", "redundant implied builder leg"
                ):
                    raise
                rejected[reason] += 1
                continue
            calculation = joint_probability(legs, mass)
            stress = [sum(m.get(score, 0.) for score in cells) for m in variants]
            scenario_blocks = sorted({
                issue["code"] for market in markets for issue in
                market_constraint_issues(market, grid["selection_constraints"])
                if issue.get("severity") == "BLOCK"
            })
            branches = calculation["terminal_branch_contributions"]
            rows.append({
                "id": digest(["GOAL_JOINT_RAW", [m.key for m in markets]]),
                "legs": legs, "keys": [m.key for m in markets],
                "size": count,
                "joint_probability_raw": calculation["joint_probability_raw"],
                "fair_odds_raw": calculation["fair_odds_raw"],
                "marginals_raw": calculation["marginals_raw"],
                "naive_product_diagnostic_only": calculation["independence_product_diagnostic"],
                "dependence_gap": calculation["dependence_gap"],
                "rate_stress_probability_min": min(
                    [calculation["joint_probability_raw"], *stress]
                ),
                "rate_stress_probabilities_raw": stress,
                "scenario_blockers": scenario_blocks,
                "terminal_branch_contributions": branches,
                "terminal_branch_given_win": calculation["terminal_branches_given_win"],
                "model_status": "RAW_GOALS_JOINT_UNCALIBRATED",
                "price_status": "NO_VERIFIED_SGM_PRICE",
                "stake_joint_odds": None, "builder_ev": None,
                "available_in_bet_builder": None,
                "allow_execution": False, "monetary_permission": False,
            })
            if len(rows) > MAX_BUILDERS:
                raise ValueError("explicit builder output cap exceeded; freeze a smaller size")
    out = {
        "schema": SCHEMA, "as_of": at,
        "prediction_id": prediction["id"], "original_grid_hash": grid["hash"],
        "match": prediction["sports"]["match"], "source_sealed_at": prediction["sealed_at"],
        "model_hash": prediction["model_hash"], "code_hash": prediction["code_hash"],
        "policy_hash": prediction["policy_hash"], "palette_hash": digest(PALETTE),
        "palette": list(PALETTE), "sizes": list(sizes),
        "candidate_count": len(rows),
        "enumerated_count": sum(
            __import__("math").comb(len(PALETTE), n) for n in sizes
        ),
        "rejected_counts": dict(sorted(rejected.items())), "candidates": rows,
        "synthetic": bool(prediction["synthetic"]),
        "sporting_model_issues": prediction["issues"],
        "sensitivity_is_confidence_interval": False,
        "joint_calibration_status": "UNVALIDATED",
        "prices_read": False, "selected_after_odds": False,
        "cross_metric": {
            "families": list(MIXED_FAMILIES),
            "status": "MISSING_JOINT_DISTRIBUTION_AND_PROVIDER_COMBO_PRICE",
            "joint_probability": None, "joint_ev": None,
            "notes": "Shots, corners, fouls, cards, player props cannot be multiplied as independent.",
        },
        "stake_sgm_void_rule": "ANY_VOID_SELECTION_VOIDS_WHOLE_SGM",
        "unsupported": ["PUSH_LEG", "ASIAN_QUARTER", "LIVE", "EARLY_GOAL_PATH",
                         "HALF_TIME", "MULTI_EVENT", "MIXED_METRIC_PROBABILITY"],
        "monetary_permission": False, "execution_enabled": False, "stake": 0.0,
        "research_status": "UNVALIDATED_SHADOW_ONLY",
    }
    out["hash"] = digest(out)
    return out


def inspect_stake(frozen, snapshot):
    """Post-freeze read-only view of individual Stake leg availability.

    No combinability is inferred from a per-outcome customBetAvailable flag,
    and no odds multiplication or synthetic SGM quote is allowed.
    """
    _verify(frozen)
    if (frozen.get("schema") != SCHEMA or frozen.get("monetary_permission") is not False
            or frozen.get("prices_read") is not False
            or frozen.get("execution_enabled") is not False):
        raise ValueError("valid price-blind builder freeze required")
    if len(frozen.get("candidates", [])) != frozen.get("candidate_count"):
        raise ValueError("builder row count mismatch")
    if frozen.get("palette_hash") != digest(PALETTE):
        raise ValueError("builder palette changed")
    if [list(frozen.get("sizes", []))] not in ([[2]], [[3]], [[2, 3]]):
        raise ValueError("unsupported builder size selection")
    if not isinstance(snapshot, dict):
        raise ValueError("original Stake snapshot required")
    _verify(snapshot)
    if (snapshot.get("provider") != "STAKE_GRAPHQL_EXPERIMENTAL"
            or snapshot.get("status") != "RESEARCH_ONLY"
            or snapshot.get("monetary_permission") is not False
            or snapshot.get("execution_enabled") is not False):
        raise ValueError("Stake snapshot not research-only")
    match = frozen["match"]
    if (snapshot.get("fixture_id") != match["id"]
            or snapshot.get("home") != match["home"]
            or snapshot.get("away") != match["away"]
            or time(snapshot["kickoff"]) != time(match["kickoff"])):
        raise ValueError("Stake snapshot fixture mismatch")
    if not time(frozen["as_of"]) <= time(snapshot["received_at"]) < time(match["kickoff"]):
        raise ValueError("Stake prices must be fetched post-freeze and prematch")
    if snapshot.get("market_count") != len(snapshot.get("markets", [])):
        raise ValueError("raw Stake inventory incomplete or malformed")
    try:
        normalized = normalize_snapshot(snapshot)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Stake normalization cannot verify market labels") from exc
    # Mapped single rows are independent from joint SGM quote production.
    # A null market status or null outcome.active remains UNKNOWN, never TRUE.
    bykey = {}
    raw_by_market = {
        str(m.get("id")): m for m in snapshot["markets"]
        if isinstance(m, dict)
    }
    for row in normalized["main_quotes"]:
        raw = raw_by_market.get(str(row["stake_market_id"]))
        if raw is None or row["stake_outcome_id"] is None:
            continue
        outcomes = raw.get("outcomes")
        if not isinstance(outcomes, list):
            continue
        matching = [
            x for x in outcomes if isinstance(x, dict)
            and x.get("id") == row["stake_outcome_id"]
        ]
        if len(matching) != 1:
            continue
        active = (
            raw.get("status") in ("active", "open", "ACTIVE", "OPEN")
            and matching[0].get("active") is True
            and matching[0].get("customBetAvailable") is True
        )
        bykey.setdefault(row["key"], []).append({
            "market_id": row["stake_market_id"],
            "outcome_id": row["stake_outcome_id"],
            "raw_template": row["raw_template"],
            "single_odds": row["odds"], "flag_active_custom_bet": active,
        })
    reviewed = []
    for combo in frozen["candidates"]:
        parts = []
        for key in combo["keys"]:
            matches = bykey.get(key, [])
            valid = [p for p in matches if p["flag_active_custom_bet"]]
            parts.append({
                "key": key,
                "status": "FLAGGED_FOR_CUSTOM_BET" if len(valid) == 1 else
                          "MISSING_OR_AMBIGUOUS_ACTIVE_OUTCOME",
                "stake_ids": [
                    {"market_id": v["market_id"], "outcome_id": v["outcome_id"]}
                    for v in valid
                ] if len(valid) == 1 else [],
            })
        reviewed.append({
            "builder_id": combo["id"], "leg_count": len(parts), "legs": parts,
            "all_legs_individually_flagged": all(
                p["status"] == "FLAGGED_FOR_CUSTOM_BET" for p in parts
            ),
            "actual_combination_accepted_by_stake": None,
            "stake_joint_odds": None, "builder_ev": None,
            "quote_status": "NO_STAKE_SGM_PRICE_OR_COMPATIBILITY_PROOF",
            "monetary_permission": False,
        })
    out = {
        "schema": INSPECTION_SCHEMA, "builder_hash": frozen["hash"],
        "stake_snapshot_hash": snapshot["hash"],
        "received_at": snapshot["received_at"], "match": match,
        "candidates": reviewed,
        "individually_flagged_combo_count": sum(
            bool(row["all_legs_individually_flagged"]) for row in reviewed
        ),
        "sgm_accepted_count": None, "sgm_price_count": 0,
        "joint_ev_available_count": 0,
        "interpretation": "Stake individual customBetAvailable flags do not confirm pairwise compatibility or joint prices.",
        "cross_metric_joint": None, "monetary_permission": False,
        "execution_enabled": False, "stake": 0.0,
    }
    out["hash"] = digest(out)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stake Bet Builder combinations; shadow only")
    sub = parser.add_subparsers(dest="action", required=True)
    fr = sub.add_parser("freeze", help="generate deterministic price-blind 2/3 goal SGM palette")
    fr.add_argument("prediction", help="original sealed prediction JSON")
    fr.add_argument("--at", required=True, help="ISO timestamp before kickoff")
    fr.add_argument("--sizes", choices=("2", "3", "both"), default="both")
    fr.add_argument("--output", required=True)
    rev = sub.add_parser("inspect", help="compare frozen legs with original Stake raw snapshot")
    rev.add_argument("freeze")
    rev.add_argument("snapshot")
    rev.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "freeze":
            sizes = (2, 3) if args.sizes == "both" else (int(args.sizes),)
            report = freeze(_read(args.prediction), args.at, sizes=sizes)
        else:
            report = inspect_stake(_read(args.freeze), _read(args.snapshot))
        _write_new(args.output, report)
        print(json.dumps({
            "schema": report["schema"], "output": str(args.output),
            "candidate_count": report.get("candidate_count", len(report.get("candidates", []))),
            "monetary_permission": False, "execution_enabled": False,
        }, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"Bet Builder Lab: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
