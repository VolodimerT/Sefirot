"""Offline FootyStats Premium/free Match CSV research validation, no network."""
import argparse
import csv
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.provider_compare.footystats_csv import inspect_csv, MAX_CSV_BYTES


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True, help="local manually downloaded CSV")
    p.add_argument("--season", required=True, help="explicit operator-declared season, e.g. 2018/19")
    p.add_argument("--received-at", required=True, help="actual CSV first-observed timestamp with timezone")
    p.add_argument("--expected-matches", type=int, default=None)
    p.add_argument("--output", type=Path, required=True, help="a new file; never overwritten")
    args = p.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        p.error("input/output must differ")
    try:
        with args.input.open("rb") as src:
            data = src.read(MAX_CSV_BYTES + 1)
        report = inspect_csv(data, season=args.season,
                             received_at=args.received_at,
                             expected_matches=args.expected_matches)
        # Do not export original data rows or new opponent names to report.
        summary = {k: v for k, v in report.items() if k != "records"}
        with args.output.open("x", encoding="utf-8") as out:
            json.dump(summary, out, ensure_ascii=False, indent=2, allow_nan=False)
            out.write("\n")
        print(json.dumps({"status": report["status"], "matches": report["count"],
                          "goals": report["coverage"]["complete_goal_scores"],
                          "corners": report["coverage"]["complete_corner_scores"],
                          "training_allowed": False}))
    except (OSError, ValueError, TypeError, csv.Error) as exc:
        p.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()
