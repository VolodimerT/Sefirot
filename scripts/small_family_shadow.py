"""Offline family SHADOW report; no provider or model-training command."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"src")]
from research.small_family_shadow import FAMILY_SPECS, family_report
from scripts.small_market_qc import strict_json

def main(argv=None):
    parser=argparse.ArgumentParser(description="SEFIROT small-market SHADOW (offline)")
    parser.add_argument("--family",required=True,choices=sorted(FAMILY_SPECS))
    parser.add_argument("--as-of",required=True)
    parser.add_argument("--input",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args(argv)
    try:
        report=family_report(args.family,data=strict_json(args.input) if args.input else None,at=args.as_of)
        raw=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
        if args.output:
            with args.output.open("x",encoding="utf-8") as handle:handle.write(raw)
        else:print(raw,end="")
        return 0
    except (ValueError,OSError,KeyError,TypeError):
        print("SHADOW_INPUT_REJECTED; no probability or wager",file=sys.stderr)
        return 2
if __name__=="__main__":raise SystemExit(main())
