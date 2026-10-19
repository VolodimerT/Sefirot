"""SHADOW family matrix over existing observation QC; never fit, fetch or admit."""
from pathlib import Path
from hashlib import sha256
from sefirot.contracts import digest
from research.small_observation_v2 import audit_dataset, PERIODS
from scripts.small_market_qc import readiness_without_archive
from research.referee_yc_shadow import inspect_referee

FAMILY_SPECS = {"CORNERS": {"metrics": ("CORNERS",),
    "method": "CORNERS_SHADOW_V0_POISSON_NEGATIVE_BINOMIAL",
    "module": "src/sefirot/corners_shadow.py",
    "rate_basis": "OWN_CORNER_COUNTS; 2H_FROM_SAME_TYPED_FT_MINUS_1H",
    "extra_blockers": []},
    "SHOTS_SOT": {"metrics": ("SHOTS", "SOT"),
        "method": "OWN_SHOT_POISSON_WITH_CONDITIONAL_SOT_BINOMIAL_UNVALIDATED",
        "module": "research/shots_shadow.py",
        "rate_basis": "OWN_PAIRED_SAME_FIXTURE_SHOTS_AND_SOT_COUNTS",
        "extra_blockers": ["PAIRED_SHOTS_SOT_SOURCE_DEFINITION_NOT_ATTESTED"]},
    "FOULS": {"metrics": ("FOULS_COMMITTED", "FOULS_SUFFERED"),
        "method": "OWN_DIRECT_COMMITTED_AND_SUFFERED_FOUL_POISSON_UNVALIDATED",
        "module": "research/fouls_shadow.py",
        "rate_basis": "OWN_DIRECT_FOUL_COUNTS; NO_YC_OR_OPPONENT_PROXY",
        "extra_blockers": ["FOUL_DIRECTION_AND_STYLE_NOT_ATTESTED"]},
    "YC": {"metrics": ("YELLOW_CARDS",),
        "method": "OWN_YC_COUNT_BASELINE_REFEREE_GATED_UNVALIDATED",
        "module": "research/referee_yc_shadow.py", "rate_basis": "OWN_YC_COUNTS; NO_FOUL_SURROGATE",
        "extra_blockers": ["REFEREE_GATE_HOLD", "PREMATCH_CONFIRMED_REFEREE_REQUIRED",
            "YC_PER_GAME_AND_FOUL_REQUIRED", "RISK_0_1_REQUIRED", "NO_CLEANER_MARKET_PROOF_REQUIRED"]}}
ROOT = Path(__file__).resolve().parents[1]


def family_report(family, *, data=None, at):
    if family not in FAMILY_SPECS:
        raise ValueError("UNSUPPORTED_SHADOW_FAMILY")
    spec = FAMILY_SPECS[family]
    qc = audit_dataset(data, at) if data is not None else readiness_without_archive(at)
    selected = [r for r in qc["markets"] if r["metric"] in spec["metrics"]]
    # Existing observation-v2 has no direct suffered field. Preserve its schema
    # and show the missing direction; never infer it from opponent committed/YC.
    missing_metrics = set(spec["metrics"]) - {r["metric"] for r in selected}
    for metric in sorted(missing_metrics):
        for period in PERIODS:
            denominator = qc.get("eligible_unique_fixture_count")
            selected.append({"metric": metric, "period": period,
                "eligible_denominator": denominator, "known_fixtures": 0 if denominator is not None else None,
                "missing_fixtures": denominator, "observed_coverage": None,
                "blockers": ["DIRECT_METRIC_NOT_AVAILABLE_IN_OBSERVATION_V2",
                    "SOURCE_ORIGIN_NOT_ATTESTED", "SETTLEMENT_NOT_ATTESTED", "NO_INDEPENDENT_HOLDOUT"]})
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
    if family == "YC":
        result["referee_gate"] = inspect_referee()
        for row in result["matrix"]:
            row["blockers"] = sorted(set(row["blockers"]) | set(result["referee_gate"]["blockers"]))
            row["status"] = "HOLD/PASS"
    result["hash"] = digest(result)
    return result
