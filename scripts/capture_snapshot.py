"""Capture one manually sourced prematch sports snapshot; no market data or bets."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot_core import CaptureJournal, Fact, SportsOnlySnapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Record a prematch observation; no betting verdict")
    parser.add_argument("--journal", type=Path, required=True, help="one JSONL file per match")
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--kickoff", required=True, help="timezone-aware ISO 8601, e.g. 2026-10-01T19:00:00+03:00")
    parser.add_argument("--home", required=True)
    parser.add_argument("--away", required=True)
    parser.add_argument("--source", required=True, help="human-readable original source URL or document ID")
    parser.add_argument("--published-at", required=True, help="source's documented publication time, ISO 8601")
    parser.add_argument("--confirmed", action="store_true",
                        help="assert you independently checked the source and team identities")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    try:
        kickoff = datetime.fromisoformat(args.kickoff)
        published = datetime.fromisoformat(args.published_at)
        kind = "FACT" if args.confirmed else "ASSUMPTION"
        facts = tuple(Fact(key, value, args.source, published, now, kind) for key, value in (
            ("sports.home_team", args.home), ("sports.away_team", args.away)))
        snapshot = SportsOnlySnapshot(args.match_id, kickoff, now, facts)
        record = CaptureJournal(args.journal).capture_snapshot(snapshot)
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))
    print(f"CAPTURED {record.hash} at {record.recorded_at.isoformat()}")
    print(f"SNAPSHOT {snapshot.digest()} | evidence={kind} | monetary verdict=PASS")
    print("Source publication time and confirmation are user assertions; local receipt is not independent proof.")


if __name__ == "__main__":
    main()
