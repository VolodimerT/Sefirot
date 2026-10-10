"""Explicit offline ARENA 1.0 diagnostic registry; no network/LLM/runtime mode."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from research.arena1.registry import read_bound, register


def load_json(path):
    source = Path(path)
    if source.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('bounded offline input required')
    return json.loads(source.read_text(encoding='utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='ARENA 1.0 diagnostics; KEEP_SHADOW; no monetary permission')
    parser.add_argument('--prediction', required=True)
    parser.add_argument('--quotes', help='optional original post-seal quotes; missing is UNKNOWN')
    parser.add_argument('--at', required=True)
    parser.add_argument('--db', help='existing compatible original ledger, read-only')
    parser.add_argument('--decision-id')
    parser.add_argument('--legacy-reviews', help='optional v0.2 findings; veto entailment remains unverified')
    parser.add_argument('--findings', help='complete deterministic diagnostic replay; new facts forbidden')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--registry', help='separate directory for one new immutable research record')
    action.add_argument('--verify', help='read and reproduce an existing registry record')
    args = parser.parse_args(argv)
    try:
        prediction = load_json(args.prediction)
        quotes = load_json(args.quotes) if args.quotes else []
        options = {'database': args.db, 'decision_id': args.decision_id,
                   'legacy_reviews': load_json(args.legacy_reviews) if args.legacy_reviews else None,
                   'recorded_findings': load_json(args.findings) if args.findings else None}
        if args.verify:
            report = read_bound(args.verify, prediction, quotes, args.at, **options)
            path = Path(args.verify)
        else:
            path, report = register(args.registry, prediction, quotes, args.at, **options)
        print(json.dumps({'schema': report['schema'], 'record': str(path), 'hash': report['hash'],
                          'findings': len(report['findings']), 'empirical_status': report['empirical_status'],
                          'model_action': report['model_action'], 'monetary_permission': False}))
        return 0
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
        parser.exit(2, 'ARENA diagnostic error: ' + str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
