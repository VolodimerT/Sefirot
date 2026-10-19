"""Explicit offline PREMATCH scenario or read-only operator view. No provider I/O."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from research.prematch_readiness import operator_report
from research.prematch_scenario import run_scenario


def main(argv=None):
    parser = argparse.ArgumentParser(description="SEFIROT PREMATCH: чтение готовности без API и ставок")
    parser.add_argument("--synthetic-e2e", action="store_true")
    parser.add_argument("--db")
    parser.add_argument("--at")
    parser.add_argument("--prediction-id")
    args = parser.parse_args(argv)
    if args.synthetic_e2e and any((args.db, args.at, args.prediction_id)):
        parser.error("synthetic scenario cannot use an operator ledger or cutoff")
    try:
        result = run_scenario() if args.synthetic_e2e else operator_report(
            args.db, at=args.at, prediction_id=args.prediction_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError):
        print("SEFIROT: данные не подтверждены; операция закрыта.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
