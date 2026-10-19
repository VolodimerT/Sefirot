"""Referee prerequisite inspector; self-declared facts cannot authorize YC P/EV."""
from math import fsum,isfinite
import re
from sefirot.contracts import digest,time

FIELDS={"fixture_id","kickoff","referee_id","confirmed_at","yc_per_game","yc_per_foul",
        "risk","rules_version","cleaner_market_exists","calibration_hash","ev"}
REQUIREMENTS={"fixture_id":"EXACT_FIXTURE_ID_REQUIRED","kickoff":"TARGET_KICKOFF_REQUIRED",
    "referee_id":"CONFIRMED_REFEREE_REQUIRED","confirmed_at":"PREMATCH_REFEREE_RECEIPT_REQUIRED",
    "yc_per_game":"YC_PER_GAME_REQUIRED","yc_per_foul":"YC_PER_FOUL_REQUIRED","risk":"RISK_0_1_REQUIRED",
    "rules_version":"STAKE_YC_RULES_REQUIRED","cleaner_market_exists":"NO_CLEANER_MARKET_PROOF_REQUIRED",
    "calibration_hash":"INDEPENDENT_YC_CALIBRATION_REQUIRED","ev":"VERIFIED_YC_EV_REQUIRED"}

def inspect_referee(context=None):
    facts=context if isinstance(context,dict) else {}
    blockers={"INDEPENDENT_REFEREE_SOURCE_ORIGIN_NOT_ATTESTED"}
    missing=[k for k in sorted(FIELDS) if facts.get(k) is None]
    blockers.update(REQUIREMENTS[k] for k in missing if k in REQUIREMENTS)
    if context is not None and (not isinstance(context,dict) or set(context)-FIELDS):
        blockers.add("CALLER_ATTESTATION_OR_UNKNOWN_FIELDS_REJECTED")
    for key in ("yc_per_game","yc_per_foul","risk","ev"):
        value=facts.get(key)
        if value is not None and (type(value) not in (int,float) or not isfinite(value)):
            blockers.add("INVALID_REFEREE_NUMBER")
        elif value is not None:
            if key=="risk" and not 0<=value<=1:blockers.add("RISK_OUTSIDE_0_1")
            if key in ("yc_per_game","yc_per_foul") and value<0:blockers.add("NEGATIVE_REFEREE_RATE")
            if key=="ev" and value<=0:blockers.add("NO_VERIFIED_POSITIVE_EV")
    for key in ("fixture_id","referee_id","rules_version"):
        if facts.get(key) is not None and (not isinstance(facts[key],str) or not facts[key].strip()):
            blockers.add("INVALID_REFEREE_ID_OR_RULES")
    if facts.get("cleaner_market_exists") is not None:
        if type(facts["cleaner_market_exists"]) is not bool:blockers.add("CLEANER_MARKET_STATE_NOT_BOOLEAN")
        elif facts["cleaner_market_exists"]:blockers.add("CLEANER_MAIN_MARKET_EXISTS")
    if facts.get("calibration_hash") is not None and (not isinstance(facts["calibration_hash"],str)
        or not re.fullmatch("[a-f0-9]{64}",facts["calibration_hash"])):
        blockers.add("INVALID_CALIBRATION_CONTENT_REFERENCE")
    if facts.get("confirmed_at") is not None and facts.get("kickoff") is not None:
        try:
            if time(facts["confirmed_at"])>=time(facts["kickoff"]):blockers.add("REFEREE_NOT_CONFIRMED_PREMATCH")
        except ValueError:blockers.add("INVALID_REFEREE_CHRONOLOGY")
    # No deployed independent attestation authority is installed. Shape/caller
    # claims/risk numbers/hashes never become verified source/calibration/EV.
    return {"schema":"referee-yc-gate-v1","status":"HOLD","decision":"PASS","class":"D",
        "missing_fields":missing,"blockers":sorted(blockers),"source_attested":False,
        "probability":None,"ev":None,"monetary_permission":False,"stake":0.0}

def own_yc_count_parameters(rows):
    if not isinstance(rows,list) or len(rows)<20:raise ValueError("INSUFFICIENT_OWN_YC_COUNTS")
    seen=set();refs=set()
    for r in rows:
        if not isinstance(r,dict) or set(r)!={"fixture_id","referee_id","yc"}:
            raise ValueError("OWN_YC_FIELDS_NO_FOUL_PROXY")
        if any(not isinstance(r[k],str) or not r[k] for k in ("fixture_id","referee_id")):
            raise ValueError("FIXTURE_REFEREE_IDS_REQUIRED")
        if r["fixture_id"] in seen:raise ValueError("DUPLICATE_FIXTURE")
        seen.add(r["fixture_id"]);refs.add(r["referee_id"])
        if type(r["yc"]) is not int or not 0<=r["yc"]<=40:raise ValueError("KNOWN_YC_COUNT_REQUIRED")
    if len(refs)!=1:raise ValueError("SAME_REFEREE_LAB_SCOPE_REQUIRED")
    return {"method":"OWN_YC_COUNT_BASELINE_UNCALIBRATED","own_yc_mean":fsum(r["yc"] for r in rows)/len(rows),
        "counts_hash":digest(rows),"source_attested":False,"referee_gate_passed":False,
        "probability":None,"ev":None,"monetary_permission":False}
