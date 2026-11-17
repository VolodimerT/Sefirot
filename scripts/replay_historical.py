"""Replay one decision on a copy with its exact pinned archived CORE build."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from research.historical_replay import replay_historical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True, help='checkpointed SQLite ledger; never modified')
    parser.add_argument('--decision-id', required=True)
    args = parser.parse_args()
    try:
        result = replay_historical(args.ledger, args.decision_id)
    except (ValueError, OSError) as exc:
        print(json.dumps({'status':'BLOCKED', 'reason':str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
