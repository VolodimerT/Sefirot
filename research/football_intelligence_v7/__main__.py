"""Emit V7 research coverage from an existing dedicated Repository."""
import argparse
import json
from pathlib import Path

from sefirot.repository import Repository
from .data import inspect
from .tactical import profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--scope', nargs=2, action='append', type=int, required=True,
                        metavar=('LEAGUE', 'SEASON'))
    parser.add_argument('--as-of')
    parser.add_argument('--fixture', type=int)
    args = parser.parse_args()
    repo = Repository(args.source_db, read_only=True)
    try:
        report = inspect(repo, map(tuple, args.scope), as_of=args.as_of)
        if args.fixture is not None:
            report['tactical_profile'] = profile(report, args.fixture)
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    finally:
        repo.close()


if __name__ == '__main__':
    main()
