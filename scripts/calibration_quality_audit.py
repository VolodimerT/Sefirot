"""Read-only, fixture-clustered calibration diagnostics for original forward scorecards.

No model fit, no refit, no leakage, no bookmaker prices, no money gate.
Consumes only original SEFIROT forward-scorecard-v1 exports.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import timezone
import json
from pathlib import Path
from random import Random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.contracts import digest, time
from sefirot.evaluation import metrics, probability_vector
from sefirot.markets import market_from_key
from sefirot.probability import bin_key

SCHEMA = "calibration-quality-audit-v1"
OUTCOMES = ("WIN", "PUSH", "LOSS")
MAX_FIXTURES = 200000
MAX_OBSERVATIONS = 1000000
DEFAULT_BIN_MIN = 20  # Policy 2.4.2, report-only diagnostic (NOT an approval)
DEFAULT_HOLDOUT_MIN = 60
DEFAULT_COVERAGE_MIN = 0.8


def _validate(report):
    if not isinstance(report, dict) or report.get("schema") != "forward-scorecard-v1":
        raise ValueError("original forward-scorecard-v1 required")
    content = dict(report)
    signature = content.pop("hash", None)
    if not isinstance(signature, str) or signature != digest(content):
        raise ValueError("scorecard local content hash mismatch")
    if (report.get("monetary_permission") is not False
            or report.get("execution_enabled") is not False
            or report.get("holdout_passed") is not False
            or report.get("statistical_profitability_proven") is not False
            or report.get("forecasts_recomputed") != 0):
        raise ValueError("only original untouched research scorecards can be audited")
    role = report.get("role")
    if role not in ("CALIBRATION", "HOLDOUT"):
        raise ValueError("unknown or retrospective scorecard role")
    fixtures = report.get("fixtures")
    observations = report.get("observations")
    if (not isinstance(fixtures, list) or not 1 <= len(fixtures) <= MAX_FIXTURES
            or not isinstance(observations, list) or len(observations) > MAX_OBSERVATIONS):
        raise ValueError("bounded nonempty frozen fixture cohort required")
    if report.get("planned_fixtures") != len(fixtures):
        raise ValueError("plan denominator mismatch")
    fixture_map = {}
    for f in fixtures:
        if not isinstance(f, dict):
            raise ValueError("invalid fixture record")
        match_id = f.get("match_id")
        if not isinstance(match_id, str) or not match_id or match_id in fixture_map:
            raise ValueError("unique planned fixture ID required")
        if not isinstance(f.get("league"), str) or not isinstance(f.get("competition_profile"), str):
            raise ValueError("fixture league/profile required")
        if time(f["kickoff"]) > time(report["at"]) and f.get("status") == "SCORED":
            raise ValueError("scored event cannot be in the future")
        fixture_map[match_id] = f
    counted = sum(f["status"] == "SCORED" for f in fixtures)
    if report.get("scored_fixtures") != counted or report.get("market_observations") != len(observations):
        raise ValueError("scorecard scored/observation count mismatch")
    if abs(report.get("fixture_coverage", -1) - counted / len(fixtures)) > 1e-10:
        raise ValueError("scorecard coverage mismatch")
    if role == "CALIBRATION" and report.get("frozen_build", {}).get("calibrator_id") is not None:
        raise ValueError("CALIBRATION scorecard must not reuse a fitted calibrator")
    valid_keys = set()
    for group in report.get("groups", []):
        if not isinstance(group, dict):
            raise ValueError("invalid group")
        market = market_from_key(group["market"])
        valid_keys.add((group["league"], group["competition_profile"], market.key))
    if not valid_keys:
        raise ValueError("original declared market groups required")
    per_fixture = defaultdict(set)
    all_rows = []
    for r in observations:
        if not isinstance(r, dict):
            raise ValueError("invalid observation")
        mid = r.get("match_id")
        if mid not in fixture_map or fixture_map[mid]["status"] != "SCORED":
            raise ValueError("observation not from a scored planned fixture")
        f = fixture_map[mid]
        if (r.get("prediction_id") != f.get("prediction_id")
                or r.get("kickoff") != f["kickoff"]
                or r.get("league") != f["league"]
                or r.get("competition_profile") != f["competition_profile"]):
            raise ValueError("forecast does not match planned fixture identity")
        m = market_from_key(r["market"])
        if (f["league"], f["competition_profile"], m.key) not in valid_keys:
            raise ValueError("market outside frozen plan")
        if m.key in per_fixture[mid]:
            raise ValueError("duplicate market within one fixture")
        per_fixture[mid].add(m.key)
        if r["outcome"] not in OUTCOMES:
            raise ValueError("only full-time WIN/PUSH/LOSS scored")
        if r["outcome"] == "PUSH" and not m.push_possible:
            raise ValueError("impossible PUSH in non-push market")
        for field in ("raw", "base"):
            p = probability_vector(r[field])
            if not m.push_possible and p[1] != 0:
                raise ValueError("impossible PUSH probability")
        all_rows.append((r, m))
    # A valid original forward scorecard contains the SAME declared candidates
    # for every fixture of a league/profile; an edited subset cannot improve metrics.
    for mid, fixture in fixture_map.items():
        if fixture["status"] != "SCORED":
            continue
        expected = {key for league, profile, key in valid_keys
                    if (league, profile) == (fixture["league"], fixture["competition_profile"])}
        if per_fixture[mid] != expected:
            raise ValueError("market omission from a scored fixture")
    if sum(len(per_fixture[mid]) for mid in per_fixture) != len(observations):
        raise ValueError("inconsistent observation count")
    return role, fixtures, all_rows


def _paired(group_rows):
    outcomes = [OUTCOMES.index(r["outcome"]) for r in group_rows]
    raw = metrics([r["raw"] for r in group_rows], outcomes, bins=10)
    base = metrics([r["base"] for r in group_rows], outcomes, bins=10)
    return {
        "n_rows": len(group_rows),
        "n_distinct_matches": len({r["match_id"] for r in group_rows}),
        "raw": {"brier": raw["brier"], "log_loss": raw["log_loss"], "ece_macro": raw["ece_macro"]},
        "base": {"brier": base["brier"], "log_loss": base["log_loss"], "ece_macro": base["ece_macro"]},
        "delta_base_minus_raw": {
            "brier": base["brier"] - raw["brier"],
            "log_loss": base["log_loss"] - raw["log_loss"],
            "ece_macro": base["ece_macro"] - raw["ece_macro"],
        },
        "direction_note": "Negative Brier/log loss delta favors base, not proof of a real-money edge.",
    }


def _bin_occupancy(rows, *, required):
    buckets = defaultdict(set)
    for r, market in rows:
        # Exact canonical train bin is contract + profile + 0.2-wide raw-WIN bin.
        key = bin_key(market, r["raw"][0], r["competition_profile"])
        buckets[key].add(r["match_id"])
    result = [
        {"bin": key, "distinct_matches": len(matches),
         "min_calibration": required, "remaining_to_min": max(0, required - len(matches)),
         "min_reached": len(matches) >= required}
        for key, matches in sorted(buckets.items())
    ]
    return {
        "observed_bins": len(result),
        "at_or_above_min": sum(r["min_reached"] for r in result),
        "below_min": sum(not r["min_reached"] for r in result),
        "bins": result,
        "warning": "Coverage is a sample-size audit, not fitted calibration or proof that unseen bins are covered.",
    }


def _interval(rows):
    # Pair only rows from the same fixture. Bootstrap GAME DATE clusters,
    # preserving the dependence between all markets from each fixture.
    per_fixture = defaultdict(list)
    dates = {}
    for r in rows:
        mid = r["match_id"]
        y = OUTCOMES.index(r["outcome"])
        raw = r["raw"]; base = r["base"]
        loss_raw = sum((p - (i == y)) ** 2 for i, p in enumerate(raw)) / 2
        loss_base = sum((p - (i == y)) ** 2 for i, p in enumerate(base)) / 2
        per_fixture[mid].append(loss_base - loss_raw)
        dates[mid] = time(r["kickoff"]).astimezone(timezone.utc).date().isoformat()
    clusters = defaultdict(list)
    for mid, errors in per_fixture.items():
        clusters[dates[mid]].append(sum(errors) / len(errors))
    if len(per_fixture) < 30 or len(clusters) < 8:
        return None
    groups = [clusters[k] for k in sorted(clusters)]
    rng = Random(20261008)
    samples = []
    for _ in range(2000):
        drawn = [groups[rng.randrange(len(groups))] for _ in range(len(groups))]
        samples.append(sum(map(sum, drawn)) / sum(map(len, drawn)))
    samples.sort()
    return {
        "low": samples[49], "high": samples[1949], "method": "exploratory paired UTC-day cluster bootstrap",
        "replicates": 2000, "certifies_model": False,
        "unit": "per-fixture average delta Brier across its predefined markets",
    }


def audit(scorecard, *, min_calibration=DEFAULT_BIN_MIN, min_holdout=DEFAULT_HOLDOUT_MIN):
    if type(min_calibration) is not int or min_calibration < 1:
        raise ValueError("positive min calibration")
    if type(min_holdout) is not int or min_holdout < 1:
        raise ValueError("positive min holdout")
    role, fixtures, entries = _validate(scorecard)
    rows = [r for r, _ in entries]
    scored = sum(f["status"] == "SCORED" for f in fixtures)
    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["league"], r["competition_profile"], r["market"])].append(r)
    groups = []
    for (league, profile, market), cohort in sorted(grouped.items()):
        groups.append({"league": league, "competition_profile": profile,
                       "market": market, **_paired(cohort)})
    coverage = scored / len(fixtures)
    fit_presence = scorecard["frozen_build"].get("calibrator_id") is not None
    if not scored:
        state = "NO_SCORABLE_FORECASTS"
    elif role == "CALIBRATION":
        state = "TRAINING_COHORT_ONLY_NO_OUT_OF_SAMPLE_GAIN"
    elif not fit_presence:
        state = "HOLDOUT_WITHOUT_FROZEN_CALIBRATOR"
    elif scored < min_holdout or coverage < DEFAULT_COVERAGE_MIN:
        state = "HOLDOUT_COVERAGE_OR_SAMPLE_INSUFFICIENT"
    else:
        state = "HOLDOUT_DESCRIPTIVE_METRICS_ONLY"
    # Never claim release, monetary permission, or model fit from diagnostics.
    output = {
        "schema": SCHEMA, "source_scorecard_hash": scorecard["hash"],
        "source_plan_id": scorecard["plan_id"], "source_role": role,
        "source_build": scorecard["frozen_build"],
        "source_time": scorecard["at"],
        "status": state, "planned_fixtures": len(fixtures),
        "scored_fixtures": scored, "missing_or_unscored_fixtures": len(fixtures) - scored,
        "fixture_coverage": coverage, "market_observations": len(rows),
        "distinct_matches_scored": len({r["match_id"] for r in rows}),
        "fixture_status_counts": dict(sorted(Counter(f["status"] for f in fixtures).items())),
        "calibration_status_counts": dict(sorted(Counter(r["calibration_status"] for r in rows).items())),
        "bins": _bin_occupancy(entries, required=min_calibration),
        "observed_metrics_by_exact_contract": groups,
        "paired_all_markets": _paired(rows) if rows else None,
        "paired_fixture_cluster_brier_interval": _interval(rows),
        "requirements": {
            "policy_min_calibration_per_exact_bin": min_calibration,
            "policy_min_holdout_distinct_fixtures": min_holdout,
            "research_coverage_target": DEFAULT_COVERAGE_MIN,
            "frozen_calibrator_present": fit_presence,
            "bin_key": "competition_profile:exact_contract:floor(raw_WIN*5)",
        },
        "interpretation": [
            "CALIBRATION is training material and cannot prove out-of-sample improvement.",
            "HOLDOUT performance describes only an already-frozen calibrator; validation and Policy still apply.",
            "Multiple related market scores on one fixture are correlated, not independent observations.",
            "Small ECE is NOT evidence of profit; smaller paired Brier/log loss is better.",
            "Historical already-viewed TEST cannot be recertified as fresh HOLDOUT.",
            "No bookmaker price, no new source data, no refit, no automatic activation.",
            "Original scorecard hash is a self-attested local content checksum, not an external provider signature.",
        ],
        "read_only": True, "parameters_modified": False, "training_performed": False,
        "frozen_artifact_created": False, "holdout_passed": False, "edge_certified": False,
        "monetary_permission": False, "execution_enabled": False, "stake": 0.0,
    }
    output["hash"] = digest(output)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="SEFIROT read-only prospective calibration diagnostics")
    parser.add_argument("scorecard", help="existing original forward-scorecard-v1 JSON")
    parser.add_argument("--output", required=True, help="new report path (never overwrite)")
    args = parser.parse_args(argv)
    try:
        report = audit(json.loads(Path(args.scorecard).read_text(encoding="utf-8")))
        _target = Path(args.output)
        _target.parent.mkdir(parents=True, exist_ok=True)
        with _target.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        print(json.dumps({"status": report["status"], "scored": report["scored_fixtures"],
                          "planned": report["planned_fixtures"], "bins_ready": report["bins"]["at_or_above_min"],
                          "bins_below_min": report["bins"]["below_min"],
                          "calibrator_unchanged": True, "monetary_permission": False},
                         ensure_ascii=False))
        return 0
    except (KeyError, ValueError, TypeError, OSError) as exc:
        parser.exit(2, f"SEFIROT calibration audit: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
