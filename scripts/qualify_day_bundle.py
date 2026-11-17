"""Offline qualification of saved originals. No fetching, fitting or DB writes."""
from pathlib import Path
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from sefirot.provider_transport import strict_json_payload
from research.day_bundle import qualify_day


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--day', required=True)
    p.add_argument('--as-of', required=True)
    p.add_argument('--timezone', choices=['UTC','Europe/Kyiv'], default='Europe/Kyiv')
    p.add_argument('--calendar')
    p.add_argument('--archive')
    p.add_argument('--snapshot')
    p.add_argument('--audit')
    a = p.parse_args()
    calendar = strict_json_payload(Path(a.calendar).read_bytes()) if a.calendar else None
    result = qualify_day(day=a.day, as_of=a.as_of, timezone=a.timezone, calendar=calendar,
                         archive=a.archive, snapshot=a.snapshot, audit=a.audit)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
