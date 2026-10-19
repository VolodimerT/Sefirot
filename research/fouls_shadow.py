"""Independent direct foul-count math lab; never maps fouls to yellow cards."""
from math import fsum
from sefirot.contracts import digest
from sefirot.corners_shadow import _pmf

def parameters_from_direct_counts(rows):
    if not isinstance(rows,list) or len(rows)<20:raise ValueError("INSUFFICIENT_DIRECT_FOUL_COUNTS")
    seen=set()
    for r in rows:
        if not isinstance(r,dict) or set(r)!={"fixture_id","committed","suffered","style"}:
            raise ValueError("DIRECT_SEPARATE_FOUL_FIELDS_REQUIRED")
        if not isinstance(r["fixture_id"],str) or not r["fixture_id"] or r["fixture_id"] in seen:
            raise ValueError("UNIQUE_FIXTURE_ID_REQUIRED")
        seen.add(r["fixture_id"])
        if any(type(r[k]) is not int or not 0<=r[k]<=100 for k in ("committed","suffered")):
            raise ValueError("MISSING_IS_NOT_ZERO")
        if r["style"] is not None and (not isinstance(r["style"],str) or not r["style"]):
            raise ValueError("EXPLICIT_STYLE_OR_UNKNOWN_REQUIRED")
    return {"method":"DIRECT_FOUL_COUNT_POISSON_UNCALIBRATED",
        "committed_mean":fsum(r["committed"] for r in rows)/len(rows),
        "suffered_mean":fsum(r["suffered"] for r in rows)/len(rows),
        "style_status":"NOT_INDEPENDENTLY_ATTESTED_NO_ADJUSTMENT",
        "distinct_fixtures":len(rows),"counts_hash":digest(rows),
        "yellow_card_probability":None,"source_attested":False,"monetary_permission":False}

def count_mass(own_foul_mean):
    if type(own_foul_mean) not in (int,float):raise ValueError("OWN_FOUL_RATE_REQUIRED")
    return _pmf(own_foul_mean,None)
