"""Read-only P0 adapter. Write JSON to stdout; never alter input files or fit models."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.contracts import time
from research.source_adapter_v3 import adapt_sources


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path)
    p.add_argument('--database',type=Path)
    p.add_argument('--cutoff',required=True)
    p.add_argument('--league-id',required=True,type=int)
    p.add_argument('--season',required=True,type=int)
    p.add_argument('--profile',required=True,choices=('MEN','WOMEN','RESERVE','LOWER'))
    a=p.parse_args(argv)
    if time(a.cutoff)>datetime.now(timezone.utc): p.error('cutoff is in the future')
    report=adapt_sources(archive=a.archive,database=a.database,cutoff=a.cutoff,
                         league_id=a.league_id,season=a.season,profile=a.profile)
    print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
