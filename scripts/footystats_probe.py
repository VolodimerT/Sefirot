"""CLI to inspect one locally saved FootyStats JSON response. No HTTP or API keys."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.provider_compare.footystats import inspect


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True, help="existing JSON sample; never provide secrets")
    p.add_argument("--season-id", type=int, required=True)
    p.add_argument("--received-at", required=True, help="actual UTC collection timestamp; never backdate")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--output", type=Path, required=True, help="new file, no overwrite")
    args = p.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        p.error("input and output must differ")
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        report = inspect(data, season_id=args.season_id, received_at=args.received_at, expected_page=args.page)
        # Do not allow accidentally publishing personal packets or bookmaker keys.
        safe = {k: v for k, v in report.items() if k != "records"}
        safe["example_records"] = report["records"][:3]
        with args.output.open("x", encoding="utf-8") as f:
            json.dump(safe, f, indent=2, ensure_ascii=False, allow_nan=False)
            f.write("\n")
        print(json.dumps({"status": report["status"], "fixtures": report["fixture_count"], "training_allowed": False}))
    except (ValueError, OSError, TypeError, json.JSONDecodeError) as exc:
        p.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()
