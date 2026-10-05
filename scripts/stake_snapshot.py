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
from sefirot.stake_provider import exact_event, research_snapshot, sports_events


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("prediction_id")
    parser.add_argument("--db", default="data/sefirot.sqlite")
    parser.add_argument("--sport", default="football")
    parser.add_argument("--first", type=int, default=50)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    destination = Path(args.output)
    if destination.exists():
        raise SystemExit("output already exists")

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
        packet = sports_events(first=args.first, sport_slug=args.sport)
        event = exact_event(packet["events"], prediction, received)
        report = research_snapshot(event, prediction, received, packet["receipt"])
    finally:
        repo.close()

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    print(json.dumps({
        "status": report["status"],
        "provider": report["provider"],
        "event_id": report["stake_event_id"],
        "market_count": report["market_count"],
        "output": str(destination.resolve()),
        "monetary_permission": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
