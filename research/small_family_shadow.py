"""SHADOW family matrix over existing observation QC; never fit, fetch or admit."""
from pathlib import Path
from hashlib import sha256
from sefirot.contracts import digest
from research.small_observation_v2 import audit_dataset, PERIODS
from scripts.small_market_qc import readiness_without_archive

FAMILY_SPECS = {"CORNERS": {"metrics": ("CORNERS",),
    "method": "CORNERS_SHADOW_V0_POISSON_NEGATIVE_BINOMIAL",
    "module": "src/sefirot/corners_shadow.py",
    "rate_basis": "OWN_CORNER_COUNTS; 2H_FROM_SAME_TYPED_FT_MINUS_1H",
    "extra_blockers": []}}
ROOT = Path(__file__).resolve().parents[1]


def family_report(family, *, data=None, at):
    if family not in FAMILY_SPECS:
        raise ValueError("UNSUPPORTED_SHADOW_FAMILY")
    spec = FAMILY_SPECS[family]
    qc = audit_dataset(data, at) if data is not None else readiness_without_archive(at)
    selected = [r for r in qc["markets"] if r["metric"] in spec["metrics"]]
    matrix = []
    for row in selected:
        for scope in ("MATCH", "HOME", "AWAY"):
            matrix.append({"market": row["metric"]+":"+row["period"]+":"+scope,
                "metric": row["metric"], "period": row["period"], "scope": scope,
                "source": "NOT_INDEPENDENTLY_VERIFIED",
                "eligible_denominator": row["eligible_denominator"],
                "known_fixtures": row.get("known_fixtures"),
                "missing_fixtures": row.get("missing_fixtures"),
                "observed_coverage": row.get("observed_coverage"), "verified_coverage": None,
                "model": spec["method"], "model_parameters": None,
                "rate_basis": spec["rate_basis"], "calibration": "NOT_VERIFIED",
                "quote_rules": "NOT_VERIFIED", "probability": None, "ev": None,
                "status": "INSUFFICIENT_REAL_DATA", "fit_allowed": False,
                "blockers": sorted(set(row["blockers"]) | set(spec["extra_blockers"]))})
    result = {"schema": "small-family-shadow-matrix-v1", "family": family,
        "at": qc.get("evaluated_at", at), "status": "INSUFFICIENT_REAL_DATA",
        "input_qc_hash": qc.get("report_hash"), "source_attested": False,
        "source_code_sha256": sha256((ROOT/spec["module"]).read_bytes()).hexdigest(),
        "model_imported_by_CORE": False, "original_CORE_modified": False, "matrix": matrix,
        "source_requirements": ["PERMITTED_FULL_LEAGUE_SEASON_MANIFEST",
            "EXACT_FIXTURE_TEAM_PERIOD_IDS", "UTC_PUBLICATION_RECEIPT_REVISION",
            "IMMUTABLE_RAW_RECEIPTS_AND_HASH_BINDINGS", "MISSING_IS_NOT_ZERO",
            "INDEPENDENT_SOURCE_ORIGIN", "STAKE_SETTLEMENT_AND_REAL_TIMESTAMPED_QUOTE"],
        "builder": {"status": "UNPRICED/RESEARCH_ONLY", "joint_probability": None,
            "combined_bookmaker_quote": None, "marginal_product_used": False,
            "required": ["VERIFIED_JOINT_DISTRIBUTION", "ACTUAL_COMBINED_BOOKMAKER_QUOTE"]},
        "network_requests": 0, "real_training_performed": False,
        "holdout_passed": False, "statistical_profitability_proven": False,
        "monetary_permission": False, "execution_enabled": False, "stake": 0.0}
    result["hash"] = digest(result)
    return result
