"""Real API-Football observations -> the existing SEFIROT engine, SHADOW only.

No odds, no bookmaker comparisons, no prediction ledger, no API calls,
no fitting/calibration, and no monetary permissions. This only exercises
the original engine.prepare against a dedicated source Repository.
"""
from __future__ import annotations

from datetime import timedelta

from sefirot.contracts import Policy, time
from sefirot.engine import prepare
from sefirot.markets import DEFAULT_POOL
from research.football_pipeline import league_view, model_inputs, source_only, utcnow

LEAGUES = (39, 135, 140)
SEASON = 2026
MAX_SHADOW_TARGETS = 4


def preview(repo, *, as_of=None, ids=None, limit=MAX_SHADOW_TARGETS):
    source_only(repo)  # Never run on the user's prediction/accounting ledger.
    stamp = as_of or utcnow()
    cutoff = time(stamp)
    if cutoff > time(utcnow()) or type(limit) is not int or not 1 <= limit <= MAX_SHADOW_TARGETS:
        raise ValueError("SHADOW_CUTOFF_OR_LIMIT_INVALID")
    if ids is not None and (
            not isinstance(ids, (list, tuple)) or len(ids) > 8 or
            any(type(v) is not int or v < 1 for v in ids) or len(ids) != len(set(ids))):
        raise ValueError("SHADOW_TARGET_IDS_INVALID")

    policy = Policy()  # The original SEFIROT research policy; never override admission gates.
    candidates = []
    for league in LEAGUES:
        coverage = league_view(repo, league, SEASON, as_of=stamp)
        if (coverage["qc_rejected_packets"] or coverage["pending_qc_packets"] or
                not coverage["calendar_complete"]):
            return {"status": "SHADOW_SOURCE_QC_STOP", "league": league,
                    "probability_calibrated": False, "monetary_permission": False}
        for fid, row in coverage["fixtures"].items():
            fid = int(fid)
            kickoff = time(row["fixture"]["date"])
            if (row["fixture"]["status"]["short"] != "NS" or
                    not cutoff < kickoff <= cutoff + timedelta(hours=8) or
                    ids is not None and fid not in ids):
                continue
            candidates.append((kickoff, league, fid))
    candidates.sort()

    previews = []
    for kickoff, league, fid in candidates[:limit]:
        try:
            # 'MEN' and 0.8 are explicitly *research assumptions*, NOT an
            # attestation of provider reliability or confirmed personnel.
            inputs = model_inputs(repo, fid, as_of=stamp, profile="MEN", source_reliability=.8)
            sports = inputs["main"]["sports"]
            if time(sports["as_of"]) >= kickoff or time(utcnow()) >= kickoff:
                previews.append({"fixture_id": fid, "status": "LATE_CUTOFF_PASS"})
                continue
            result = prepare(sports, DEFAULT_POOL, policy, calibrator=None, goal_model=None)
            markets = [
                {"key": c["key"], "raw_win": c["raw"][0],
                 "raw_push": c["raw"][1], "raw_loss": c["raw"][2],
                 "calibration": c["calibration"]}
                for c in result["candidates"]
            ]
            previews.append({
                "fixture_id": fid,
                "league": league,
                "home": sports["match"]["home"],
                "away": sports["match"]["away"],
                "kickoff": sports["match"]["kickoff"],
                "as_of": sports["as_of"],
                "model_version": result["model_version"],
                "model_code_hash": result["model_hash"],
                "policy_hash": policy.fingerprint,
                "input_adapter_hash": inputs["adapter_hash"],
                "source_packets": len(inputs["source_ids"]),
                "team_history_games": result["model"]["team_games"],
                "model_goal_rates": result["model"]["rates"],
                "issues": sorted(set(v["code"] for v in result["issues"])),
                "markets": markets,
                "calibration_status": "NOT_FITTED",
                "raw_model_only": True,
                "profile_and_reliability": "MEN/0.8 RESEARCH ASSUMPTIONS",
                "status": "UNVALIDATED_SHADOW",
                "fit_allowed": False,
                "ev": None,
                "stake": 0,
                "decision": "PASS",
            })
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            previews.append({"fixture_id": fid, "status": "SHADOW_INPUT_STOP",
                             "error_type": type(exc).__name__, "decision": "PASS"})
    return {
        "schema": "sefirot-core-shadow-preview-v1",
        "status": "SHADOW_PREVIEW_COMPLETE",
        "at": stamp,
        "inputs_considered": len(candidates),
        "inputs_evaluated": len(previews),
        "previews": previews,
        "provider_requests": 0,
        "canonical_predictions_written": 0,
        "calibration_fit_allowed": False,
        "probability_calibrated": False,
        "monetary_permission": False,
        "execution_enabled": False,
    }
