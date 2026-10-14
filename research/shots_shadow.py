"""Count-only SHOTS/SOT math lab; not CORE, fit command or source attestation."""
from math import comb, fsum, isfinite
from sefirot.contracts import digest
from sefirot.corners_shadow import _pmf

def parameters_from_paired_counts(rows):
    if not isinstance(rows,list) or len(rows)<20:
        raise ValueError("INSUFFICIENT_PAIRED_SHOT_COUNTS")
    seen=set()
    for r in rows:
        if not isinstance(r,dict) or set(r)!={"fixture_id","shots","sot"}:
            raise ValueError("PAIRED_EXACT_COUNT_FIELDS")
        if not isinstance(r["fixture_id"],str) or not r["fixture_id"] or r["fixture_id"] in seen:
            raise ValueError("UNIQUE_FIXTURE_ID_REQUIRED")
        seen.add(r["fixture_id"])
        if any(type(r[k]) is not int or not 0<=r[k]<=300 for k in ("shots","sot")):
            raise ValueError("MISSING_IS_NOT_ZERO")
        if r["sot"]>r["shots"]:raise ValueError("SOT_EXCEEDS_SHOTS")
    total=fsum(r["shots"] for r in rows)
    return {"method":"OWN_SHOT_COUNT_POISSON_AND_CONDITIONAL_BINOMIAL",
        "shots_mean":total/len(rows),"sot_mean":fsum(r["sot"] for r in rows)/len(rows),
        "sot_given_shot":fsum(r["sot"] for r in rows)/total if total else None,
        "distinct_fixtures":len(rows),"counts_hash":digest(rows),
        "status":"MATHEMATICAL_LAB_UNCALIBRATED","source_attested":False,
        "monetary_permission":False}

def count_joint(shots_mean,sot_given_shot):
    if (type(shots_mean) not in (int,float) or not isfinite(shots_mean)
        or type(sot_given_shot) not in (int,float) or not isfinite(sot_given_shot)
        or not 0<=sot_given_shot<=1):
        raise ValueError("EXPLICIT_COUNT_RATE_AND_THINNING_REQUIRED")
    # Reuse the existing count PMF, not the football goal predictor.
    shots=_pmf(shots_mean,None)
    joint={(n,k):pn*comb(n,k)*sot_given_shot**k*(1-sot_given_shot)**(n-k)
           for n,pn in enumerate(shots) if pn for k in range(n+1)}
    if abs(fsum(joint.values())-1)>1e-8:raise ValueError("COUNT_TAIL_NOT_BOUNDED")
    return joint
