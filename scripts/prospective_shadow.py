"""Run the existing prospective collector in sports-only SHADOW mode."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

from research.football_pipeline import ingest
from research.prospective_shadow import enqueue, fetch_approved, plan_next, render, report, run
from sefirot.repository import Repository
from sefirot.service import Service


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True, help='dedicated shadow ledger')
    parser.add_argument('--source-db', type=Path, required=True, help='dedicated original-source ledger')
    steps = parser.add_subparsers(dest='step', required=True)
    load = steps.add_parser('import', help='ingest original files without provider calls')
    load.add_argument('packets', type=Path, nargs='+')
    add = steps.add_parser('enqueue', help='queue one future fixture')
    add.add_argument('fixture_id', type=int)
    discover = steps.add_parser('plan-next', help='review archived upcoming matches and queue one qualified fixture')
    discover.add_argument('--league', type=int, required=True)
    discover.add_argument('--limit', type=int, default=20)
    for selection in (add, discover):
        selection.add_argument('--profile', required=True, choices=('MEN', 'WOMEN', 'RESERVE', 'LOWER'))
        selection.add_argument('--source-reliability', type=float, required=True,
                               help='explicit source assertion under existing Policy')
    for name in ('capture', 'settle'):
        steps.add_parser(name, help='process the saved queue without provider calls').add_argument('--limit', type=int, default=20)
    view = steps.add_parser('report', help='read-only fixture and scorecard status')
    view.add_argument('--text', action='store_true')
    approved = steps.add_parser('collect', help='consume exactly one explicit operator approval via shared gateway')
    approved.add_argument('--phase', choices=('NS', 'FT', 'calendar'), required=True)
    approved.add_argument('--fixture-id', type=int)
    approved.add_argument('--date')
    approved.add_argument('--league', type=int)
    approved.add_argument('--season', type=int)
    approved.add_argument('--approval-id', required=True, help='unique alphanumeric operator approval identifier')
    approved.add_argument('--expires-at', required=True, help='explicit timezone and at most 15 minutes from now')
    args = parser.parse_args(argv)
    if (args.db.resolve() == args.source_db.resolve()
            or (args.db.exists() and args.source_db.exists() and args.db.samefile(args.source_db))):
        parser.error('source and shadow ledgers must be different files')
    try:
        if args.step == 'import':
            args.source_db.parent.mkdir(parents=True, exist_ok=True)
            with closing(Repository(args.source_db)) as source:
                result = [ingest(source, file.read_bytes()) for file in args.packets]
        else:
            if not args.source_db.is_file() or (args.step == 'report' and not args.db.is_file()):
                raise ValueError('source ledger required, and report also requires a shadow ledger')
            if args.step != 'report':
                args.db.parent.mkdir(parents=True, exist_ok=True)
            with closing(Repository(args.db, read_only=args.step == 'report')) as ledger, closing(
                    Repository(args.source_db, read_only=args.step != 'collect')) as source:
                service = Service(ledger)
                if args.step == 'enqueue':
                    result = enqueue(service, source, args.fixture_id, args.profile, args.source_reliability)
                elif args.step == 'plan-next':
                    result = plan_next(service, source, args.league, args.profile, args.source_reliability,
                                       limit=args.limit)
                elif args.step in ('capture', 'settle'):
                    result = run(service, source, args.step, limit=args.limit)
                elif args.step == 'report':
                    ledger.db.execute('BEGIN')
                    result = report(service, source)
                    if args.text:
                        print(render(result))
                        return 0
                else:
                    day = {k: getattr(args, k) for k in ('date', 'league', 'season') if getattr(args, k) is not None}
                    if day and args.fixture_id is not None:
                        raise ValueError('choose one fixture or one date/league/season')
                    params = {'id': args.fixture_id} if args.fixture_id is not None else day
                    result = fetch_approved(service, source, params, phase=args.phase, expires_at=args.expires_at,
                                            approval_id=args.approval_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 2 if args.step == 'collect' and result['state'] != 'DONE' else 0
    except (ValueError, OSError, sqlite3.Error, TypeError, KeyError) as exc:
        # Provider errors go through the existing probe's allowlisted result.
        # Generic failures omit arbitrary filenames, credentials and payloads.
        if not isinstance(exc, ValueError):
            print('SEFIROT SHADOW: invalid input or ledger unavailable', file=sys.stderr)
        else:
            print('SEFIROT SHADOW: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
