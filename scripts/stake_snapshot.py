"""Create a research-only Stake sportsbook snapshot for one sealed prediction.

Usage:
  python scripts/stake_snapshot.py --db data/sefirot.sqlite PREDICTION_ID --output data/stake.json

Requires STAKE_API_TOKEN in the environment or .env. The output is raw Stake
market names/outcomes and cannot be passed directly to monetary admission.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sefirot.contracts import Policy
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.stake_provider import exact_event, fixture_markets, research_snapshot, sports_events
from sefirot.stake_mapper import normalize_snapshot


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("prediction_id")
    parser.add_argument("--db", default="data/sefirot.sqlite")
    parser.add_argument("--sport", default="soccer")
    parser.add_argument("--first", type=int, default=50)
    parser.add_argument("--output", required=True)
    parser.add_argument("--normalized-output")
    args = parser.parse_args(argv)

    destination = Path(args.output)
    normalized_destination = Path(args.normalized_output or (args.output + ".normalized.json"))
    if destination.exists() or normalized_destination.exists():
        raise SystemExit("Stake output already exists")

    database = Path(args.db).resolve()
    if not database.is_file():
        raise SystemExit("ledger does not exist")

    repo = Repository(database, read_only=True)
    try:
        if not repo.verify():
            raise SystemExit("journal integrity failed")
        service = Service(repo, Policy())
        prediction = repo.get("predictions", args.prediction_id)
        received = service.now()
        packet = sports_events(first=args.first, sport_slug=args.sport, match_type="active")
        event = exact_event(packet["events"], prediction, received)
        market_packet = fixture_markets(event["slug"])
        receipts = [packet["receipt"]] + market_packet["receipts"]
        report = research_snapshot(event, prediction, received, market_packet["markets"], receipts)
        normalized = normalize_snapshot(report)
    finally:
        repo.close()

    destination.parent.mkdir(parents=True, exist_ok=True)
    normalized_destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    with normalized_destination.open("x", encoding="utf-8") as file:
        json.dump(normalized, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    print(json.dumps({
        "status": report["status"],
        "provider": report["provider"],
        "event_id": report["stake_event_id"],
        "market_count": report["market_count"],
        "main_quote_count": normalized["main_quote_count"],
        "small_quote_count": normalized["small_quote_count"],
        "output": str(destination.resolve()),
        "normalized_output": str(normalized_destination.resolve()),
        "monetary_permission": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
