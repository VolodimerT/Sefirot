"""Explicit, network-free research plan for API-Football context expansion."""
import argparse
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.football_enrichment import plan_fixture_enrichment


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bounded API-Football request plan; no network calls')
    parser.add_argument('--fixture-packet', type=Path, required=True)
    parser.add_argument('--league-packet', type=Path, required=True)
    parser.add_argument('--status-packet', type=Path, required=True)
    parser.add_argument('--fixture-id', type=int, required=True)
    parser.add_argument('--max-calls', type=int, default=6)
    parser.add_argument('--reserve', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        def load(path):
            if path.stat().st_size > 4_000_000:
                raise ValueError('packet exceeds bound')
            return json.loads(path.read_text(encoding='utf-8'))
        report = plan_fixture_enrichment(
            load(args.fixture_packet), load(args.league_packet), load(args.status_packet),
            args.fixture_id, at=datetime.now(timezone.utc).isoformat(),
            max_calls=args.max_calls, reserve=args.reserve)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as target:
            json.dump(report, target, ensure_ascii=False, indent=2, allow_nan=False)
            target.write('\n')
        print(json.dumps({'status': report['status'], 'planned_calls': len(report['requested']),
             'budget': report['quota']['budget'], 'hash': report['hash'],
             'monetary_permission': False, 'execution_enabled': False}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        print(json.dumps({'status': 'RESEARCH_PLAN_REJECTED', 'reason': 'INVALID_OR_UNAVAILABLE_RECEIPT',
              'monetary_permission': False, 'execution_enabled': False}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
