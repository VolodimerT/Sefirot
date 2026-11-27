"""Emit V7 research coverage from an existing dedicated Repository."""
import argparse
import json
from pathlib import Path

from sefirot.repository import Repository
from .data import inspect
from .dispatch import next_plan
from .tactical import profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--scope', nargs=2, action='append', type=int, required=True,
                        metavar=('LEAGUE', 'SEASON'))
    parser.add_argument('--as-of')
    parser.add_argument('--fixture', type=int)
    parser.add_argument('--budget-status', type=Path,
                        help='Emit read-only probe handoff and budget block from a saved observer record')
    args = parser.parse_args()
    repo = Repository(args.source_db, read_only=True)
    try:
        scopes = tuple(map(tuple, args.scope))
        if args.budget_status:
            if not args.as_of or args.fixture is not None:
                parser.error('--budget-status requires --as-of and is incompatible with --fixture')
            budget = json.loads(args.budget_status.read_bytes())
            report = next_plan(repo, scopes, budget, at=args.as_of)
        else:
            report = inspect(repo, scopes, as_of=args.as_of)
            if args.fixture is not None:
                report['tactical_profile'] = profile(report, args.fixture)
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    finally:
        repo.close()


if __name__ == '__main__':
    main()
