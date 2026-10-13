"""Explain missing team history from ORIGINAL SEFIROT data-session reports.

No external API call, guessing of scores, relabelling of results, or rerun
of previously reviewed TEST as a new HOLDOUT. Supports offline remediation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.contracts import digest, time

BLOCKING_PROVIDER = (
    "PROVIDER_ACCOUNT_SUSPENDED", "PROVIDER_ACCESS_DENIED",
    "PROVIDER_AUTH_FAILED", "PROVIDER_QUOTA_EXHAUSTED",
    "CREDENTIAL_MISSING_OR_INVALID", "PROVIDER_NETWORK_UNAVAILABLE",
)


def analyze(reports):
    if not isinstance(reports, list) or not reports:
        raise ValueError("at least one real data-session report required")
    seen, matches, provider_failures, statuses = set(), {}, Counter(), Counter()
    for report in reports:
        if not isinstance(report, dict) or report.get("schema") != "api-data-session-v1":
            raise ValueError("original api-data-session-v1 report required")
        data = dict(report); sig = data.pop("hash", None)
        if not isinstance(sig, str) or sig != digest(data):
            raise ValueError("data-session source hash mismatch")
        if report.get("monetary_permission") is not False or report.get("execution_enabled") is not False:
            raise ValueError("only research-only source sessions accepted")
        identifier = (report["started_at"], report["day"], report["output_directory"])
        if identifier in seen:
            raise ValueError("same data session passed twice")
        seen.add(identifier)
        for blocker in report.get("blockers", []):
            if blocker in BLOCKING_PROVIDER:
                provider_failures[blocker] += 1
        for item in report.get("fixtures", []):
            status = item["status"]
            statuses[status] += 1
            mid = item["match_id"]
            if mid in matches:
                # Duplicated fixture observations do not increase cohort size.
                matches[mid]["seen_in_multiple_sessions"] = True
                continue
            coverage = item.get("coverage") or {}
            teams = coverage.get("teams") or {}
            deficits = {}
            for side in ("home", "away"):
                row = teams.get(side) or {}
                n = row.get("games_needed")
                if type(n) is not int or n < 0:
                    n = None
                deficits[side] = {
                    "team": row.get("name"), "eligible_games": row.get("eligible_games"),
                    "missing_games": n,
                }
            match = coverage.get("match") or {}
            matches[mid] = {
                "match_id": mid, "status": status, "kickoff": match.get("kickoff"),
                "league": match.get("league"), "deficits": deficits,
                "coverage_blockers": coverage.get("blockers", []),
                "observed_history_seasons": coverage.get("observed_history_seasons", {}),
                "excluded_history_reasons": coverage.get("exclusion_reasons", {}),
                "seen_in_multiple_sessions": False,
            }
    missing = [r for r in matches.values() if r["status"] == "INSUFFICIENT_HISTORY"]
    missing.sort(key=lambda r: (
        -sum((v["missing_games"] or 0) for v in r["deficits"].values()),
        r["match_id"],
    ))
    blocked = bool(provider_failures)
    result = {
        "schema": "calibration-history-triage-v1",
        "session_count": len(reports), "unique_fixtures": len(matches),
        "status_counts": dict(sorted(statuses.items())),
        "insufficient_history_fixtures": len(missing),
        "missing_team_games": missing,
        "provider_blockers": dict(sorted(provider_failures.items())),
        "action": "RECOVER_PROVIDER_ACCESS_FIRST" if blocked else
                  "IMPORT_AUTHENTIC_OLDER_RECEIPTS_BEFORE_NEXT_PREMATCH_SEAL",
        "remediation": [
            "Resolve provider suspension through account owner; do not rotate/bypass credentials.",
            "Reuse an actual pre-existing sports-archive with immutable original receipt timestamps.",
            "When provider permits, fetch legitimate completed FT history for declared league/seasons, not only the target season.",
            "Never backdate newly collected FT packets into an old pre-match timestamp; old missed matches stay missed.",
            "Repeat only for future preassigned fixtures; do not reconstruct and call them CALIBRATION/HOLDOUT.",
            "Review fixture counts with new capture and original forward-scorecard before trying calibration_fit_gate --fit.",
        ],
        "api_calls": 0, "fitting_done": False, "forecast_backfilled": False,
        "monetary_permission": False, "execution_enabled": False,
    }
    result["hash"] = digest(result)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Identify calibration collection blockers in archived sessions")
    p.add_argument("reports", nargs="+", help="original REPORT.json from one or more data-session folders")
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    try:
        result = analyze([json.loads(Path(x).read_text(encoding="utf-8")) for x in args.reports])
        path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        print(json.dumps({"missing_history": result["insufficient_history_fixtures"],
                          "action": result["action"], "api_calls": 0},
                         ensure_ascii=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        p.exit(2, f"History triage: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
