"""Fail-closed preflight and OPTIONAL real fitting of original calibration records.

Runs on user's local SEFIROT research.sqlite, not on historical demo reports.
No provider authentication, no new forecasts, no money gate, no deployment.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.contracts import Policy, digest, time
from sefirot.forward_scorecard import _forecast_valid, _receipt
from sefirot.identity import model_code_hash
from sefirot.markets import market_from_key, settle
from sefirot.probability import bin_key
from sefirot.repository import Repository
from sefirot.service import Service

SCHEMA = "calibration-fit-gate-v1"
TRAINING_FIXTURE_FLOOR = 60  # research safety floor; not the core holdout release criterion
MIN_CAPTURE_COVERAGE = 0.80


def _signed(record):
    if not isinstance(record, dict):
        return False
    s = dict(record)
    signature = s.pop("id", None)
    return isinstance(signature, str) and signature == digest(s)


def _source_result_proofs(jobs):
    by_id = defaultdict(list)
    for job in jobs:
        if not isinstance(job, dict) or job.get("schema") != "api-forward-result-source-v1":
            continue
        if not _signed(job) or not _receipt(job.get("receipt"), job.get("at")):
            raise ValueError("invalid API result-source job")
        for result in job.get("api_results", []):
            if (result.get("source") != "API_FOOTBALL_V3:" + job["packet_hash"]
                    or time(result["received_at"]) != time(job["receipt"]["received_at"])):
                raise ValueError("result API binding mismatch")
            by_id[result["match_id"]].append(result)
    return by_id


def _capture_proofs(jobs):
    by_prediction = defaultdict(list)
    for job in jobs:
        if not isinstance(job, dict) or job.get("schema") != "api-forward-capture-v1":
            continue
        if not _signed(job):
            raise ValueError("invalid API capture job")
        for attempt in job.get("attempts", []):
            if attempt.get("status") == "SEALED_RESEARCH":
                by_prediction[attempt["prediction_id"]].append((job, attempt))
    return by_prediction


def _checked_record(record, plan, member, assignment, prediction, result, capture, sourced):
    if not isinstance(record, dict) or not isinstance(prediction, dict):
        raise ValueError("calibration record/prediction missing")
    if not _forecast_valid(prediction, plan, member, assignment):
        raise ValueError("invalid original prospectively sealed prediction")
    if prediction.get("calibrator") is not None:
        raise ValueError("training input reuses fitted calibrator")
    if record.get("synthetic") is not False or record.get("captured_prematch") is not True:
        raise ValueError("training record must be real and prematch")
    if (record["prediction_id"] != prediction["id"] or
            record["match_id"] != member["match"]["id"] or
            record["model_id"] != prediction["model_id"] or
            record.get("calibrator_id") is not None or
            record.get("model_hash") != prediction["model_hash"] or
            record["sealed_at"] != prediction["sealed_at"] or
            record["kickoff"] != member["match"]["kickoff"]):
        raise ValueError("calibration record/forecast identity mismatch")
    if (not isinstance(result, dict) or result.get("status") != "FINISHED" or
            result not in sourced or
            not time(member["match"]["kickoff"]) < time(result["finished_at"]) <=
            time(result["received_at"]) <= time(record["received_at"])):
        raise ValueError("no original source-backed FT result for calibration")
    if not any(
        proof.get("sports_hash") == digest(prediction["sports"])
        and proof.get("source_receipts")
        and all(_receipt(r, prediction["sealed_at"]) for r in proof["source_receipts"])
        and time(proof["at"]) <= time(prediction["sealed_at"]) <= time(job["at"])
        and job.get("plan_id") == plan["id"]
        for job, proof in capture
    ):
        raise ValueError("no original source-backed prematch capture proof")
    market = market_from_key(record["market"])
    candidates = [c for c in prediction["candidates"] if c["key"] == market.key]
    if len(candidates) != 1 or record.get("kind") != market.kind:
        raise ValueError("market not uniquely present in original sealed universe")
    candidate = candidates[0]
    if (record.get("raw_probabilities") != candidate["raw"]
            or record.get("probabilities") != candidate["base"]
            or abs(record.get("raw_win", -1) - candidate["raw"][0]) > 1e-12
            or record["outcome"] != settle(market, result["home_goals"], result["away_goals"])):
        raise ValueError("record probabilities or outcome changed after capture")
    if record.get("competition_profile") != member["match"]["competition_profile"]:
        raise ValueError("competition profile mismatch")
    if time(record["received_at"]) >= time(plan["at"]) and time(record["sealed_at"]) < time(record["received_at"]):
        return bin_key(market, record["raw_win"], record["competition_profile"])
    raise ValueError("invalid calibration record chronology")


def assess(repository, policy, at):
    """Inspect all original training data. Any invalid member blocks the entire fit."""
    if not repository.verify():
        raise ValueError("SEFIROT append-only journal integrity failed")
    jobs = repository.all("jobs", at)
    source_results = _source_result_proofs(jobs)
    captures = _capture_proofs(jobs)
    assignments = {a["match_id"]: a for a in repository.all("split_assignments", at)}
    records = [r for r in repository.all("calibration_history", at)
               if assignments.get(r["match_id"], {}).get("role") == "CALIBRATION"
               and r.get("calibrator_id") is None]
    plans = {}
    for j in jobs:
        if j.get("schema") != "api-forward-plan-v1":
            continue
        if not _signed(j):
            raise ValueError("corrupt original API-forward plan")
        if j["role"] != "CALIBRATION":
            continue
        for m in j["members"]:
            mid = m["match"]["id"]
            if mid in plans:
                raise ValueError("fixture appears in multiple calibration plans")
            plans[mid] = (j, m)
    predictions = {p["id"]: p for p in repository.all("predictions", at)}
    results = {r["match_id"]: r for r in repository.all("results", at)}
    ledger_records = repository.all("calibration_history", at)
    ids = {(r["match_id"], r["market"]) for r in records}
    if len(ids) != len(records):
        raise ValueError("duplicate match-market observations")
    blockers = []
    bucket_matches = defaultdict(set)
    contract_matches = defaultdict(set)
    verified = set()
    model_ids = set()
    for r in records:
        mid = r["match_id"]
        try:
            if mid not in plans or mid not in assignments:
                raise ValueError("training observation has no original calibration plan")
            plan, member = plans[mid]
            pred = predictions.get(r["prediction_id"])
            bucket = _checked_record(r, plan, member, assignments[mid], pred,
                                     results.get(mid), captures.get(r["prediction_id"], []),
                                     source_results.get(mid, []))
            bucket_matches[bucket].add(mid)
            contract_matches[(r["competition_profile"], r["market"])].add(mid)
            model_ids.add(r["model_id"])
            verified.add(mid)
        except (ValueError, KeyError, TypeError) as exc:
            blockers.append({"match_id": mid, "market": r.get("market"),
                             "reason": str(exc)})
    # Validate ALL calibratable records, not a cherry-picked subset. The
    # canonical Service.calibrate would fit every assigned raw record.
    selected = {(r["match_id"], r["market"]) for r in records}
    if any(r["calibrator_id"] is None and
           assignments.get(r["match_id"], {}).get("role") == "CALIBRATION" and
           (r["match_id"], r["market"]) not in selected for r in ledger_records):
        blockers.append({"reason": "a calibration record was excluded"})
    if len(model_ids) != 1 and records:
        blockers.append({"reason": "multiple fitted-code identities in training records"})
    if len(model_ids) == 1:
        model_id = next(iter(model_ids))
        model = repository.get("model_versions", model_id)
        if model.get("model_hash") != model_code_hash() or model.get("policy_hash") != policy.fingerprint:
            blockers.append({"reason": "current model or Policy cannot fit archived predictions"})
    else:
        model_id = None
    available = {key: len(v) for key, v in sorted(bucket_matches.items())}
    by_contract = {profile + ":" + contract: {
        "distinct_matches": len(matches),
        "populated_bins": sum(
            name.rsplit(":", 1)[0] == profile + ":" + contract
            and n >= policy.min_calibration
            for name, n in available.items()
        ),
    } for (profile, contract), matches in sorted(contract_matches.items())}
    planned_ids = set(plans)
    verified_planned = verified & planned_ids
    coverage = len(verified_planned) / len(planned_ids) if planned_ids else 0.
    if not records:
        blockers.append({"reason": "NO_CALIBRATION_RECORDS"})
    if len(verified) < TRAINING_FIXTURE_FLOOR:
        blockers.append({"reason": "INSUFFICIENT_DISTINCT_CALIBRATION_MATCHES",
                         "needed": max(0, TRAINING_FIXTURE_FLOOR-len(verified))})
    if planned_ids and coverage < MIN_CAPTURE_COVERAGE:
        blockers.append({"reason": "PLANNED_COHORT_COVERAGE_LOW"})
    if not by_contract or any(v["populated_bins"] == 0 for v in by_contract.values()):
        blockers.append({"reason": "NO_READY_BIN_IN_EVERY_OBSERVED_CONTRACT"})
    result = {
        "schema": SCHEMA, "at": at, "read_only_check": True,
        "record_count": len(records), "verified_distinct_matches": len(verified),
        "planned_distinct_matches": len(planned_ids), "verified_plan_coverage": coverage,
        "fit_model_id": model_id, "exact_bin_occupancy": available,
        "contracts": by_contract,
        "minimum_per_exact_bin": policy.min_calibration,
        "research_fixture_floor": TRAINING_FIXTURE_FLOOR,
        "blockers": blockers,
        "fit_ready": not blockers, "fit_performed": False,
        "model_activated": False, "validation_passed": False,
        "requires_new_independent_holdout": True,
        "monetary_permission": False, "execution_enabled": False, "stake": 0.,
    }
    result["hash"] = digest(result)
    return result


def run(db, *, output, fit=False):
    path = Path(db)
    if not path.is_file():
        raise ValueError("existing research ledger required; no database was created")
    target = Path(output)
    if target.exists():
        raise ValueError("output already exists")
    policy = Policy()
    now = datetime.now(timezone.utc).isoformat()
    ro = Repository(path, read_only=True)
    try:
        report = assess(ro, policy, now)
    finally:
        ro.close()
    if fit:
        if not report["fit_ready"]:
            raise ValueError("calibration preflight blocked: fit not performed")
        rw = Repository(path)
        try:
            service = Service(rw, policy)
            fresh = assess(rw, policy, service.now())
            if not fresh["fit_ready"] or fresh["fit_model_id"] != report["fit_model_id"]:
                raise ValueError("calibration preflight changed; fit blocked")
            artifact = service.calibrate(service.now())
            report["fit_performed"] = True
            report["created_calibrator_hash"] = artifact["hash"]
            # Service.calibrate only creates a new immutable artifact; it
            # does not activate a model or certify Holdout.
            report.pop("hash")
            report["hash"] = digest(report)
        finally:
            rw.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Original API-forward calibration fit gate")
    parser.add_argument("--db", required=True, help="existing research.sqlite ledger")
    parser.add_argument("--output", required=True)
    parser.add_argument("--fit", action="store_true",
                        help="write a frozen calibrator ONLY when all real-data gates pass")
    args = parser.parse_args(argv)
    try:
        report = run(args.db, output=args.output, fit=args.fit)
        print(json.dumps({
            "status": "FITTED_FROZEN_ARTIFACT" if report["fit_performed"] else
                      "READY_TO_FIT" if report["fit_ready"] else "COLLECTION_BLOCKED",
            "verified_matches": report["verified_distinct_matches"],
            "planned_matches": report["planned_distinct_matches"],
            "fit": report["fit_performed"], "monetary_permission": False
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, "Calibration fit gate: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
