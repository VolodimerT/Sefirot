"""Read-only offline scanner; emits JSON/Markdown to stdout only."""
from pathlib import Path
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from sefirot.provider_transport import strict_json_payload
from research.daily_scanner import scan_day, render_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calendar', required=True)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--day', required=True, help='UTC date')
    parser.add_argument('--at', required=True, help='Frozen as-of timestamp')
    parser.add_argument('--profile', required=True, choices=['MEN', 'WOMEN', 'RESERVE', 'LOWER'])
    parser.add_argument('--database', help='Existing ledger, opened read-only')
    parser.add_argument('--prices', help='Saved provider event envelopes keyed by fixture ID')
    parser.add_argument('--synthetic', action='store_true', help='Label all data SYNTHETIC_TEST_ONLY')
    parser.add_argument('--markdown', action='store_true')
    args = parser.parse_args()
    calendar = strict_json_payload(Path(args.calendar).read_bytes())
    prices = strict_json_payload(Path(args.prices).read_bytes()) if args.prices else None
    result = scan_day(calendar=calendar, archive=args.archive, day=args.day, at=args.at,
                      profile=args.profile, database=args.database, prices=prices, synthetic=args.synthetic)
    print(render_report(result) if args.markdown else json.dumps(result, ensure_ascii=False, indent=2), end='\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
